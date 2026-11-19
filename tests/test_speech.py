from __future__ import annotations

import threading
from pathlib import Path

from mika.audio.speech import Speaker


class FakeBackend:
    name = "fake"

    def __init__(self, tmp_path: Path, fail_on: str | None = None):
        self.tmp_path = tmp_path
        self.fail_on = fail_on
        self.synthesized: list[str] = []

    def synthesize(self, text: str) -> Path:
        if text == self.fail_on:
            raise RuntimeError("no internet")
        self.synthesized.append(text)
        path = self.tmp_path / f"{len(self.synthesized)}.mp3"
        path.write_bytes(b"audio")
        return path


class FakePlayer:
    def __init__(self, block_first: bool = False):
        self.played: list[str] = []
        self.block_first = block_first
        self.started = threading.Event()
        self.release = threading.Event()

    def play(self, path: Path, should_stop) -> None:
        self.played.append(path.name)
        if self.block_first and len(self.played) == 1:
            self.started.set()
            while not should_stop() and not self.release.is_set():
                self.release.wait(0.01)


class FakeSapi:
    def __init__(self):
        self.spoken: list[str] = []

    def speak(self, text: str) -> None:
        self.spoken.append(text)


def test_sentences_play_in_order_and_temp_files_are_removed(tmp_path):
    backend, player = FakeBackend(tmp_path), FakePlayer()
    speaker = Speaker(backend=backend, player=player, sapi=FakeSapi())
    for sentence in ["Satu.", "Dua.", "Tiga."]:
        speaker.say_async(sentence)
    assert speaker.wait(timeout=5)
    assert player.played == ["1.mp3", "2.mp3", "3.mp3"]
    assert list(tmp_path.iterdir()) == []
    assert speaker.first_audio_at is not None


def test_failed_neural_voice_falls_back_to_windows_voice(tmp_path):
    sapi = FakeSapi()
    speaker = Speaker(backend=FakeBackend(tmp_path, fail_on="Dua."), player=FakePlayer(), sapi=sapi)
    speaker.say_async("Satu.")
    speaker.say_async("Dua.")
    assert speaker.wait(timeout=5)
    assert sapi.spoken == ["Dua."]


def test_stop_drops_queued_sentences(tmp_path):
    player = FakePlayer(block_first=True)
    speaker = Speaker(backend=FakeBackend(tmp_path), player=player, sapi=FakeSapi())
    speaker.say_async("Kalimat panjang pertama.")
    speaker.say_async("Kedua.")
    speaker.say_async("Ketiga.")
    assert player.started.wait(5)
    speaker.stop()  # barge-in
    assert speaker.wait(timeout=5)
    assert player.played == ["1.mp3"]
    assert not speaker.is_speaking()


def test_speaker_works_again_after_stop(tmp_path):
    player = FakePlayer()
    speaker = Speaker(backend=FakeBackend(tmp_path), player=player, sapi=FakeSapi())
    speaker.stop()
    speaker.say("Masih bisa.")
    assert player.played == ["1.mp3"]


def test_disabled_speaker_only_prints(capsys):
    speaker = Speaker(enabled=False, label="Mika")
    speaker.say("Halo.")
    assert "Mika: Halo." in capsys.readouterr().out
    assert speaker.wait(timeout=0.1)


def test_warm_up_synthesizes_without_playing(tmp_path):
    backend, player = FakeBackend(tmp_path), FakePlayer()
    Speaker(backend=backend, player=player, sapi=FakeSapi()).warm_up()
    assert backend.synthesized == ["Halo."]
    assert player.played == [] and list(tmp_path.iterdir()) == []


def test_from_config_picks_backend():
    config = {"assistant_name": "Mika", "voice": {"enabled": True, "provider": "edge"}}
    assert Speaker.from_config(config).backend.name == "edge"
    config["voice"]["provider"] = "sapi"
    assert Speaker.from_config(config).backend is None
    config["voice"]["enabled"] = False
    assert Speaker.from_config(config).enabled is False


def test_recent_speech_and_audio_end_are_tracked_for_echo_rejection(tmp_path):
    speaker = Speaker(backend=FakeBackend(tmp_path), player=FakePlayer(), sapi=FakeSapi())
    speaker.say("Menurut Kompas, harga emas naik.")
    assert speaker.recent_speech(20) == ["Menurut Kompas, harga emas naik."]
    assert speaker.recent_speech(0) == []
    assert speaker.last_audio_end is not None and not speaker.is_speaking()
