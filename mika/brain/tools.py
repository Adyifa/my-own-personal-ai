"""Tool registry: LLM schemas, argument validation, and a confirmation gate enforced in code, not in the prompt."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ..text import safe_print
from .llm.base import ToolCall


@dataclass
class ToolResult:
    """What a tool hands back to the agent."""

    ok: bool
    data: dict[str, Any] = field(default_factory=dict)  # sent to the LLM as JSON
    speak: str | None = None  # ready-made spoken reply, used by the fast path
    sources: list[Any] = field(default_factory=list)  # web sources to show on screen
    needs_confirmation: bool = False  # the action waits for a spoken "iya"


@dataclass
class ToolSpec:
    """One tool the LLM may call, with its risk level and latency hints."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., ToolResult]
    risk: str = "safe"  # "safe" (read-only) | "action" (opens things) | "confirm" (needs voice yes)
    terminal: bool = False  # success fully answers the request, so a 2nd LLM call can be skipped
    filler: str | None = None  # spoken while a slow tool runs ("Bentar, Mika cariin dulu ya.")
    confirm_label: Callable[[dict[str, Any]], str] | None = None  # what Mika says it is about to do

    def schema(self) -> dict[str, Any]:
        """Function-calling schema understood by both Ollama and OpenAI."""
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


# (action_name, spoken label, deferred run) -> question to speak
ConfirmHandler = Callable[[str, str, Callable[[], Any]], str]


class ToolRegistry:
    """Runs the model's tool calls safely; risky tools only register a pending action."""

    def __init__(self, specs: Iterable[ToolSpec], confirm: ConfirmHandler | None = None):
        self._specs = {spec.name: spec for spec in specs}
        self.confirm = confirm

    def __len__(self) -> int:
        return len(self._specs)

    def names(self) -> list[str]:
        """Names of all registered tools."""
        return list(self._specs)

    def get(self, name: str) -> ToolSpec | None:
        """Look up a tool by name."""
        return self._specs.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        """All tool schemas, sent to the LLM with every request."""
        return [spec.schema() for spec in self._specs.values()]

    def execute(self, call: ToolCall) -> ToolResult:
        """Validate and run one call; never raises, errors go back to the model as data it can explain."""
        spec = self._specs.get(call.name)
        if spec is None:
            return ToolResult(False, {"error": f"Tool '{call.name}' tidak ada. Tool tersedia: {', '.join(self._specs)}"})

        arguments, error = _validate(spec, call.arguments or {})
        if error:
            return ToolResult(False, {"error": error})

        if spec.risk == "confirm":  # the model can request, but only the user's "iya" can execute
            if self.confirm is None:
                return ToolResult(False, {"error": "Aksi ini butuh konfirmasi, tapi konfirmasi suara tidak tersedia."})
            label = spec.confirm_label(arguments) if spec.confirm_label else spec.name
            question = self.confirm(spec.name, label, lambda: spec.handler(**arguments))
            return ToolResult(
                True,
                {"status": "menunggu konfirmasi suara dari pengguna", "aksi": label},
                speak=question,
                needs_confirmation=True,
            )

        try:
            return spec.handler(**arguments)
        except Exception as exc:
            safe_print(f"[tool] {call.name} error: {exc}")
            return ToolResult(False, {"error": f"{type(exc).__name__}: {exc}"})


def _validate(spec: ToolSpec, raw: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Drop invented args, coerce types, check enums and required fields (small models often get these wrong)."""
    properties: dict[str, Any] = spec.parameters.get("properties", {})
    arguments: dict[str, Any] = {}
    for key, value in raw.items():
        schema = properties.get(key)
        if schema is None or value is None:
            continue
        expected = schema.get("type")
        try:
            if expected == "integer":
                value = int(value)
            elif expected == "string":
                value = str(value).strip()
        except (TypeError, ValueError):
            return {}, f"Argumen '{key}' harus bertipe {expected}."
        if "enum" in schema and value not in schema["enum"]:
            return {}, f"Argumen '{key}' harus salah satu dari: {', '.join(map(str, schema['enum']))}."
        arguments[key] = value

    missing = [key for key in spec.parameters.get("required", []) if arguments.get(key) in (None, "")]
    if missing:
        return {}, f"Argumen wajib belum diisi: {', '.join(missing)}."
    return arguments, None
