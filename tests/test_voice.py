"""Voice input, barge-in policy, and the wake-phrase loop, with a fake microphone, STT, and speaker."""

from __future__ import annotations

import threading
import time

import pytest

from mika.audio.stt import Transcript
from mika.audio.vad import FRAME_BYTES, EnergyVAD, Utterance
from mika.audio.voice import Heard, VoiceInput, decide_barge_in, is_echo
from mika.voice_loop import VoiceLoop
from tests.test_vad import silence, tone

WAKE = {"enabled": True, "phrases": ["halo mika", "hai mika"], "match_anywhere": True, "next_command_seconds": 8}
STOP_WORDS = ["stop", "berhenti", "diam", "cukup", "udah"]


class FakeSTT:
    name = "fake"

    def __init__(self, *texts: str):
        self.texts = list(texts)
        self.warmed = False

    def warm_up(self):
        self.warmed = True

    def transcribe(self, utterance):
        text = self.texts.pop(0) if self.texts else ""
        if text.startswith("!"):
            return Transcript("", 0.1, self.name, dropped=text[1:])
        return Transcript(text, 0.12, self.name)


class TalkingSpeaker:
    def __init__(self, speaking=False, recent=()):
        self.speaking = speaking
        self.recent = list(recent)
        self.last_audio_end = None
        self.said = []

    def is_speaking(self):
        return self.speaking

    def recent_speech(self, seconds=20):
        return self.recent

    def say(self, text):
        self.said.append(text)


def make_voice(config, stt, speaker=None, mode="keyword", interrupts=None, source_factory=None):
    config["barge_in"]["mode"] = mode
    calls = interrupts if interrupts is not None else []
    return VoiceInput(
        config,
        speaker or TalkingSpeaker(),
        stt,
        interrupt=lambda: calls.append("interrupt"),
        source_factory=source_factory,
        vad=EnergyVAD(),
    )


def utt(during_playback=False):
    return Utterance(bytes(FRAME_BYTES * 20), started_at=10.0, speech_end_at=10.6, during_playback=during_playback)


# Echo rejection and barge-in decisions -------------------------------------------------------


@pytest.mark.parametrize(
    ("heard", "recent", "echo"),
    [
        ("menurut kompas harga emas naik", ["Menurut Kompas, harga emas naik sedikit hari ini."], True),
        ("harga emas naik sedikit", ["Menurut Kompas, harga emas naik sedikit hari ini."], True),
        ("halo mika", ["Halo, aku Mika. Panggil aku dengan Halo Mika."], True),
        ("mika stop", ["Oke, Mika bukain Spotify ya."], False),
        ("stop", ["Menurut Kompas, harga emas naik sedikit hari ini."], False),
        ("buka youtube", [], False),
    ],
)
def test_is_echo(heard, recent, echo):
    assert is_echo(heard, recent) is echo


@pytest.mark.parametrize(
    ("heard", "decision"),
    [
        ("stop", ("stop", "")),
        ("udah cukup", ("stop", "")),
        ("halo mika buka youtube", ("command", "halo mika buka youtube")),
        ("halo mika", ("command", "halo mika")),
        ("harga emas naik sedikit", ("ignore", "")),  # Mika's own voice
        ("eh tadi aku mau bilang sesuatu yang panjang banget", ("ignore", "")),  # chatter, not a command
    ],
)
def test_decide_barge_in(heard, decision):
    recent = ["Menurut Kompas, harga emas naik sedikit hari ini."]
    assert decide_barge_in(heard, recent, WAKE, STOP_WORDS) == decision


# VoiceInput routing ---------------------------------------------------------------------------


def test_normal_utterance_is_transcribed_with_timing(config):
    voice = make_voice(config, FakeSTT("halo mika buka youtube"))
    voice.dispatch(utt())
    heard = voice.next(timeout=0.5)
    assert (heard.text, heard.speech_end_at, heard.stt_seconds, heard.barge_in) == ("halo mika buka youtube", 10.6, 0.12, False)


def test_rejected_transcripts_are_skipped(config):
    voice = make_voice(config, FakeSTT("!halusinasi khas saat hening", "buka youtube"))
    voice.dispatch(utt())
    voice.dispatch(utt())
    assert voice.next(timeout=0.5).text == "buka youtube"


def test_mode_off_ignores_speech_over_mika(config):
    interrupts = []
    voice = make_voice(config, FakeSTT("halo mika stop"), mode="off", interrupts=interrupts)
    voice.dispatch(utt(during_playback=True))
    assert voice.next(timeout=0.1) is None and interrupts == []


def test_keyword_mode_stop_word_interrupts_silently(config):
    interrupts = []
    voice = make_voice(config, FakeSTT("stop"), TalkingSpeaker(True, ["Menurut Kompas, harga emas naik."]), interrupts=interrupts)
    assert voice.handle_barge_in(utt(True)) == "stop"
    assert interrupts == ["interrupt"] and voice.next(timeout=0.1) is None


def test_keyword_mode_ignores_mikas_own_voice(config):
    interrupts = []
    speaker = TalkingSpeaker(True, ["Menurut Kompas, harga emas naik sedikit hari ini."])
    voice = make_voice(config, FakeSTT("harga emas naik sedikit hari ini"), speaker, interrupts=interrupts)
    assert voice.handle_barge_in(utt(True)) == "ignore" and interrupts == []


