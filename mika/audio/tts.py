"""Text-to-speech backends (Edge neural, Coqui XTTS, Windows SAPI) and the audio player."""

from __future__ import annotations

import asyncio
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Protocol

from ..text import normalize


class TTSBackend(Protocol):
    name: str

    def synthesize(self, text: str) -> Path:
        """Render text to an audio file and return its path. Raise on failure."""
        ...


class AudioPlayer(Protocol):
    def play(self, path: Path, should_stop: Callable[[], bool]) -> None: ...


def _temp_audio_path(suffix: str) -> Path:
    handle, path = tempfile.mkstemp(prefix="mika_", suffix=suffix)
    os.close(handle)
    return Path(path)


class EdgeBackend:
    name = "edge"

    def __init__(self, voice_config: dict[str, Any]):
        self.voice = str(voice_config.get("edge_voice", "id-ID-GadisNeural"))
        self.rate = str(voice_config.get("edge_rate", "+0%"))
        self.volume = str(voice_config.get("edge_volume", "+0%"))
        self.pitch = str(voice_config.get("edge_pitch", "+0Hz"))

    def synthesize(self, text: str) -> Path:
        import edge_tts

        path = _temp_audio_path(".mp3")
        communicate = edge_tts.Communicate(
            text=text, voice=self.voice, rate=self.rate, volume=self.volume, pitch=self.pitch
        )
        try:
            # Runs on the synthesis worker thread, which has no event loop of its own.
            asyncio.run(communicate.save(str(path)))
            if path.stat().st_size == 0:
                raise RuntimeError("Edge TTS mengembalikan audio kosong")
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return path


class CoquiBackend:
    name = "coqui"

    def __init__(self, voice_config: dict[str, Any]):
        self.config = voice_config
        self._tts: Any = None
        self._lock = threading.Lock()

    def _model(self) -> Any:
        # Cached: the old code reloaded XTTS for every sentence, which costs seconds each time.
        if self._tts is None:
            from TTS.api import TTS

            model_path = str(self.config.get("coqui_model_path", "")).strip()
            config_path = str(self.config.get("coqui_config_path", "")).strip()
            use_gpu = bool(self.config.get("coqui_gpu", False))
            if model_path and config_path:
                self._tts = TTS(model_path=model_path, config_path=config_path, progress_bar=False, gpu=use_gpu)
            else:
                model_name = str(self.config.get("coqui_model", "tts_models/multilingual/multi-dataset/xtts_v2"))
                self._tts = TTS(model_name=model_name, progress_bar=False, gpu=use_gpu)
        return self._tts

    def synthesize(self, text: str) -> Path:
        path = _temp_audio_path(".wav")
        args: dict[str, Any] = {"text": text, "file_path": str(path)}
        speaker_wav = str(self.config.get("coqui_speaker_wav", "")).strip()
        language = str(self.config.get("coqui_language", "id")).strip() or "id"
        if speaker_wav:
            args["speaker_wav"] = speaker_wav
        if language:
            args["language"] = language
        try:
            with self._lock:
                self._model().tts_to_file(**args)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return path


class SapiVoice:
    """Windows built-in voice. Used as the primary voice for provider "sapi" and as the
    last-resort fallback when Edge (needs internet) or Coqui fails."""

    def __init__(self, voice_config: dict[str, Any]):
        self.config = voice_config

    def speak(self, text: str) -> None:
        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", int(self.config.get("rate", 175)))
        engine.setProperty("volume", float(self.config.get("volume", 1.0)))
        requested = normalize(str(self.config.get("name_contains", "")))
        if requested:
            for voice in engine.getProperty("voices"):
                if requested in normalize(f"{voice.name} {voice.id}"):
                    engine.setProperty("voice", voice.id)
                    break
        engine.say(text)
        engine.runAndWait()


class PygamePlayer:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    def play(self, path: Path, should_stop: Callable[[], bool]) -> None:
        import pygame

        with self._lock:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.play()
            try:
                while pygame.mixer.music.get_busy():
                    if should_stop():
                        pygame.mixer.music.stop()
                        break
                    time.sleep(0.02)
            finally:
                try:
                    pygame.mixer.music.unload()
                except Exception:
                    pass


def build_backend(provider: str, voice_config: dict[str, Any]) -> TTSBackend | None:
    provider = provider.lower()
    if provider == "edge":
        return EdgeBackend(voice_config)
    if provider in {"coqui", "coqui_tts", "coqui_xtts", "xtts"}:
        return CoquiBackend(voice_config)
    return None  # "sapi": spoken directly by SapiVoice


def init_com_for_thread() -> None:
    """pyttsx3/SAPI talks to COM, which must be initialised on every thread that uses it."""
    try:
        import comtypes

        comtypes.CoInitialize()
    except Exception:
        pass
