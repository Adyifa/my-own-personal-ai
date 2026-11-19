from __future__ import annotations

import math
from array import array

import pytest

from mika.audio.vad import FRAME_BYTES, Endpointer, EnergyVAD, WebRtcVAD, build_vad, frame_rms, silence_ms_from_config

SAMPLES = FRAME_BYTES // 2


def tone(amplitude: int = 8000, frequency: float = 220.0) -> bytes:
    return array("h", (int(amplitude * math.sin(2 * math.pi * frequency * n / 16000)) for n in range(SAMPLES))).tobytes()


def silence() -> bytes:
    return bytes(FRAME_BYTES)


def feed(endpointer: Endpointer, pattern: str, playing: bool = False):
    """pattern: "." = silent frame, "#" = voiced frame; 30 ms per frame starting at t=0."""
    events, utterances = [], []
    for index, char in enumerate(pattern):
        frame = tone() if char == "#" else silence()
        event, utterance = endpointer.process(frame, char == "#", index * 0.03, playing)
        if event:
            events.append((event, index))
        if utterance:
            utterances.append((utterance, index))
    return events, utterances


def test_energy_vad_separates_speech_from_quiet():
    vad = EnergyVAD()
    assert not vad.is_speech(silence())
    assert vad.is_speech(tone(8000))
    assert frame_rms(tone(1000)) == pytest.approx(707, rel=0.02)


def test_energy_vad_learns_steady_background_noise():
    vad = EnergyVAD(min_rms=100)
    fan = tone(1200)  # rms ~850: loud enough to count as speech in a fresh, quiet room
    assert vad.is_speech(fan)
    for _ in range(500):  # 15 s of the same level: that is the room, not a voice
        vad.is_speech(fan)
    assert not vad.is_speech(fan)
    assert vad.is_speech(tone(8000))  # a real voice over the fan still counts


def test_webrtc_vad_when_installed():
    pytest.importorskip("webrtcvad")
    vad = WebRtcVAD(2)
    assert not vad.is_speech(silence())
    assert isinstance(build_vad({"stt": {"vad": {"engine": "auto"}}}), WebRtcVAD)
    assert isinstance(build_vad({"stt": {"vad": {"engine": "energy"}}}), EnergyVAD)


def test_utterance_boundaries_and_preroll():
    endpointer = Endpointer(silence_ms=300, preroll_ms=150, start_ms=90, min_speech_ms=150)
    events, utterances = feed(endpointer, "." * 10 + "#" * 20 + "." * 12)
    assert events == [("start", 12)]  # third voiced frame confirms the start
    (utterance, ended), = utterances
    assert ended == 39  # 10 silent frames (300 ms) after the last voiced one
    assert utterance.started_at == pytest.approx(0.30)  # first voiced frame, not the confirmation
    assert utterance.speech_end_at == pytest.approx(29 * 0.03)
    assert len(utterance.pcm) == (5 + 20 + 10) * FRAME_BYTES  # 150 ms pre-roll + speech + trailing pause
    assert utterance.seconds == pytest.approx(35 * 0.03)


def test_cough_is_dropped_and_short_blips_do_not_start():
    endpointer = Endpointer(silence_ms=300, min_speech_ms=250)
    assert feed(endpointer, "##..." + "#####" + "." * 12)[1] == []  # 5 voiced frames < 250 ms


def test_long_speech_is_cut_at_the_limit():
    endpointer = Endpointer(silence_ms=300, max_seconds=0.6)
    _, utterances = feed(endpointer, "#" * 60)
    assert len(utterances) >= 2 and all(u.seconds <= 0.6 + 0.2 for u, _ in utterances)


def test_playback_flag_is_latched_at_start():
    endpointer = Endpointer(silence_ms=300, min_speech_ms=150)
    _, utterances = feed(endpointer, "#" * 10 + "." * 12, playing=True)
    assert utterances[0][0].during_playback


def test_silence_default_follows_existing_pause_threshold():
    assert silence_ms_from_config({"listen": {"pause_threshold": 0.45}}) == 450
    assert silence_ms_from_config({"stt": {"vad": {"silence_ms": 700}}, "listen": {"pause_threshold": 0.45}}) == 700
    assert silence_ms_from_config({"listen": {"pause_threshold": 0.1}}) == 300
