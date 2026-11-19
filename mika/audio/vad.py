"""Voice activity detection and endpointing: decides when an utterance starts and ends in a 16 kHz mic stream."""

from __future__ import annotations

import math
from array import array
from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2  # int16
FRAME_MS = 30  # webrtcvad accepts 10/20/30 ms frames
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * SAMPLE_WIDTH


@dataclass
class Utterance:
    """One stretch of speech: 16 kHz mono int16 PCM plus timing used for latency tracking and barge-in."""

    pcm: bytes
    started_at: float  # clock time when speech was detected
    speech_end_at: float  # clock time of the last voiced frame (what "end of speech" means for latency)
    during_playback: bool = False  # Mika was talking when this started (echo or barge-in)

    @property
    def seconds(self) -> float:
        """Audio length in seconds."""
        return len(self.pcm) / (SAMPLE_RATE * SAMPLE_WIDTH)

    def as_float32(self) -> Any:
        """Float32 array in [-1, 1], the input format Whisper expects."""
        import numpy as np

        return np.frombuffer(self.pcm, dtype=np.int16).astype(np.float32) / 32768.0


def frame_rms(frame: bytes) -> float:
    """Root-mean-square loudness of one int16 frame."""
    samples = array("h", frame)
    if not samples:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


class VoiceDetector(Protocol):
    """Anything that can say whether one 30 ms frame contains speech."""

    def is_speech(self, frame: bytes) -> bool:
        """True when the frame contains speech."""
        ...


class EnergyVAD:
    """Dependency-free fallback: speech is a frame clearly louder than the slowly adapting background noise."""

    def __init__(self, ratio: float = 3.0, min_rms: float = 300.0, initial_noise: float = 150.0, rise: float = 0.01, fall: float = 0.1):
        self.ratio = ratio
        self.min_rms = min_rms
        self.noise = initial_noise
        self.rise = rise
        self.fall = fall
        self.last_rms = 0.0

    def is_speech(self, frame: bytes) -> bool:
        """Compare against the noise floor. The floor falls fast and rises slowly, so a steady fan or AC is
        learned within seconds while short bursts of speech barely move it."""
        rms = frame_rms(frame)
        self.last_rms = rms
        speech = rms > max(self.min_rms, self.noise * self.ratio)
        rate = self.fall if rms < self.noise else self.rise
        self.noise += rate * (rms - self.noise)
        return speech


class WebRtcVAD:
    """Google's WebRTC VAD (a small GMM, ~0.1 ms per frame): far fewer false triggers than plain loudness."""

    def __init__(self, aggressiveness: int = 2):
        import webrtcvad

        self._vad = webrtcvad.Vad(max(0, min(3, int(aggressiveness))))
        self.last_rms = 0.0

    def is_speech(self, frame: bytes) -> bool:
        """WebRTC decision for one 30 ms frame."""
        self.last_rms = frame_rms(frame)
        return bool(self._vad.is_speech(frame, SAMPLE_RATE))


def build_vad(config: dict[str, Any]) -> VoiceDetector:
    """WebRTC VAD when installed ("auto"), else the energy detector."""
    vad_config = config.get("stt", {}).get("vad", {})
    engine = str(vad_config.get("engine", "auto")).lower()
    if engine in ("auto", "webrtc"):
        try:
            return WebRtcVAD(int(vad_config.get("aggressiveness", 2)))
        except ImportError:
            if engine == "webrtc":
                raise
    return EnergyVAD()


def silence_ms_from_config(config: dict[str, Any]) -> int:
    """End-of-speech pause; defaults to the user's existing listen.pause_threshold tuning."""
    configured = int(config.get("stt", {}).get("vad", {}).get("silence_ms", 0) or 0)
    if configured > 0:
        return configured
    return max(300, int(float(config.get("listen", {}).get("pause_threshold", 0.6)) * 1000))


class Endpointer:
    """State machine over VAD decisions: start after a few voiced frames, end after a pause, keep a short pre-roll."""

    def __init__(
        self,
        *,
        silence_ms: int = 600,
        preroll_ms: int = 300,
        start_ms: int = 90,
        min_speech_ms: int = 250,
        max_seconds: float = 12.0,
    ):
        self.silence_frames = max(1, silence_ms // FRAME_MS)
        self.start_frames = max(1, start_ms // FRAME_MS)
        self.min_speech_frames = max(1, min_speech_ms // FRAME_MS)
        self.max_frames = int(max_seconds * 1000 // FRAME_MS)
        self._preroll: deque[bytes] = deque(maxlen=max(self.start_frames, preroll_ms // FRAME_MS))
        self._run: list[tuple[bytes, float]] = []  # consecutive voiced frames before the start is confirmed
        self._frames: list[bytes] = []
        self._in_speech = False
        self._silence = 0
        self._voiced = 0
        self._started_at = 0.0
        self._last_voice_at = 0.0
        self._during_playback = False

    @property
    def in_speech(self) -> bool:
        """True between a confirmed start and the end of the utterance."""
        return self._in_speech

    @property
    def during_playback(self) -> bool:
        """Whether the current utterance started while Mika was talking."""
        return self._during_playback

    def process(self, frame: bytes, voiced: bool, now: float, playing: bool = False) -> tuple[str | None, Utterance | None]:
        """Feed one frame; returns ("start", None) when speech begins and (None, Utterance) when it ends."""
        if not self._in_speech:
            if voiced:
                self._run.append((frame, now))
                if len(self._run) >= self.start_frames:
                    # Pre-roll keeps the quiet onset of the first word ("h" in "halo") that VAD misses.
                    self._frames = list(self._preroll) + [f for f, _ in self._run]
                    self._started_at = self._run[0][1]
                    self._last_voice_at = now
                    self._voiced = len(self._run)
                    self._silence = 0
                    self._in_speech = True
                    self._during_playback = playing
                    self._run = []
                    self._preroll.clear()
                    return "start", None
                return None, None
            self._preroll.extend(f for f, _ in self._run)
            self._run = []
            self._preroll.append(frame)
            return None, None

        self._frames.append(frame)
        if voiced:
            self._voiced += 1
            self._silence = 0
            self._last_voice_at = now
        else:
            self._silence += 1
        if self._silence >= self.silence_frames or len(self._frames) >= self.max_frames:
            return None, self._finish()
        return None, None

    def _finish(self) -> Utterance | None:
        """Close the utterance; too little voiced audio (a cough, a click) is dropped."""
        utterance = None
        if self._voiced >= self.min_speech_frames:
            utterance = Utterance(b"".join(self._frames), self._started_at, self._last_voice_at, self._during_playback)
        self._frames = []
        self._in_speech = False
        self._silence = 0
        self._voiced = 0
        return utterance
