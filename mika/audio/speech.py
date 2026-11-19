"""Speech queue: sentence N+1 is synthesized while sentence N plays, so Mika starts talking before the LLM finishes."""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from ..text import safe_print
from .tts import AudioPlayer, PygamePlayer, SapiVoice, TTSBackend, build_backend, init_com_for_thread


class Speaker:
    """Two worker threads (synthesize, play) fed by a queue; stop() is the barge-in hook."""

    def __init__(
        self,
        enabled: bool = True,
        backend: TTSBackend | None = None,
        *,
        player: AudioPlayer | None = None,
        sapi: Any = None,
        label: str = "Assistant",
        provider: str = "sapi",
        config: dict[str, Any] | None = None,
    ):
        self.enabled = enabled
        self.backend = backend
        self.player = player or PygamePlayer()
        self.config = config or {}
        self.sapi = sapi or SapiVoice(self.config)
        self.label = label
        self.provider = provider
        self.first_audio_at: float | None = None
        self.last_audio_end: float | None = None  # for the echo "tail" right after Mika stops
        self._recent: deque[tuple[float, str]] = deque(maxlen=20)  # what was played, for echo rejection
        self._generation = 0
        self._pending = 0
        self._cv = threading.Condition()
        self._text_queue: queue.Queue[tuple[int, str]] = queue.Queue()
        self._audio_queue: queue.Queue[tuple[int, str, Path | None]] = queue.Queue()
        self._threads_started = False

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "Speaker":
        """Pick Edge, Coqui, or Windows SAPI from commands.json."""
        voice_config = config.get("voice", {})
        label = str(config.get("assistant_name", "Assistant"))
        if not voice_config.get("enabled", True):
            return cls(enabled=False, label=label, config=voice_config)
        provider = str(voice_config.get("provider", "sapi")).lower()
        backend = build_backend(provider, voice_config)
        return cls(
            enabled=True,
            backend=backend,
            label=label,
            provider=backend.name if backend else "sapi",
            config=voice_config,
        )

    # Public API -----------------------------------------------------------------------

    def say(self, message: str) -> None:
        """Blocking speak, same contract as the original Speaker.say."""
        self.say_async(message)
        self.wait()

    def say_async(self, message: str) -> None:
        """Queue one sentence and return immediately (used by the streaming agent)."""
        text = message.strip()
        if not text:
            return
        safe_print(f"{self.label}: {text}")
        if not self.enabled:
            return
        self._ensure_workers()
        with self._cv:
            self._pending += 1
            generation = self._generation
        self._text_queue.put((generation, text))

    def wait(self, timeout: float | None = None) -> bool:
        """Block until everything queued has been spoken (so Mika never hears herself)."""
        with self._cv:
            return self._cv.wait_for(lambda: self._pending == 0, timeout=timeout)

    def stop(self) -> None:
        """Drop queued sentences and cut the one playing (barge-in)."""
        with self._cv:
            self._generation += 1

    def is_speaking(self) -> bool:
        """True while sentences are queued or playing."""
        with self._cv:
            return self._pending > 0

    def recent_speech(self, seconds: float = 20) -> list[str]:
        """Sentences played in the last `seconds`; the mic may be hearing them back."""
        now = time.perf_counter()
        return [text for started, text in list(self._recent) if now - started <= seconds]

    def warm_up(self) -> None:
        """Synthesize a throwaway phrase at startup: the first Edge TTS call takes ~3 s, later ones ~0.5 s."""
        if not self.enabled or self.backend is None:
            return
        try:
            self.backend.synthesize("Halo.").unlink(missing_ok=True)
        except Exception as exc:
            safe_print(f"[tts] Pemanasan {self.backend.name} gagal: {exc}")

    def mark_turn(self) -> None:
        """Start a new latency measurement; first_audio_at is set when playback begins."""
        self.first_audio_at = None

    # Workers --------------------------------------------------------------------------

    def _ensure_workers(self) -> None:
        """Start the synth and play threads on first use."""
        if self._threads_started:
            return
        self._threads_started = True
        threading.Thread(target=self._synth_loop, name="mika-tts-synth", daemon=True).start()
        threading.Thread(target=self._play_loop, name="mika-tts-play", daemon=True).start()

    def _is_current(self, generation: int) -> bool:
        """Items queued before the last stop() belong to an old generation and are skipped."""
        return generation == self._generation

    def _finish_item(self) -> None:
        """Mark one sentence done and wake up wait()."""
        with self._cv:
            self._pending = max(0, self._pending - 1)
            self._cv.notify_all()

    def _synth_loop(self) -> None:
        """Worker 1: text → audio file, running ahead of playback."""
        init_com_for_thread()
        while True:
            generation, text = self._text_queue.get()
            if not self._is_current(generation):
                self._finish_item()
                continue
            audio: Path | None = None
            if self.backend is not None:
                try:
                    audio = self.backend.synthesize(text)
                except Exception as exc:
                    safe_print(f"[tts] {self.backend.name} gagal ({exc}); pakai suara Windows.")
            self._audio_queue.put((generation, text, audio))

    def _play_loop(self) -> None:
        """Worker 2: play audio in order; fall back to the Windows voice if synthesis failed."""
        init_com_for_thread()
        while True:
            generation, text, audio = self._audio_queue.get()
            try:
                if not self._is_current(generation):
                    continue
                if self.first_audio_at is None:
                    self.first_audio_at = time.perf_counter()
                self._recent.append((time.perf_counter(), text))
                if audio is not None:
                    self.player.play(audio, lambda: not self._is_current(generation))
                else:
                    self.sapi.speak(text)
                self.last_audio_end = time.perf_counter()
            except Exception as exc:
                safe_print(f"[voice] Gagal memutar suara: {exc}")
            finally:
                if audio is not None:
                    try:
                        audio.unlink(missing_ok=True)
                    except OSError:
                        pass
                self._finish_item()
