"""Any OpenAI-compatible /chat/completions API (OpenAI, OpenRouter, Groq, LM Studio) via plain httpx + SSE."""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Iterator

import httpx

from .base import LLMError, Message, ProviderUnavailable, StreamEvent, ToolCall, parse_arguments

_FALLBACK_STATUS = {401, 403, 404, 408, 409, 429}  # bad key, missing model, rate limit: try the next provider


class OpenAICompatProvider:
    """Cloud (or local) OpenAI-style LLM, used as the fallback after Ollama."""

    name = "openai"

    def __init__(self, config: dict[str, Any], *, client: httpx.Client | None = None):
        self.config = config
        base_url_env = str(config.get("base_url_env", "OPENAI_BASE_URL"))
        self.base_url = (os.environ.get(base_url_env) or str(config.get("base_url", "https://api.openai.com/v1"))).rstrip("/")
        self.api_key_env = str(config.get("api_key_env", "OPENAI_API_KEY"))
        self.model = str(config.get("model", "gpt-5-mini"))
        self.reasoning_effort = config.get("reasoning_effort")  # "minimal" keeps GPT-5 time-to-first-token low
        self.send_temperature = bool(config.get("send_temperature", False))  # GPT-5 rejects custom temperature
        self.max_tokens_param = str(config.get("max_tokens_param", "max_completion_tokens"))  # GPT-5 rejects max_tokens
        self.timeout = httpx.Timeout(
            float(config.get("read_timeout_seconds", 60)),
            connect=float(config.get("connect_timeout_seconds", 3)),
        )
        self._client = client

    @property
    def client(self) -> httpx.Client:
        """Created on first use, so building the provider chain at startup costs nothing."""
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    @property
    def api_key(self) -> str:
        """The key lives in an environment variable / .env, never in commands.json."""
        return os.environ.get(self.api_key_env, "")

    def is_configured(self) -> bool:
        """Usable with a key, or without one when the endpoint is a local server."""
        is_local = self.base_url.startswith(("http://127.0.0.1", "http://localhost"))
        return bool(self.model) and (bool(self.api_key) or is_local)

    def warmup(self) -> None:
        """Hosted APIs need no warm-up."""
        return None

    def stream_chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[StreamEvent]:
        """Stream a chat completion and reassemble tool calls that arrive as JSON fragments."""
        if not self.is_configured():
            raise ProviderUnavailable(f"API key belum diisi (env {self.api_key_env})")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._to_wire(message) for message in messages],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = tools
        if max_tokens:
            payload[self.max_tokens_param] = max_tokens
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        if self.send_temperature and temperature is not None:
            payload["temperature"] = temperature

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        pending_calls: dict[int, dict[str, str]] = {}
        usage: dict[str, Any] = {}
        try:
            with self.client.stream(
                "POST", f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=self.timeout
            ) as response:
                if response.status_code >= 400:
                    body = response.read().decode("utf-8", errors="replace")[:300]
                    message = f"{self.name} error {response.status_code}: {body}"
                    if response.status_code in _FALLBACK_STATUS or response.status_code >= 500:
                        raise ProviderUnavailable(message)
                    raise LLMError(message)

                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        continue
                    if chunk.get("error"):
                        raise LLMError(f"{self.name}: {chunk['error']}")
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if delta.get("content"):
                            yield StreamEvent("text", text=delta["content"], provider=self.name)
                        for fragment in delta.get("tool_calls") or []:  # arguments arrive split over many chunks
                            slot = pending_calls.setdefault(int(fragment.get("index", 0)), {"id": "", "name": "", "args": ""})
                            if fragment.get("id"):
                                slot["id"] = fragment["id"]
                            function = fragment.get("function") or {}
                            if function.get("name"):
                                slot["name"] += function["name"]
                            if function.get("arguments"):
                                slot["args"] += function["arguments"]
        except httpx.TransportError as exc:
            if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
                raise ProviderUnavailable(f"{self.name} tidak bisa dihubungi: {exc}") from exc
            raise LLMError(f"Koneksi ke {self.name} terputus: {exc}") from exc

        for index in sorted(pending_calls):
            slot = pending_calls[index]
            if not slot["name"]:
                continue
            yield StreamEvent(
                "tool_call",
                tool_call=ToolCall(
                    id=slot["id"] or f"call_{index + 1}",
                    name=slot["name"],
                    arguments=parse_arguments(slot["args"]),
                ),
                provider=self.name,
            )
        yield StreamEvent("done", provider=self.name, usage=usage)

    @staticmethod
    def _to_wire(message: Message) -> dict[str, Any]:
        """Convert our Message to the OpenAI chat format (tool args as JSON text, results by call id)."""
        if message.role == "tool":
            return {"role": "tool", "tool_call_id": message.tool_call_id or "", "content": message.content}
        if message.images:
            parts: list[dict[str, Any]] = [{"type": "text", "text": message.content}]
            for image in message.images:
                data = base64.b64encode(image).decode("ascii")
                parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}})
            return {"role": message.role, "content": parts}
        wire: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.role == "assistant" and message.tool_calls:
            wire["content"] = message.content or None
            wire["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)},
                }
                for call in message.tool_calls
            ]
        return wire
