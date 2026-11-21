"""Local LLM through Ollama's native /api/chat (supports `think: false`, unlike its OpenAI-compatible route)."""

from __future__ import annotations

import base64
import json
from typing import Any, Iterator

import httpx

from ...text import safe_print
from .base import LLMError, Message, ProviderUnavailable, StreamEvent, ToolCall, is_local_url, parse_arguments


class OllamaProvider:
    """Free, private, offline LLM on the laptop GPU (default qwen3.5:4b, runs on a 4 GB GPU)."""

    name = "ollama"

    @property
    def local(self) -> bool:
        return is_local_url(self.base_url)

    def __init__(self, config: dict[str, Any], *, client: httpx.Client | None = None):
        self.base_url = str(config.get("base_url", "http://127.0.0.1:11434")).rstrip("/")
        self.model = str(config.get("model", "qwen3.5:4b"))
        self.think = config.get("think", False)  # False: skip Qwen3's hidden reasoning, which delays the first word
        self.keep_alive = config.get("keep_alive", "30m")  # keep the model in VRAM between turns (no reload)
        self.num_ctx = config.get("num_ctx", 4096)  # 4k context keeps the KV cache inside 4 GB VRAM
        self.timeout = httpx.Timeout(
            float(config.get("read_timeout_seconds", 60)),
            connect=float(config.get("connect_timeout_seconds", 1.5)),  # fail fast when Ollama is not running
        )
        self._client = client
        self._send_think = self.think is not None
        self._think_checked = False
        self.thinking_budget = int(config.get("thinking_budget_tokens", 1536))  # only used by thinking-only models

    @property
    def client(self) -> httpx.Client:
        """Created on first use, so building the provider chain at startup costs nothing."""
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def is_configured(self) -> bool:
        """A local server needs no key; reachability is checked on first use."""
        return bool(self.model)

    def warmup(self) -> None:
        """Load the model into VRAM now (empty message list = load only), so the first question is fast."""
        try:
            response = self.client.post(
                f"{self.base_url}/api/chat",
                json={"model": self.model, "messages": [], "keep_alive": self.keep_alive, "stream": False},
                timeout=self.timeout,
            )
        except httpx.TransportError as exc:
            raise ProviderUnavailable(f"Ollama tidak bisa dihubungi di {self.base_url}: {exc}") from exc
        if response.status_code >= 400:
            raise ProviderUnavailable(f"Ollama warm-up gagal ({response.status_code}): {response.text[:200]}")

    def stream_chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[StreamEvent]:
        """Stream text and tool calls; retries once without `think` for models that reject the flag."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._to_wire(message) for message in messages],
            "stream": True,
            "keep_alive": self.keep_alive,
            "options": {"num_ctx": self.num_ctx},
        }
        if temperature is not None:
            payload["options"]["temperature"] = temperature
        self._check_thinking_only()
        if max_tokens:
            # A thinking-only model spends its tokens on reasoning first; without extra room it never reaches the answer.
            payload["options"]["num_predict"] = max_tokens + (self.thinking_budget if self.think is True else 0)
        if tools:
            payload["tools"] = tools
        if self._send_think:
            payload["think"] = self.think

        try:
            yield from self._stream(payload)
        except _ThinkUnsupported:
            self._send_think = False
            payload.pop("think", None)
            yield from self._stream(payload)

    def _check_thinking_only(self) -> None:
        """Some models can only think (Ollama's qwen3:4b is now Qwen3-4B-Thinking-2507). For those, `think: false`
        is ignored and the reasoning arrives as the answer, so Mika would read it aloud. Asking for `think: true`
        moves it to a separate field that is never spoken: correct, but slow, so the log suggests an instruct model."""
        if self._think_checked or self.think is not False:
            return
        self._think_checked = True
        try:
            response = self.client.post(f"{self.base_url}/api/show", json={"model": self.model}, timeout=self.timeout)
            values = (response.json().get("thinking") or {}).get("values") if response.status_code < 400 else None
        except (httpx.HTTPError, ValueError):
            return  # cannot tell: keep think=false
        if isinstance(values, list) and values and False not in values:
            self.think = True
            safe_print(
                f"[llm] {self.model} selalu berpikir dulu sebelum menjawab, jadi jawabannya lambat. "
                "Untuk suara, pakai model yang bisa menjawab tanpa berpikir dulu: ollama pull qwen3.5:4b"
            )

    def _stream(self, payload: dict[str, Any]) -> Iterator[StreamEvent]:
        """Parse Ollama's newline-delimited JSON stream into StreamEvents."""
        call_index = 0
        try:
            with self.client.stream("POST", f"{self.base_url}/api/chat", json=payload, timeout=self.timeout) as response:
                if response.status_code >= 400:
                    body = response.read().decode("utf-8", errors="replace")[:300]
                    if response.status_code == 400 and "think" in body.lower() and "think" in payload:
                        raise _ThinkUnsupported(body)
                    raise ProviderUnavailable(f"Ollama error {response.status_code}: {body}")
                for line in response.iter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except ValueError:
                        continue
                    if data.get("error"):
                        raise LLMError(f"Ollama: {data['error']}")
                    message = data.get("message") or {}
                    if message.get("content"):
                        yield StreamEvent("text", text=message["content"], provider=self.name)
                    for raw_call in message.get("tool_calls") or []:
                        function = raw_call.get("function") or {}
                        if not function.get("name"):
                            continue
                        call_index += 1
                        yield StreamEvent(
                            "tool_call",
                            tool_call=ToolCall(
                                id=str(raw_call.get("id") or f"call_{call_index}"),
                                name=str(function["name"]),
                                arguments=parse_arguments(function.get("arguments")),
                            ),
                            provider=self.name,
                        )
                    if data.get("done"):
                        usage = {
                            key: data.get(key)
                            for key in ("prompt_eval_count", "eval_count", "load_duration", "total_duration")
                            if key in data
                        }
                        yield StreamEvent("done", provider=self.name, usage=usage)
                        return
        except httpx.TransportError as exc:
            if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
                raise ProviderUnavailable(f"Ollama tidak bisa dihubungi di {self.base_url}: {exc}") from exc
            raise LLMError(f"Koneksi ke Ollama terputus: {exc}") from exc

    @staticmethod
    def _to_wire(message: Message) -> dict[str, Any]:
        """Convert our Message to Ollama's chat format (tool args as objects, tool results named)."""
        wire: dict[str, Any] = {"role": message.role, "content": message.content or ""}
        if message.role == "assistant" and message.tool_calls:
            wire["tool_calls"] = [
                {"function": {"name": call.name, "arguments": call.arguments}} for call in message.tool_calls
            ]
        if message.role == "tool" and message.name:
            wire["tool_name"] = message.name
        if message.images:
            wire["images"] = [base64.b64encode(image).decode("ascii") for image in message.images]
        return wire


class _ThinkUnsupported(Exception):
    """The model has no thinking mode and rejected the `think` flag."""
