"""Provider-neutral chat types, so the agent never cares which LLM backend answers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal, Protocol


@dataclass
class ToolCall:
    """One function call requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    """One chat message; each provider converts it to its own wire format."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None  # tool name, for role == "tool"
    images: list[bytes] = field(default_factory=list)  # JPEG bytes for vision models (screenshots)


@dataclass
class StreamEvent:
    """One streamed piece of a reply: a text delta, a tool call, or the end marker."""

    kind: Literal["text", "tool_call", "done"]
    text: str = ""
    tool_call: ToolCall | None = None
    provider: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


class LLMError(Exception):
    """The model call failed."""


class ProviderUnavailable(LLMError):
    """The provider cannot be used right now (not running, no key, rate limited)."""


class LLMProvider(Protocol):
    """What every LLM backend implements: configured check, streaming chat, warm-up."""

    name: str

    def is_configured(self) -> bool: ...

    def stream_chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[StreamEvent]: ...

    def warmup(self) -> None: ...


def parse_arguments(raw: Any) -> dict[str, Any]:
    """Tool args arrive as a dict (Ollama) or JSON text (OpenAI); invalid JSON from small models becomes {}."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}
