"""Always-on voice input: mic → VAD → utterances → speech-to-text, plus barge-in while Mika is talking."""

from __future__ import annotations

import difflib
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from ..text import clean_transcript, contains_phrase, normalize, plain_words, safe_print
from .capture import FrameSource, PyAudioSource
from .stt import SpeechToText
from .vad import Endpointer, Utterance, VoiceDetector, build_vad, silence_ms_from_config
from .wake import strip_wake_prefix

DEFAULT_STOP_WORDS = ["stop", "berhenti", "diam", "cukup", "udah", "sudah", "skip", "stop mika", "mika diam"]


@dataclass
class Heard:
    """A transcribed utterance with the timing needed for end-of-speech → first-audio latency."""

    text: str
    speech_end_at: float
    stt_seconds: float
    engine: str
    barge_in: bool = False  # it interrupted Mika, so it needs no wake phrase


def is_echo(transcript: str, recent_speech: list[str], threshold: float = 0.7) -> bool:
    """Software echo rejection: on laptop speakers the mic hears Mika herself, so a transcript that matches
    what she just said is treated as her own voice."""
    heard = plain_words(transcript)
    tokens = heard.split()
    if not tokens:
        return True
    spoken_sentences = [plain_words(sentence) for sentence in recent_speech if sentence.strip()]
    spoken = " ".join(spoken_sentences)
    if not spoken:
        return False
    if f" {heard} " in f" {spoken} ":
        return True
    if len(tokens) >= 2:
        spoken_tokens = set(spoken.split())
        if sum(token in spoken_tokens for token in tokens) / len(tokens) >= threshold:
            return True
    return any(difflib.SequenceMatcher(None, heard, sentence).ratio() >= threshold for sentence in spoken_sentences)


def decide_barge_in(
    transcript: str,
    recent_speech: list[str],
    wake_config: dict[str, Any],
    stop_words: list[str],
    echo_threshold: float = 0.7,
) -> tuple[str, str]:
    """("ignore" | "stop" | "command", text) for speech heard while Mika talks (keyword mode)."""
    text = normalize(clean_transcript(transcript))
    if not text or is_echo(text, recent_speech, echo_threshold):
        return "ignore", ""
    matched, _rest = strip_wake_prefix(text, wake_config)
    if matched:
        return "command", text  # "halo mika, buka youtube" or just "halo mika"
    if len(text.split()) <= 4 and any(contains_phrase(text, normalize(word)) for word in stop_words):
        return "stop", ""
    return "ignore", ""


