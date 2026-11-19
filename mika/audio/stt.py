"""Speech-to-text engines: Google (online) or faster-whisper (offline, private); plus the legacy one-shot listener."""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from ..text import clean_transcript, plain_words, safe_print
from .vad import SAMPLE_RATE, SAMPLE_WIDTH, Utterance


@dataclass
class Transcript:
    """What was heard, how long recognition took, and why it was discarded (if it was)."""

    text: str
    seconds: float
    engine: str
    dropped: str = ""  # reason when the text was rejected (silence hallucination, error, ...)


class SpeechToText(Protocol):
    """A speech recognizer the voice input can use (Google, Whisper, or a test fake)."""

    name: str

    def transcribe(self, utterance: Utterance) -> Transcript:
        """Text for one utterance; never raises for "nothing recognized"."""
        ...

    def warm_up(self) -> None:
        """Load models ahead of the first utterance."""
        ...


class GoogleSTT:
    """The original engine: Google Web Speech through SpeechRecognition. Needs internet; audio leaves the laptop."""

    name = "google"

    def __init__(self, language: str = "id-ID", recognizer: Any = None):
        self.language = language
        self._recognizer = recognizer

    def warm_up(self) -> None:
        """Nothing to load."""
        return None

    def transcribe(self, utterance: Utterance) -> Transcript:
        """Send one utterance (as FLAC, done by SpeechRecognition) and return the best guess."""
        import speech_recognition as sr

        recognizer = self._recognizer or sr.Recognizer()
        started = time.perf_counter()
        try:
            text = recognizer.recognize_google(sr.AudioData(utterance.pcm, SAMPLE_RATE, SAMPLE_WIDTH), language=self.language)
            return Transcript(str(text or ""), time.perf_counter() - started, self.name)
        except sr.UnknownValueError:
            return Transcript("", time.perf_counter() - started, self.name, dropped="tidak ada ucapan yang dikenali")
        except sr.RequestError as exc:
            return Transcript("", time.perf_counter() - started, self.name, dropped=f"layanan Google gagal: {exc}")


# Approximate VRAM for faster-whisper with int8_float16 weights, in MB (model + working memory).
WHISPER_VRAM_MB = {
    "tiny": 400, "base": 500, "small": 900, "medium": 1800, "large-v2": 3000, "large-v3": 3000,
    "large-v3-turbo": 2000, "turbo": 2000, "distil-large-v3": 2000,
}

# Whisper "hears" these on silence or noise because they end many subtitled videos in its training data.
_SILENCE_HALLUCINATIONS = {
    "terima kasih", "terima kasih telah menonton", "terima kasih sudah menonton", "terima kasih telah menyaksikan",
    "sampai jumpa", "sampai jumpa di video berikutnya", "sampai jumpa di video selanjutnya", "jangan lupa subscribe",
    "like dan subscribe", "thank you", "thanks for watching", "thank you for watching", "you",
}
_CREDIT_PREFIXES = ("subtitle", "subtitles", "terjemahan oleh", "diterjemahkan oleh", "transcribed by", "amara org")


def hallucination_reason(text: str, no_speech_prob: float, avg_logprob: float, seconds: float) -> str:
    """Why a Whisper transcript looks invented, or "" when it looks real."""
    t = plain_words(text)
    if not t:
        return "kosong"
    if t.startswith(_CREDIT_PREFIXES):
        return "baris kredit subtitle"
    if t in _SILENCE_HALLUCINATIONS and (no_speech_prob > 0.3 or avg_logprob < -0.7 or seconds < 0.6):
        return "halusinasi khas saat hening"
    if no_speech_prob > 0.6 and avg_logprob < -1.0:
        return "kemungkinan besar bukan ucapan"
    if re.search(r"\b(\w+)(?:\s+\1\b){5,}", t):
        return "pengulangan"
    return ""


