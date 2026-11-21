from __future__ import annotations

import json

import httpx
import pytest

from mika.brain.llm.base import LLMError, Message, ProviderUnavailable, StreamEvent, ToolCall
from mika.brain.llm.fallback import FallbackProvider
from mika.brain.llm.ollama import OllamaProvider
from mika.brain.llm.openai_compat import OpenAICompatProvider


def ndjson(*objects) -> bytes:
    return "".join(json.dumps(obj) + "\n" for obj in objects).encode()


def sse(*chunks) -> bytes:
    lines = [f"data: {json.dumps(chunk)}\n\n" for chunk in chunks] + ["data: [DONE]\n\n"]
    return "".join(lines).encode()


def collect(events):
    return list(events)


# Ollama --------------------------------------------------------------------------------


def test_ollama_streams_text_and_tool_calls():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=ndjson(
                {"message": {"role": "assistant", "content": "Oke, "}, "done": False},
                {"message": {"role": "assistant", "content": "bentar."}, "done": False},
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"function": {"name": "open_app", "arguments": {"name": "spotify"}}}],
                    },
                    "done": False,
                },
                {"message": {"role": "assistant", "content": ""}, "done": True, "eval_count": 12},
            ),
        )

    provider = OllamaProvider({"model": "qwen3:4b"}, client=httpx.Client(transport=httpx.MockTransport(handler)))
    messages = [
        Message("system", "sys"),
        Message("user", "buka spotify"),
        Message("assistant", "", tool_calls=[ToolCall("call_1", "open_app", {"name": "x"})]),
        Message("tool", '{"ok": true}', tool_call_id="call_1", name="open_app"),
    ]
    events = collect(provider.stream_chat(messages, tools=[{"type": "function"}], temperature=0.5, max_tokens=99))

    assert [e.text for e in events if e.kind == "text"] == ["Oke, ", "bentar."]
    calls = [e.tool_call for e in events if e.kind == "tool_call"]
    assert calls == [ToolCall("call_1", "open_app", {"name": "spotify"})]
    assert events[-1].kind == "done" and events[-1].usage["eval_count"] == 12

    body = captured["body"]
    assert captured["url"].endswith("/api/chat")
    assert body["think"] is False  # no hidden reasoning: keeps time-to-first-word low
    assert body["keep_alive"] == "30m"
    assert body["options"] == {"num_ctx": 4096, "temperature": 0.5, "num_predict": 99}
    assert body["tools"] == [{"type": "function"}]
    assert body["messages"][2]["tool_calls"] == [{"function": {"name": "open_app", "arguments": {"name": "x"}}}]
    assert body["messages"][3] == {"role": "tool", "content": '{"ok": true}', "tool_name": "open_app"}


def test_ollama_retries_without_think_for_models_that_reject_it():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion"]})  # no thinking information
        body = json.loads(request.content)
        bodies.append(body)
        if "think" in body:
            return httpx.Response(400, json={"error": "model does not support thinking"})
        return httpx.Response(200, content=ndjson({"message": {"content": "Halo."}, "done": True}))

    provider = OllamaProvider({"model": "llama3.2"}, client=httpx.Client(transport=httpx.MockTransport(handler)))
    events = collect(provider.stream_chat([Message("user", "hai")]))
    assert [e.text for e in events if e.kind == "text"] == ["Halo."]
    assert "think" in bodies[0] and "think" not in bodies[1]


