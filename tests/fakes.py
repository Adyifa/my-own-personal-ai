"""Test doubles: no microphone, no speakers, no model, no network."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

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

    def __init__(self, config: dict[str, Any]):
        self.opened_urls: list[str] = []
        self.started_files: list[Path] = []
        self.commands: list[str] = []
        super().__init__(
            config,
            open_url=self.opened_urls.append,
            start_file=self.started_files.append,
            run_command=self.commands.append,
        )

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


def make_result(index: int = 1, source: str = "Kompas", content: str = "Isi berita.") -> SearchResult:
    return SearchResult(
        title=f"Judul {index}",
        url=f"https://example{index}.com/artikel",
        snippet=f"Cuplikan {index}",
        source=source,
        content=content,
    )