def gpu_free_mb() -> int | None:
    """Free VRAM of the first NVIDIA GPU via nvidia-smi (no extra Python package), or None without one."""
    try:
        output = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        return int(output.strip().splitlines()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def ollama_on_gpu(base_url: str, model: str) -> bool:
    """True when Ollama already holds the model in VRAM (then nvidia-smi's free memory already accounts for it)."""
    try:
        import httpx

        response = httpx.get(f"{base_url.rstrip('/')}/api/ps", timeout=1.0)
        for row in response.json().get("models", []):
            if str(row.get("name", "")).startswith(model) and int(row.get("size_vram", 0)) > 0:
                return True
    except Exception:
        pass
    return False


def choose_whisper_device(
    requested: str,
    model: str,
    *,
    gpu_free: int | None,
    local_llm: bool,
    llm_loaded: bool,
    llm_reserve_mb: int,
) -> tuple[str, str, str]:
    """(device, compute_type, reason). On a 4 GB GPU the local LLM gets the VRAM and Whisper runs on the CPU."""
    if requested == "cpu":
        return "cpu", "int8", "diminta di config"
    if requested == "cuda":
        return "cuda", "int8_float16", "diminta di config"
    if gpu_free is None:
        return "cpu", "int8", "tidak ada GPU NVIDIA"
    need = WHISPER_VRAM_MB.get(model, 1000)
    if local_llm and not llm_loaded:
        need += llm_reserve_mb  # the LLM will load later and must still fit
    if gpu_free >= need:
        return "cuda", "int8_float16", f"VRAM cukup ({gpu_free} MB bebas, butuh {need} MB)"
    return "cpu", "int8", f"VRAM tidak cukup untuk LLM dan Whisper sekaligus ({gpu_free} MB bebas, butuh {need} MB)"


class WhisperSTT:
    """faster-whisper (CTranslate2) running locally: works offline and no audio leaves the laptop."""

    name = "whisper"

    def __init__(
        self,
        config: dict[str, Any],
        *,
        model_factory: Callable[..., Any] | None = None,
        gpu_probe: Callable[[], int | None] = gpu_free_mb,
        llm_probe: Callable[[], bool] | None = None,
    ):
        stt_config = config.get("stt", {})
        cfg = stt_config.get("whisper", {})
        self.language = str(stt_config.get("language", "id"))
        self.model_name = str(cfg.get("model", "small"))
        self.requested_device = str(cfg.get("device", "auto")).lower()
        self.requested_compute = str(cfg.get("compute_type", "auto")).lower()
        self.beam_size = int(cfg.get("beam_size", 1))  # greedy: ~2x faster than beam 5, same accuracy on short commands
        self.cpu_threads = int(cfg.get("cpu_threads", 0)) or min(8, os.cpu_count() or 4)
        self.download_root = str(cfg.get("download_root", "")) or None
        # Context, not a likely utterance: an initial prompt that equals a command would leak into silent clips.
        self.initial_prompt = str(cfg.get("initial_prompt", "")) or None
        self.llm_reserve_mb = int(cfg.get("llm_vram_reserve_mb", 3300))
        prefer_plain_http_downloads(bool(cfg.get("disable_xet", True)))
        llm_config = config.get("llm", {})
        self.local_llm = bool(llm_config.get("enabled", True)) and "ollama" in llm_config.get("providers", [])
        ollama = llm_config.get("ollama", {})
        self._llm_probe = llm_probe or (lambda: ollama_on_gpu(str(ollama.get("base_url", "http://127.0.0.1:11434")), str(ollama.get("model", "qwen3:4b"))))
        self._gpu_probe = gpu_probe
        self._model_factory = model_factory
        self._model: Any = None
        self._lock = threading.Lock()
        self.device = ""
        self.compute_type = ""
        self.device_reason = ""
        self.load_seconds = 0.0

    def warm_up(self) -> None:
        """Load the model now (download on first run) instead of on the first sentence."""
        self._load()

    def _load(self) -> Any:
        """Pick CPU/GPU, load the model, and fall back to CPU if CUDA libraries are missing."""
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            device, compute, reason = choose_whisper_device(
                self.requested_device,
                self.model_name,
                gpu_free=self._gpu_probe() if self.requested_device == "auto" else None,
                local_llm=self.local_llm,
                llm_loaded=self._llm_probe() if self.requested_device == "auto" and self.local_llm else False,
                llm_reserve_mb=self.llm_reserve_mb,
            )
            if self.requested_compute != "auto":
                compute = self.requested_compute
            factory = self._model_factory or _faster_whisper_model
            started = time.perf_counter()
            try:
                model = factory(self.model_name, device=device, compute_type=compute, cpu_threads=self.cpu_threads, download_root=self.download_root)
                if device == "cuda":
                    self._probe(model)
                self._model = model
            except Exception as exc:
                if device == "cpu":
                    raise
                # Typical on Windows: cuBLAS/cuDNN DLLs not installed. CPU int8 still works.
                safe_print(f"[stt] Whisper di GPU gagal ({exc}); pindah ke CPU.")
                device, compute, reason = "cpu", "int8", f"GPU gagal dipakai: {exc}"
                self._model = factory(self.model_name, device=device, compute_type=compute, cpu_threads=self.cpu_threads, download_root=self.download_root)
            self.load_seconds = time.perf_counter() - started
            self.device, self.compute_type, self.device_reason = device, compute, reason
            safe_print(f"[stt] Whisper {self.model_name} di {device} ({compute}): {reason}; dimuat {self.load_seconds:.1f}s")
            return self._model

    def _probe(self, model: Any) -> None:
        """Decode half a second of silence: CTranslate2 loads cuBLAS/cuDNN lazily, so a missing CUDA DLL
        only shows up on the first decode, not when the model is created."""
        import numpy as np

        segments, _info = model.transcribe(
            np.zeros(SAMPLE_RATE // 2, dtype=np.float32), language=self.language, beam_size=1, without_timestamps=True, vad_filter=False
        )
        list(segments)

    def _decode(self, model: Any, utterance: Utterance) -> list[Any]:
        """Greedy decoding of one utterance; returns Whisper's segments."""
        with self._lock:  # the barge-in watcher and the main loop may both transcribe
            segments, _info = model.transcribe(
                utterance.as_float32(),
                language=self.language,
                beam_size=self.beam_size,
                temperature=0.0,
                condition_on_previous_text=False,
                without_timestamps=True,
                vad_filter=False,  # our own VAD already cut the utterance
                initial_prompt=self.initial_prompt,
            )
            return list(segments)  # decoding happens while iterating

    def transcribe(self, utterance: Utterance) -> Transcript:
        """Decode one utterance in Indonesian and reject typical Whisper hallucinations; a GPU failure mid-run
        moves Whisper to the CPU and retries once."""
        model = self._load()
        started = time.perf_counter()
        try:
            segments = self._decode(model, utterance)
        except RuntimeError as exc:
            if self.device != "cuda" or not re.search(r"cuda|cublas|cudnn", str(exc), re.IGNORECASE):
                raise
            safe_print(f"[stt] Whisper di GPU gagal saat dipakai ({exc}); pindah ke CPU.")
            self._model, self.requested_device = None, "cpu"
            segments = self._decode(self._load(), utterance)
        elapsed = time.perf_counter() - started
        text = "".join(segment.text for segment in segments).strip()
        if not segments:
            return Transcript("", elapsed, self.name, dropped="kosong")
        no_speech = max(float(getattr(segment, "no_speech_prob", 0.0)) for segment in segments)
        logprob = sum(float(getattr(segment, "avg_logprob", 0.0)) for segment in segments) / len(segments)
        reason = hallucination_reason(text, no_speech, logprob, utterance.seconds)
        if reason:
            return Transcript("", elapsed, self.name, dropped=f"{reason}: {text!r}")
        return Transcript(clean_transcript(text), elapsed, self.name)


def _faster_whisper_model(name: str, **kwargs: Any) -> Any:
    """Imported lazily so Google-only users never need faster-whisper installed."""
    from faster_whisper import WhisperModel

    return WhisperModel(name, **kwargs)


def prefer_plain_http_downloads(enabled: bool = True) -> None:
    """Hugging Face's newer "Xet" transfer stalled at 0 bytes on the target network while plain HTTP worked,
    so the first model download uses plain HTTP unless the user sets HF_HUB_DISABLE_XET themselves."""
    if enabled:
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


def build_stt(config: dict[str, Any]) -> SpeechToText:
    """Engine chosen in config["stt"]["engine"]; Whisper falls back to Google if faster-whisper is missing."""
    engine = str(config.get("stt", {}).get("engine", "google")).lower()
    language = str(config.get("listen", {}).get("language", "id-ID"))
    if engine == "whisper":
        if importlib.util.find_spec("faster_whisper") is not None:  # checked without importing the heavy package
            return WhisperSTT(config)
        safe_print("[stt] faster-whisper belum terpasang; pakai Google.")
    return GoogleSTT(language)


def listen_once(
    config: dict[str, Any],
    speaker: Any,
    quiet: bool = False,
    timeout_override: int | None = None,
    phrase_time_limit_override: int | None = None,
) -> str | None:
    """Legacy one-shot listener (opens the mic, listens once, Google STT); kept for older scripts."""
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
