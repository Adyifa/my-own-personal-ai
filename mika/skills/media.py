"""Media keys and system volume on Windows: works with Spotify, YouTube in the browser, and any media app."""

from __future__ import annotations

from typing import Any, Callable

from ..audio.tts import init_com_for_thread

VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT = 0xB0
VK_MEDIA_PREVIOUS = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3
_KEYEVENTF_KEYUP = 0x0002


def press_key(vk: int) -> None:
    """Simulate one press of a multimedia key, exactly like the keyboard's own media buttons."""
    import ctypes

    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)  # type: ignore[attr-defined]
    ctypes.windll.user32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)  # type: ignore[attr-defined]


class MediaControl:
    """Play/pause, next, previous for whatever app owns the media session."""

    def __init__(self, press: Callable[[int], Any] = press_key):
        self._press = press

    def play_pause(self) -> None:
        """Toggle (Windows has no separate play and pause keys)."""
        self._press(VK_MEDIA_PLAY_PAUSE)

    def next(self) -> None:
        """Next track."""
        self._press(VK_MEDIA_NEXT)

    def previous(self) -> None:
        """Previous track."""
        self._press(VK_MEDIA_PREVIOUS)


def _endpoint_volume() -> Any:
    """The speaker's IAudioEndpointVolume via pycaw (new and old pycaw APIs)."""
    init_com_for_thread()
    from pycaw.pycaw import AudioUtilities

    speakers = AudioUtilities.GetSpeakers()
    endpoint = getattr(speakers, "EndpointVolume", None)
    if endpoint is not None:
        return endpoint
    from ctypes import POINTER, cast

    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume

    interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


class VolumeControl:
    """Exact volume through Windows Core Audio (pycaw); without pycaw, falls back to volume key presses."""

    def __init__(self, endpoint_factory: Callable[[], Any] | None = _endpoint_volume, press: Callable[[int], Any] = press_key):
        self._endpoint_factory = endpoint_factory
        self._press = press

    def _endpoint(self) -> Any:
        """Endpoint or None when pycaw is unavailable."""
        if self._endpoint_factory is None:
            return None
        try:
            return self._endpoint_factory()
        except Exception:
            return None

    def get(self) -> int | None:
        """Current volume in percent, or None if it cannot be read."""
        endpoint = self._endpoint()
        if endpoint is None:
            return None
        return int(round(endpoint.GetMasterVolumeLevelScalar() * 100))

    def set(self, percent: int) -> int:
        """Set volume to 0-100 percent and return it."""
        percent = max(0, min(100, int(percent)))
        endpoint = self._endpoint()
        if endpoint is not None:
            endpoint.SetMasterVolumeLevelScalar(percent / 100, None)
            return percent
        for _ in range(50):  # each key press is 2%: go to 0, then up
            self._press(VK_VOLUME_DOWN)
        for _ in range(percent // 2):
            self._press(VK_VOLUME_UP)
        return percent

    def change(self, delta: int) -> int | None:
        """Raise or lower by `delta` percent; returns the new level when known."""
        current = self.get()
        if current is not None:
            return self.set(current + delta)
        key = VK_VOLUME_UP if delta > 0 else VK_VOLUME_DOWN
        for _ in range(max(1, abs(delta) // 2)):
            self._press(key)
        return None

    def mute(self, muted: bool) -> None:
        """Mute or unmute (the key fallback can only toggle)."""
        endpoint = self._endpoint()
        if endpoint is not None:
            endpoint.SetMute(1 if muted else 0, None)
        else:
            self._press(VK_VOLUME_MUTE)
