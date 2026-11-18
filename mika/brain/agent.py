"""LLM agent loop: stream the answer, speak it sentence by sentence, and run tools in between."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..text import safe_print
from .llm.base import LLMError, LLMProvider, Message, ToolCall
from .prompts import build_system_prompt
from .sentences import DETAIL_RE, HiddenTagFilter, SpeechSegmenter, clean_for_speech
from .session import ConversationSession
from .tools import ToolRegistry, ToolResult

# Words that signal a multi-step request ("buka spotify terus cari berita"): keep the LLM in the loop.
COMPOUND_RE = re.compile(r"\b(terus|trus|lalu|kemudian|habis itu|abis itu|setelah itu|sekalian|dan)\b")
MAX_TOOL_RESULT_CHARS = 6000  # cap what one tool result adds to a 4k-token context
MID_TURN_APOLOGY = "Maaf, otak Mika lagi error di tengah jalan. Coba ulangi sebentar lagi, ya."
EMPTY_ANSWER = "Hmm, Mika belum nemu jawabannya. Coba tanya dengan kalimat lain, ya."


@dataclass
class AgentReply:
    """Everything one turn produced: spoken lines, screen text, sources, tools used, and timings."""

    spoken: list[str]
    full_text: str = ""
    detail: str = ""
    tools_used: list[str] = field(default_factory=list)
    sources: list[Any] = field(default_factory=list)
    provider: str = ""
    pending_confirmation: bool = False
    first_token_seconds: float | None = None
    llm_calls: int = 0

    @property
    def needs_display(self) -> bool:
        """Long details and sources are shown on screen instead of being read aloud."""
        return bool(self.detail or self.sources)


class _SpokenStream:
    """Glue between raw LLM deltas and the speaker for one turn."""

    def __init__(self, speak: Callable[[str], None], max_sentences: int):
        self._speak = speak
        self._tags = HiddenTagFilter()
        self.segmenter = SpeechSegmenter(max_sentences)
        self.spoken: list[str] = []
        self.visible: list[str] = []
        self.step_spoke = False

    @property
    def spoke_anything(self) -> bool:
        """True once the user has heard something this turn."""
        return bool(self.spoken)

    def new_step(self) -> None:
        """Start a new LLM response within the same turn."""
        self.step_spoke = False
        self.segmenter.new_step()

    def feed(self, delta: str) -> str:
        """Filter one text delta and speak every sentence it completes."""
        visible = self._tags.feed(delta)
        if visible:
            self.visible.append(visible)
            for sentence in self.segmenter.feed(visible):
                self.say(sentence)
        return visible

    def end_step(self) -> None:
        """Speak what is left of this response before tools run or the turn ends."""
        tail = self._tags.flush()
        if tail:
            self.visible.append(tail)
            for sentence in self.segmenter.feed(tail):
                self.say(sentence)
        for sentence in self.segmenter.flush():
            self.say(sentence)

    def say(self, text: str) -> None:
        """Clean one sentence for TTS and queue it (non-blocking)."""
        cleaned = clean_for_speech(text)
        if not cleaned:
            return
        self.spoken.append(cleaned)
        self.step_spoke = True
        self._speak(cleaned)


class Agent:
    """Answers one user turn with an LLM that can call tools, speaking while it thinks."""

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry,
        session: ConversationSession,
        config: dict[str, Any],
        *,
        speak: Callable[[str], None],
        clock: Callable[[], float] = time.perf_counter,
    ):
        self.llm = llm
        self.tools = tools
        self.session = session
        self.config = config
        self._speak = speak
        self._clock = clock
        agent_config = config.get("agent", {})
        llm_config = config.get("llm", {})
        self.max_steps = max(1, int(agent_config.get("max_tool_steps", 4)))  # bound on LLM calls per turn
        self.max_sentences = int(agent_config.get("max_spoken_sentences", 3))  # voice stays short
        self.fast_actions = bool(agent_config.get("fast_action_replies", True))  # skip 2nd LLM call after simple actions
        self.temperature = llm_config.get("temperature", 0.6)
        self.max_tokens = llm_config.get("max_output_tokens", 400)

    def warm_up(self) -> None:
        """Load the model before the first question."""
        warmup = getattr(self.llm, "warmup", None)
        if callable(warmup):
            warmup()

    def respond(self, user_text: str) -> AgentReply:
        """Answer one turn; raises LLMError only if nothing was said or done, so the caller can fall back offline."""
        started = self._clock()
        out = _SpokenStream(self._speak, self.max_sentences)
        reply = AgentReply(spoken=out.spoken)
        schemas = self.tools.schemas()
        messages = [
            Message("system", build_system_prompt(self.config, context=self._context_note())),
            *self.session.history(),
            Message("user", user_text),
        ]

        for step in range(self.max_steps):
            out.new_step()
            offer_tools = bool(schemas) and step < self.max_steps - 1  # last step: no tools, so it must answer
            text_parts: list[str] = []
            calls: list[ToolCall] = []
            reply.llm_calls += 1
            try:
                for event in self.llm.stream_chat(
                    messages,
                    schemas if offer_tools else None,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                ):
                    reply.provider = event.provider or reply.provider
                    if event.kind == "text":
                        if reply.first_token_seconds is None:
                            reply.first_token_seconds = self._clock() - started
                        text_parts.append(out.feed(event.text))
                    elif event.kind == "tool_call" and event.tool_call is not None:
                        calls.append(event.tool_call)
            except LLMError as exc:
                if step == 0 and not out.spoke_anything and not "".join(out.visible).strip():
                    raise
                safe_print(f"[agent] LLM error di tengah giliran: {exc}")
                out.end_step()
                out.say(MID_TURN_APOLOGY)
                break

            out.end_step()
            if not calls:
                break
            messages.append(Message("assistant", "".join(text_parts), tool_calls=calls))
            if self._run_tools(calls, messages, out, reply, user_text):
                break

        if not out.spoken:
            out.say(EMPTY_ANSWER)

        reply.full_text = DETAIL_RE.sub("\n", "".join(out.visible)).strip()
        reply.detail = out.segmenter.detail
        self.session.add_turn(user_text, _history_text(reply))
        return reply

    def _run_tools(
        self,
        calls: list[ToolCall],
        messages: list[Message],
        out: _SpokenStream,
        reply: AgentReply,
        user_text: str,
    ) -> bool:
        """Run the model's tool calls and append results; return True when the turn is finished."""
        quick_replies: list[str] = []
        all_quick = True
        for call in calls:
            spec = self.tools.get(call.name)
            if spec is not None and spec.filler and not out.spoke_anything:
                out.say(spec.filler)  # no dead air while a slow tool (web/file search) runs
            safe_print(f"[agent] tool {call.name} {json.dumps(call.arguments, ensure_ascii=False)}")
            result = self.tools.execute(call)
            reply.tools_used.append(call.name)
            if result.sources:
                reply.sources = list(result.sources)
            messages.append(Message("tool", render_tool_result(result), tool_call_id=call.id, name=call.name))

            if result.needs_confirmation:  # stop: the model must not continue (or claim success) past the gate
                reply.pending_confirmation = True
                if result.speak:
                    out.say(result.speak)
                return True
            if spec is not None and spec.terminal and result.ok and result.speak:
                quick_replies.append(result.speak)
            else:
                all_quick = False

        if self.fast_actions and all_quick and quick_replies and not COMPOUND_RE.search(user_text.lower()):
            if not out.step_spoke:  # simple action done: template reply instead of a 2nd LLM round trip
                for text in quick_replies:
                    out.say(text)
            return True
        return False

    def _context_note(self) -> str:
        """Last search titles go in the system prompt (not chat history, which small models copy into speech)."""
        results = self.session.last_results[:5]
        if not results:
            return ""
        listing = "; ".join(
            f"{index}. {getattr(result, 'source', '')}: {getattr(result, 'title', '')}"
            for index, result in enumerate(results, start=1)
        )
        return f"Hasil web_search terakhir (nomor untuk open_search_result): {listing}"


def render_tool_result(result: ToolResult) -> str:
    """Tool result as compact JSON for the model, size-capped."""
    text = json.dumps({"ok": result.ok, **result.data}, ensure_ascii=False)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + "..."
    return text


def _history_text(reply: AgentReply) -> str:
    """What the next turn remembers: the answer only, never raw tool output or page text."""
    text = " ".join(reply.spoken) or reply.full_text
    if reply.detail:
        text += "\n[DETAIL]\n" + reply.detail[:400]
    return text[:1500]