def _thinking_server(values, chats, shows):
    """A fake Ollama whose model reports which `think` values it accepts, and streams reasoning separately."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/show":
            shows.append(1)
            return httpx.Response(200, json={"capabilities": ["completion", "thinking"], "thinking": {"values": values}})
        body = json.loads(request.content)
        chats.append(body)
        lines = [{"message": {"thinking": "Okay, the user asks about the capital."}}] if body.get("think") else []
        lines.append({"message": {"content": "Canberra."}, "done": True})
        return httpx.Response(200, content=ndjson(*lines))

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_thinking_only_model_thinks_separately_and_the_reasoning_is_never_spoken():
    chats, shows = [], []
    provider = OllamaProvider({"model": "qwen3:4b"}, client=_thinking_server([True], chats, shows))
    first = collect(provider.stream_chat([Message("user", "ibu kota australia?")]))
    collect(provider.stream_chat([Message("user", "lagi")]))
    assert [e.text for e in first if e.kind == "text"] == ["Canberra."]
    assert chats[0]["think"] is True and chats[1]["think"] is True
    assert len(shows) == 1  # checked once per provider, not on every turn


def test_thinking_only_model_gets_room_to_reach_the_answer():
    chats = []
    provider = OllamaProvider({"model": "qwen3:4b"}, client=_thinking_server([True], chats, []))
    collect(provider.stream_chat([Message("user", "hai")], max_tokens=400))
    assert chats[0]["options"]["num_predict"] == 400 + 1536


def test_model_that_can_skip_thinking_keeps_think_false():
    chats, shows = [], []
    provider = OllamaProvider({"model": "qwen3:4b-instruct"}, client=_thinking_server([True, False], chats, shows))
    collect(provider.stream_chat([Message("user", "hai")]))
    assert chats[0]["think"] is False


def test_ollama_not_running_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = OllamaProvider({}, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderUnavailable):
        collect(provider.stream_chat([Message("user", "hai")]))


def test_ollama_missing_model_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'qwen3:4b' not found"})

    provider = OllamaProvider({}, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderUnavailable, match="not found"):
        collect(provider.stream_chat([Message("user", "hai")]))


# OpenAI-compatible ---------------------------------------------------------------------


def test_openai_assembles_fragmented_tool_calls(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=sse(
                {"choices": [{"delta": {"content": "Bentar "}}]},
                {"choices": [{"delta": {"content": "ya."}}]},
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_a", "function": {"name": "web_search", "arguments": '{"que'}}]}}]},
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'ry": "harga beras"}'}}]}}]},
                {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], "usage": {"total_tokens": 42}},
            ),
        )

    provider = OpenAICompatProvider(
        {"model": "gpt-5-mini", "reasoning_effort": "minimal"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    events = collect(provider.stream_chat([Message("user", "harga beras")], tools=[{"type": "function"}], temperature=0.7, max_tokens=300))

    assert "".join(e.text for e in events if e.kind == "text") == "Bentar ya."
    assert [e.tool_call for e in events if e.kind == "tool_call"] == [ToolCall("call_a", "web_search", {"query": "harga beras"})]
    assert events[-1].usage == {"total_tokens": 42}
    assert captured["auth"] == "Bearer sk-test"
    body = captured["body"]
    assert body["max_completion_tokens"] == 300
    assert body["reasoning_effort"] == "minimal"
    assert "temperature" not in body  # GPT-5 models reject custom temperatures
    assert body["stream"] is True


def test_openai_wire_format_for_tool_round_trip():
    wire = OpenAICompatProvider._to_wire(Message("assistant", "", tool_calls=[ToolCall("c1", "open_app", {"name": "x"})]))
    assert wire == {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "open_app", "arguments": '{"name": "x"}'}}],
    }
    assert OpenAICompatProvider._to_wire(Message("tool", "hasil", tool_call_id="c1", name="open_app")) == {
        "role": "tool",
        "tool_call_id": "c1",
        "content": "hasil",
    }


def test_openai_without_key_is_not_configured(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    provider = OpenAICompatProvider({})
    assert not provider.is_configured()
    with pytest.raises(ProviderUnavailable):
        collect(provider.stream_chat([Message("user", "hai")]))


def test_openai_rate_limit_is_unavailable(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    transport = httpx.MockTransport(lambda request: httpx.Response(429, json={"error": "slow down"}))
    provider = OpenAICompatProvider({}, client=httpx.Client(transport=transport))
    with pytest.raises(ProviderUnavailable):
        collect(provider.stream_chat([Message("user", "hai")]))


def test_api_key_comes_from_env_not_config(monkeypatch):
    monkeypatch.setenv("MY_KEY", "from-env")
    provider = OpenAICompatProvider({"api_key_env": "MY_KEY", "api_key": "ignored"})
    assert provider.api_key == "from-env"


# Fallback chain ------------------------------------------------------------------------


class StubProvider:
    def __init__(self, name, events=None, error=None, error_after=None):
        self.name = name
        self.events = events or [StreamEvent("text", text=f"dari {name}"), StreamEvent("done")]
        self.error = error
        self.error_after = error_after
        self.calls = 0

    def is_configured(self):
        return True

    def warmup(self):
        if self.error:
            raise self.error

    def stream_chat(self, messages, tools=None, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        for index, event in enumerate(self.events):
            if self.error_after is not None and index == self.error_after:
                raise LLMError("putus di tengah")
            yield event


def test_fallback_uses_next_provider_and_tags_events():
    local = StubProvider("ollama", error=ProviderUnavailable("down"))
    cloud = StubProvider("openai")
    chain = FallbackProvider([local, cloud])
    events = collect(chain.stream_chat([Message("user", "hai")]))
    assert events[0].text == "dari openai" and events[0].provider == "openai"
    assert chain.last_provider == "openai"


def test_failed_provider_cools_down():
    now = [100.0]
    local = StubProvider("ollama", error=ProviderUnavailable("down"))
    cloud = StubProvider("openai")
    chain = FallbackProvider([local, cloud], cooldown_seconds=60, clock=lambda: now[0])
    collect(chain.stream_chat([Message("user", "a")]))
    collect(chain.stream_chat([Message("user", "b")]))
    assert local.calls == 1  # skipped during cooldown: no repeated connect timeouts
    now[0] += 61
    collect(chain.stream_chat([Message("user", "c")]))
    assert local.calls == 2


def test_no_fallback_after_the_answer_started():
    local = StubProvider("ollama", error_after=1)
    cloud = StubProvider("openai")
    chain = FallbackProvider([local, cloud])
    with pytest.raises(LLMError):
        collect(chain.stream_chat([Message("user", "hai")]))
    assert cloud.calls == 0


def test_all_providers_down():
    chain = FallbackProvider([StubProvider("ollama", error=ProviderUnavailable("down"))])
    with pytest.raises(ProviderUnavailable, match="ollama"):
        collect(chain.stream_chat([Message("user", "hai")]))


def test_unexpected_provider_bug_still_falls_back():
    broken = StubProvider("ollama", error=ValueError("bug"))
    chain = FallbackProvider([broken, StubProvider("openai")])
    assert collect(chain.stream_chat([Message("user", "hai")]))[0].provider == "openai"


def test_warmup_puts_dead_provider_on_cooldown():
    local = StubProvider("ollama", error=ProviderUnavailable("down"))
    cloud = StubProvider("openai")
    chain = FallbackProvider([local, cloud])
    chain.warmup()
    collect(chain.stream_chat([Message("user", "hai")]))
    assert local.calls == 0 and cloud.calls == 1
