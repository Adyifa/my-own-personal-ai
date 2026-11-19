"""Test doubles: no microphone, no speakers, no model, no network."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

import httpx

from mika.brain.llm.base import Message, StreamEvent, ToolCall
from mika.skills.launcher import Launcher
from mika.skills.web_search import SearchReport, SearchResult


class FakeSpeaker:
    def __init__(self) -> None:
        self.said: list[str] = []
        self.first_audio_at = None
        self.stopped = False

    def say(self, message: str) -> None:
        self.said.append(message)

    def say_async(self, message: str) -> None:
        self.said.append(message)

    def wait(self, timeout: float | None = None) -> bool:
        return True

    def stop(self) -> None:
        self.stopped = True

    def mark_turn(self) -> None:
        self.first_audio_at = None

    @property
    def text(self) -> str:
        return " ".join(self.said)


class RecordingLauncher(Launcher):
    """Real lookup logic, recorded side effects."""

    def __init__(self, config: dict[str, Any], store_apps: dict[str, str] | None = None):
        self.opened_urls: list[str] = []
        self.started_files: list[Path] = []
        self.commands: list[str] = []
        self.store_scans = 0
        self._store_apps = dict(store_apps or {})
        super().__init__(
            config,
            open_url=self.opened_urls.append,
            start_file=self.started_files.append,
            run_command=self.commands.append,
            start_apps_scanner=self._fake_store_scan,
        )

    def _fake_store_scan(self) -> dict[str, str]:
        """Stands in for Get-StartApps; counts calls so tests can check the scan is cached and lazy."""
        self.store_scans += 1
        return dict(self._store_apps)

    @property
    def actions(self) -> list[Any]:
        return [*self.opened_urls, *self.started_files, *self.commands]


def text(*chunks: str) -> list[StreamEvent]:
    return [StreamEvent("text", text=chunk, provider="fake") for chunk in chunks] + [StreamEvent("done", provider="fake")]


def tool(tool_name: str, /, *, call_id: str = "call_1", **arguments: Any) -> list[StreamEvent]:
    return [
        StreamEvent("tool_call", tool_call=ToolCall(id=call_id, name=tool_name, arguments=arguments), provider="fake"),
        StreamEvent("done", provider="fake"),
    ]


class ScriptedLLM:
    """Replays one scripted list of events per stream_chat call. An Exception in the list is raised."""

    name = "fake"

    def __init__(self, *scripts: Iterable[Any]):
        self.scripts = [list(script) for script in scripts]
        self.calls: list[dict[str, Any]] = []
        self.warmed = False

    def is_configured(self) -> bool:
        return True

    def warmup(self) -> None:
        self.warmed = True

    def stream_chat(self, messages: list[Message], tools=None, **kwargs: Any):
        self.calls.append({"messages": list(messages), "tools": tools, **kwargs})
        if not self.scripts:
            raise AssertionError("ScriptedLLM called more often than scripted")
        for event in self.scripts.pop(0):
            if isinstance(event, Exception):
                raise event
            yield event


class FakeSearcher:
    def __init__(self, results: list[SearchResult] | None = None):
        self.results = results or []
        self.queries: list[str] = []

    def search(self, query: str) -> SearchReport:
        self.queries.append(query)
        return SearchReport(query=query, provider="fake", results=list(self.results))


class FakeClock:
    """Controllable clock: call it to get "now", advance() to move time."""

    def __init__(self, start: datetime):
        self.current = start

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **delta: float) -> None:
        self.current += timedelta(**delta)


class FakeEndpoint:
    """Stands in for Windows' IAudioEndpointVolume."""

    def __init__(self, level: float = 0.3):
        self.level = level
        self.muted = 0

    def GetMasterVolumeLevelScalar(self) -> float:
        return self.level

    def SetMasterVolumeLevelScalar(self, value: float, context: Any) -> None:
        self.level = value

    def SetMute(self, value: int, context: Any) -> None:
        self.muted = value


class FakePsutil:
    """Battery and usage numbers on demand."""

    def __init__(self, battery: Any = "default"):
        self._battery = SimpleNamespace(percent=47, secsleft=-2, power_plugged=True) if battery == "default" else battery

    def sensors_battery(self) -> Any:
        return self._battery

    def cpu_percent(self, interval: float = 0) -> float:
        return 14.9

    def virtual_memory(self) -> Any:
        return SimpleNamespace(percent=77.2)


