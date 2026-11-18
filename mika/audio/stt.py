"""Speech-to-text. Stage 1 keeps the existing Google Web Speech path (via SpeechRecognition);
stage 3 adds offline faster-whisper + VAD behind the same function."""

from __future__ import annotations

from typing import Any

from ..text import safe_print


def listen_once(
    config: dict[str, Any],
    speaker: Any,
    quiet: bool = False,
    timeout_override: int | None = None,
    phrase_time_limit_override: int | None = None,
) -> str | None:
    try:
        import speech_recognition as sr
    except ImportError:
        speaker.say(
            "Library speech recognition belum terpasang. Jalankan mode ketik dulu, atau install requirements."
        )
        return None

    recognizer = sr.Recognizer()
    listen_config = config.get("listen", {})
    language = listen_config.get("language", "id-ID")
    device_index = listen_config.get("device_index")
    timeout = int(listen_config.get("timeout_seconds", 6))
    phrase_time_limit = int(listen_config.get("phrase_time_limit_seconds", 8))
    adjust_duration = float(listen_config.get("ambient_adjust_seconds", 0.5))
    recognizer.pause_threshold = float(listen_config.get("pause_threshold", recognizer.pause_threshold))
    recognizer.non_speaking_duration = float(
        listen_config.get("non_speaking_duration", recognizer.non_speaking_duration)
    )
    recognizer.dynamic_energy_threshold = bool(
        listen_config.get("dynamic_energy_threshold", recognizer.dynamic_energy_threshold)
    )
    energy_threshold = listen_config.get("energy_threshold")
    if energy_threshold not in (None, ""):
        recognizer.energy_threshold = int(energy_threshold)
    if timeout_override is not None:
        timeout = timeout_override
    if phrase_time_limit_override is not None:
        phrase_time_limit = phrase_time_limit_override
    if device_index == "":
        device_index = None

    try:
        with sr.Microphone(device_index=device_index) as source:
            safe_print("Mendengarkan...")
            recognizer.adjust_for_ambient_noise(source, duration=adjust_duration)
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
    except sr.WaitTimeoutError:
        if not quiet:
            speaker.say("Aku belum mendengar perintah.")
        return None
    except Exception as exc:
        if quiet:
            safe_print(f"[mic] Mikrofon belum bisa dipakai: {exc}")
        else:
            speaker.say(f"Mikrofon belum bisa dipakai: {exc}")
        return None

    try:
        return recognizer.recognize_google(audio, language=language)
    except sr.UnknownValueError:
        if not quiet:
            speaker.say("Maaf, aku belum menangkap suaramu.")
    except sr.RequestError as exc:
        if quiet:
            safe_print(f"[speech] Layanan pengenal suara sedang bermasalah: {exc}")
        else:
            speaker.say(f"Layanan pengenal suara sedang bermasalah: {exc}")

    return None