class VoiceInput:
    """Owns the microphone thread. Normal utterances go to next(); utterances heard while Mika speaks go to
    the barge-in policy ("off": dropped, "keyword": stop/wake words only, "voice": any speech interrupts)."""

    def __init__(
        self,
        config: dict[str, Any],
        speaker: Any,
        stt: SpeechToText,
        *,
        interrupt: Callable[[], None] = lambda: None,
        source_factory: Callable[[], FrameSource] | None = None,
        vad: VoiceDetector | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ):
        self.config = config
        self.speaker = speaker
        self.stt = stt
        self.interrupt = interrupt
        listen = config.get("listen", {})
        device = listen.get("device_index")
        self._source_factory = source_factory or (lambda: PyAudioSource(None if device in ("", None) else int(device)))
        self.vad = vad or build_vad(config)
        self._clock = clock
        self.endpointer = self._new_endpointer()
        barge = config.get("barge_in", {})
        self.mode = str(barge.get("mode", "keyword")).lower()
        self.stop_words = list(barge.get("stop_words", DEFAULT_STOP_WORDS))
        self.echo_threshold = float(barge.get("echo_similarity", 0.7))
        self.tail_seconds = float(barge.get("tail_ms", 400)) / 1000
        self.wake_config = config.get("wake", {})
        self._main: queue.Queue[Utterance | Heard] = queue.Queue()
        self._barge: queue.Queue[Utterance | None] = queue.Queue()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.error = ""
        self.level = 0.0  # last frame loudness, for the mic test meter

    # Lifecycle -------------------------------------------------------------------------

    def _new_endpointer(self) -> Endpointer:
        """Endpointer configured from commands.json (pause length follows listen.pause_threshold)."""
        vad_config = self.config.get("stt", {}).get("vad", {})
        return Endpointer(
            silence_ms=silence_ms_from_config(self.config),
            preroll_ms=int(vad_config.get("preroll_ms", 300)),
            min_speech_ms=int(vad_config.get("min_speech_ms", 250)),
            max_seconds=float(vad_config.get("max_utterance_seconds", 12)),
        )

    def start(self) -> None:
        """Open the mic and start the capture and barge-in threads; speech-to-text loads in the background."""
        if self.is_running:
            return
        self._stop.clear()
        self.error = ""
        self.endpointer = self._new_endpointer()  # never resume half an utterance from before a pause
        source = self._source_factory()
        source.open()  # raise here, on the caller's thread, if the mic is unavailable
        self._threads = [
            threading.Thread(target=self._capture_loop, args=(source,), name="mika-mic", daemon=True),
            threading.Thread(target=self._barge_loop, name="mika-barge-in", daemon=True),
            threading.Thread(target=self._warm_stt, name="mika-stt-warmup", daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        """Close the mic and drop anything not yet processed."""
        self._stop.set()
        self._barge.put(None)
        for thread in self._threads:
            if thread is not threading.current_thread() and thread.name != "mika-stt-warmup":
                thread.join(timeout=1.0)
        self._threads = []
        for pending in (self._main, self._barge):
            while not pending.empty():
                pending.get_nowait()

    @property
    def is_running(self) -> bool:
        """True while the capture thread is alive."""
        return any(thread.is_alive() and thread.name == "mika-mic" for thread in self._threads)

    def _warm_stt(self) -> None:
        """Load the STT model (Whisper can take a few seconds) while the user is not talking yet."""
        try:
            self.stt.warm_up()
        except Exception as exc:
            self.error = f"STT gagal dimuat: {exc}"
            safe_print(f"[stt] {self.error}")

    # Consumer side -------------------------------------------------------------------

    def next(self, timeout: float | None = None) -> Heard | None:
        """The next transcribed utterance, or None after `timeout` seconds of nothing usable."""
        deadline = None if timeout is None else self._clock() + timeout
        while True:
            remaining = None if deadline is None else max(0.0, deadline - self._clock())
            try:
                item = self._main.get(timeout=remaining)
            except queue.Empty:
                return None
            if isinstance(item, Heard):
                return item
            heard = self._transcribe(item, barge_in=item.during_playback)
            if heard is not None:
                return heard
            if deadline is not None and self._clock() >= deadline:
                return None

    def _transcribe(self, utterance: Utterance, barge_in: bool = False) -> Heard | None:
        """Speech-to-text with logging; empty or rejected transcripts become None."""
        try:
            result = self.stt.transcribe(utterance)
        except Exception as exc:
            safe_print(f"[stt] Gagal mengenali suara: {exc}")
            return None
        if result.dropped:
            safe_print(f"[stt] diabaikan ({result.dropped})")
        text = clean_transcript(result.text)
        if not text:
            return None
        return Heard(text, utterance.speech_end_at, result.seconds, result.engine, barge_in=barge_in)

    # Producer side -------------------------------------------------------------------

    def _playing(self) -> bool:
        """Mika is talking, or stopped so recently that the room may still echo."""
        if getattr(self.speaker, "is_speaking", lambda: False)():
            return True
        last_end = getattr(self.speaker, "last_audio_end", None)
        return last_end is not None and self._clock() - last_end < self.tail_seconds

    def _capture_loop(self, source: FrameSource) -> None:
        """Read frames forever, run VAD, and hand finished utterances to dispatch()."""
        try:
            while not self._stop.is_set():
                frame = source.read()
                voiced = self.vad.is_speech(frame)
                self.level = float(getattr(self.vad, "last_rms", 0.0))
                event, utterance = self.endpointer.process(frame, voiced, self._clock(), self._playing())
                if event == "start":
                    self.on_speech_start(self.endpointer.during_playback)
                if utterance is not None:
                    self.dispatch(utterance)
        except Exception as exc:
            self.error = f"Mikrofon berhenti: {exc}"
            safe_print(f"[mic] {self.error}")
        finally:
            source.close()

    def on_speech_start(self, during_playback: bool) -> None:
        """Voice mode (headsets): any speech over Mika interrupts her immediately, before the sentence ends."""
        if during_playback and self.mode == "voice":
            self.interrupt()

    def dispatch(self, utterance: Utterance) -> None:
        """Route a finished utterance: normal → next(); over Mika's voice → the barge-in policy."""
        if not utterance.during_playback:
            self._main.put(utterance)
        elif self.mode == "voice":
            self._main.put(utterance)  # already interrupted at speech start; this is the user's command
        elif self.mode == "keyword":
            self._barge.put(utterance)
        # mode "off": speech over Mika is ignored, exactly like before barge-in existed

    def _barge_loop(self) -> None:
        """Keyword mode: transcribe speech heard over Mika and act only on stop or wake words that are not echo."""
        while not self._stop.is_set():
            utterance = self._barge.get()
            if utterance is None:
                return
            self.handle_barge_in(utterance)

    def handle_barge_in(self, utterance: Utterance) -> str:
        """Decide and act on one over-speech utterance; returns the decision (for logs and tests)."""
        heard = self._transcribe(utterance, barge_in=True)
        if heard is None:
            return "ignore"
        recent = getattr(self.speaker, "recent_speech", lambda seconds=20: [])(20)
        decision, text = decide_barge_in(heard.text, recent, self.wake_config, self.stop_words, self.echo_threshold)
        if decision == "ignore":
            safe_print(f"[barge-in] diabaikan (gema atau bukan perintah): {heard.text!r}")
            return decision
        safe_print(f"[barge-in] {decision}: {heard.text!r}")
        self.interrupt()
        if decision == "command":
            heard.text = text
            self._main.put(heard)
        return decision
