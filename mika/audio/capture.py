"""Microphone capture as a steady stream of 30 ms, 16 kHz mono frames (resampled when the device cannot do 16 kHz)."""

from __future__ import annotations

from typing import Any, Protocol

from .vad import FRAME_BYTES, FRAME_MS, SAMPLE_RATE


class FrameSource(Protocol):
    """A microphone (or a test double) delivering 30 ms, 16 kHz, mono int16 frames."""

    def open(self) -> None:
        """Start capturing; raise if the device is unavailable."""
        ...

    def read(self) -> bytes:
        """Block until the next frame is available."""
        ...

    def close(self) -> None:
        """Release the device."""
        ...


def list_input_devices() -> list[dict[str, Any]]:
    """Input devices as PyAudio sees them (index, name, channels, default rate)."""
    import pyaudio

    audio = pyaudio.PyAudio()
    try:
        devices = []
        for index in range(audio.get_device_count()):
            info = audio.get_device_info_by_index(index)
            if int(info.get("maxInputChannels", 0)) > 0:
                devices.append(
                    {
                        "index": index,
                        "name": str(info.get("name", "")),
                        "channels": int(info["maxInputChannels"]),
                        "rate": int(info.get("defaultSampleRate", 0)),
                    }
                )
        return devices
    finally:
        audio.terminate()


def resample_to_16k(pcm: bytes, source_rate: int) -> bytes:
    """Linear-interpolation resampling of int16 mono PCM; good enough for speech recognition."""
    if source_rate == SAMPLE_RATE:
        return pcm
    import numpy as np

    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return b""
    target = int(round(samples.size * SAMPLE_RATE / source_rate))
    positions = np.linspace(0, samples.size - 1, num=target)
    return np.interp(positions, np.arange(samples.size), samples).astype(np.int16).tobytes()


class PyAudioSource:
    """Keeps the microphone open (no re-open per sentence, unlike the old listener) and yields 30 ms frames."""

    def __init__(self, device_index: int | None = None):
        self.device_index = device_index
        self._audio: Any = None
        self._stream: Any = None
        self._rate = SAMPLE_RATE
        self._pending = b""

    def open(self) -> None:
        """Open at 16 kHz, or at the device's own rate when it refuses 16 kHz."""
        import pyaudio

        self._audio = pyaudio.PyAudio()
        rates = [SAMPLE_RATE]
        try:
            info = (
                self._audio.get_device_info_by_index(self.device_index)
                if self.device_index is not None
                else self._audio.get_default_input_device_info()
            )
            rates.append(int(info.get("defaultSampleRate", 48000)))
        except Exception:
            rates.append(48000)
        last_error: Exception | None = None
        for rate in rates:
            try:
                self._stream = self._audio.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=rate,
                    input=True,
                    input_device_index=self.device_index,
                    frames_per_buffer=rate * FRAME_MS // 1000,
                )
                self._rate = rate
                return
            except Exception as exc:
                last_error = exc
        self.close()
        raise OSError(f"Mikrofon tidak bisa dibuka: {last_error}")

    def read(self) -> bytes:
        """Next 30 ms frame at 16 kHz (blocks for about 30 ms)."""
        while len(self._pending) < FRAME_BYTES:
            chunk = self._stream.read(self._rate * FRAME_MS // 1000, exception_on_overflow=False)
            self._pending += resample_to_16k(chunk, self._rate)
        frame, self._pending = self._pending[:FRAME_BYTES], self._pending[FRAME_BYTES:]
        return frame

    def close(self) -> None:
        """Release the device (Windows' microphone-in-use indicator turns off)."""
        try:
            if self._stream is not None:
                self._stream.stop_stream()
                self._stream.close()
        finally:
            self._stream = None
            if self._audio is not None:
                self._audio.terminate()
                self._audio = None
            self._pending = b""