def test_keyword_mode_wake_command_interrupts_and_runs(config):
    interrupts = []
    voice = make_voice(config, FakeSTT("halo mika lagu berikutnya"), TalkingSpeaker(True, ["Oke, lanjut."]), interrupts=interrupts)
    assert voice.handle_barge_in(utt(True)) == "command"
    heard = voice.next(timeout=0.5)
    assert interrupts == ["interrupt"] and heard.barge_in and heard.text == "halo mika lagu berikutnya"


def test_voice_mode_interrupts_at_speech_start(config):
    interrupts = []
    voice = make_voice(config, FakeSTT("ganti lagu"), mode="voice", interrupts=interrupts)
    voice.on_speech_start(during_playback=True)
    voice.on_speech_start(during_playback=False)
    assert interrupts == ["interrupt"]
    voice.dispatch(utt(True))
    heard = voice.next(timeout=0.5)
    assert heard.barge_in and heard.text == "ganti lagu"


class ScriptedMic:
    """Plays a fixed frame pattern, then silence, 30 ms per frame (sped up)."""

    def __init__(self, pattern: str):
        self.frames = [tone() if char == "#" else silence() for char in pattern]
        self.opened = self.closed = False

    def open(self):
        self.opened = True

    def read(self):
        time.sleep(0.001)
        return self.frames.pop(0) if self.frames else silence()

    def close(self):
        self.closed = True


def test_end_to_end_from_microphone_frames(config):
    mic = ScriptedMic("." * 10 + "#" * 25 + "." * 30)
    stt = FakeSTT("halo mika jam berapa")
    voice = make_voice(config, stt, source_factory=lambda: mic)
    voice.start()
    try:
        heard = voice.next(timeout=3)
    finally:
        voice.stop()
    assert heard.text == "halo mika jam berapa"
    assert mic.opened and mic.closed and stt.warmed


def test_mic_errors_surface_on_start(config):
    class BrokenMic(ScriptedMic):
        def open(self):
            raise OSError("Mikrofon tidak bisa dibuka: device unavailable")

    voice = make_voice(config, FakeSTT(), source_factory=lambda: BrokenMic(""))
    with pytest.raises(OSError):
        voice.start()
    assert not voice.is_running


# Wake-phrase loop -----------------------------------------------------------------------------


class LoopAssistant:
    def __init__(self, config):
        self.config = config
        self.pending_action = None
        self.active = False
        self.speaker = TalkingSpeaker()
        self.handled = []

    def strip_wake_prefix(self, text):
        from mika.audio.wake import strip_wake_prefix

        return strip_wake_prefix(text, self.config["wake"])

    def conversation_is_active(self):
        return self.active

    def handle(self, command, heard=None):
        self.handled.append((command, heard))
        return command != "keluar"


def heard(text, barge_in=False):
    return Heard(text, speech_end_at=1.0, stt_seconds=0.1, engine="fake", barge_in=barge_in)


def test_wake_gate(config):
    now = [100.0]
    assistant = LoopAssistant(config)
    loop = VoiceLoop(assistant, voice=None, clock=lambda: now[0])
    assert loop.prepare(heard("tv bilang sesuatu")) is None
    assert loop.prepare(heard("halo mika buka youtube")) == "buka youtube"
    assert loop.prepare(heard("halo mika")) is None
    assert assistant.speaker.said == ["Iya, Mika denger."]
    assert loop.prepare(heard("buka youtube")) == "buka youtube"  # within the 8 s window
    now[0] += 20
    assert loop.prepare(heard("buka youtube")) is None
    assert loop.prepare(heard("lagu berikutnya", barge_in=True)) == "lagu berikutnya"
    assistant.active = True
    assert loop.prepare(heard("makasih ya")) == "makasih ya"
    assistant.active = False
    assistant.pending_action = object()
    assert loop.prepare(heard("iya")) == "iya"


def test_loop_step_hands_heard_to_assistant(config):
    assistant = LoopAssistant(config)

    class Voice:
        def __init__(self, items):
            self.items = list(items)

        def next(self, timeout=None):
            return self.items.pop(0) if self.items else None

    loop = VoiceLoop(assistant, Voice([heard("halo mika jam berapa"), heard("halo mika keluar")]))
    assert loop.step() is True
    assert assistant.handled[0][0] == "jam berapa" and assistant.handled[0][1].engine == "fake"
    assert loop.step() is False  # "keluar" stops the loop
    assert loop.step() is True  # nothing heard


def test_capture_test_takes_the_next_utterance(config):
    assistant = LoopAssistant(config)

    class SlowVoice:
        def __init__(self):
            self.sent = False

        def next(self, timeout=None):
            time.sleep(0.05)
            if self.sent:
                return None
            self.sent = True
            return heard("halo mika buka youtube")

    loop = VoiceLoop(assistant, SlowVoice())
    result = {}
    tester = threading.Thread(target=lambda: result.setdefault("heard", loop.capture_test(timeout=2)))
    tester.start()
    time.sleep(0.01)
    while tester.is_alive():
        loop.step(timeout=0.1)
    assert result["heard"].text == "halo mika buka youtube"
    assert assistant.handled == []  # the test utterance is not executed


def test_whisper_punctuation_does_not_break_commands(config):
    from mika.text import clean_transcript

    assert clean_transcript("Kecilkan volume.") == "Kecilkan volume"
    assert clean_transcript("Halo Mika, buka kompas.com!") == "Halo Mika buka kompas.com"
    assert clean_transcript("Ingatkan aku jam 19.30, ya?") == "Ingatkan aku jam 19.30 ya"
    voice = make_voice(config, FakeSTT("Halo Mika, kecilkan volume."))
    voice.dispatch(utt())
    assert voice.next(timeout=0.5).text == "Halo Mika kecilkan volume"