FORECAST = {
    "current": {"temperature_2m": 24.3, "apparent_temperature": 25.0, "relative_humidity_2m": 80, "weather_code": 3, "wind_speed_10m": 6.1},
    "daily": {
        "time": ["2026-11-19", "2026-11-20", "2026-11-21"],
        "weather_code": [61, 95, 1],
        "temperature_2m_max": [27.4, 26.0, 29.0],
        "temperature_2m_min": [19.2, 19.0, 20.0],
        "precipitation_probability_max": [80, 90, 10],
    },
}
PLACES = {
    "bandung": {"name": "Kota Bandung", "latitude": -6.92, "longitude": 107.6, "admin1": "Jawa Barat"},
    "jakarta": {"name": "Jakarta", "latitude": -6.2, "longitude": 106.8, "admin1": "DKI Jakarta"},
}


def weather_transport(requests: list[httpx.Request] | None = None, offline: bool = False) -> httpx.MockTransport:
    """Fake Open-Meteo: geocoding for Bandung/Jakarta, one fixed forecast."""

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        if offline:
            raise httpx.ConnectError("no internet", request=request)
        if request.url.host.startswith("geocoding"):
            place = PLACES.get(request.url.params.get("name", "").lower())
            return httpx.Response(200, json={"results": [place]} if place else {})
        return httpx.Response(200, json=FORECAST)

    return httpx.MockTransport(handler)


class Everyday(SimpleNamespace):
    """The skill hub plus every fake behind it, for assertions."""


def make_everyday(config: dict[str, Any], tmp_path: Path, start: datetime, *, battery: Any = "default", endpoint: bool = True) -> Everyday:
    from mika.skills.hub import SkillHub
    from mika.skills.media import MediaControl, VolumeControl
    from mika.skills.notes import NotesStore
    from mika.skills.reminders import ReminderService
    from mika.skills.system_info import SystemInfo
    from mika.skills.weather import WeatherService

    clock = FakeClock(start)
    keys: list[int] = []
    fake_endpoint = FakeEndpoint()
    opened: list[Path] = []
    weather_requests: list[httpx.Request] = []
    hub = SkillHub(
        reminders=ReminderService(tmp_path / "data" / "reminders.json", clock=clock),
        weather=WeatherService(config, client=httpx.Client(transport=weather_transport(weather_requests))),
        media=MediaControl(press=keys.append),
        volume=VolumeControl(endpoint_factory=(lambda: fake_endpoint) if endpoint else None, press=keys.append),
        system=SystemInfo(psutil_module=FakePsutil(battery), disk_root=str(tmp_path)),
        notes=NotesStore(tmp_path / "data" / "notes.md"),
        open_path=opened.append,
    )
    return Everyday(hub=hub, clock=clock, keys=keys, endpoint=fake_endpoint, opened=opened, weather_requests=weather_requests)


def make_result(index: int = 1, source: str = "Kompas", content: str = "Isi berita.") -> SearchResult:
    return SearchResult(
        title=f"Judul {index}",
        url=f"https://example{index}.com/artikel",
        snippet=f"Cuplikan {index}",
        source=source,
        content=content,
    )


class FakeClipboard:
    """In-memory clipboard with the real sanitize/truncate logic."""

    def __init__(self, text: str = ""):
        from mika.skills.clipboard import Clipboard

        self.text = text
        self.written: list[str] = []
        self.inner = Clipboard(paste=lambda: self.text, copy=self.written.append, max_chars=200)

    def read(self):
        return self.inner.read()

    def write(self, text: str) -> bool:
        return self.inner.write(text)


class FakeScreen:
    def __init__(self):
        self.captures = 0

    def capture(self, active_window: bool = False) -> bytes:
        self.captures += 1
        return b"\xff\xd8fake-jpeg"


class FakeNews:
    def __init__(self, headlines=None):
        from mika.skills.news import Headline

        self.items = headlines if headlines is not None else [
            Headline("Pemerintah umumkan libur nasional 2027", "https://www.antaranews.com/a", "Antara"),
            Headline("Harga beras turun di pasar induk", "https://www.cnnindonesia.com/b", "CNN Indonesia"),
            Headline("Timnas menang 2-0", "https://www.republika.co.id/c", "Republika"),
        ]

    def headlines(self, limit: int = 5):
        return self.items[:limit]
