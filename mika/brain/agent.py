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
    first_token_at: float | None = None  # absolute clock time, for end-of-speech latency
    llm_calls: int = 0
    interrupted: bool = False  # the user talked over Mika (barge-in)
    tainted: bool = False  # this turn read untrusted text (web, screen, clipboard)
    tool_detail: str = ""  # screen text produced by tools (weather table, briefing, memory list)

    @property
    def needs_display(self) -> bool:
        """Long details and sources are shown on screen instead of being read aloud."""
        return bool(self.detail or self.sources or self.tool_detail)


class _SpokenStream:
    """Glue between raw LLM deltas and the speaker for one turn."""

    def __init__(self, speak: Callable[[str], None], max_sentences: int, should_stop: Callable[[], bool] = lambda: False):
        self._speak = speak
        self._should_stop = should_stop
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
        """Clean one sentence for TTS and queue it (non-blocking); silent once the user interrupted."""
        cleaned = clean_for_speech(text)
        if not cleaned or self._should_stop():
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
        memory: Any = None,
    ):
        self.llm = llm
        self.tools = tools
        self.session = session
        self.config = config
        self.memory = memory  # long-term facts about the user, injected into the system prompt
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

    def respond(
        self,
        user_text: str,
        should_stop: Callable[[], bool] | None = None,
        *,
        mode: str = "default",
        llm: LLMProvider | None = None,
        note: str = "",
    ) -> AgentReply:
        """Answer one turn; raises LLMError only if nothing was said or done, so the caller can fall back offline.
        `should_stop` is checked per token: on barge-in the stream is closed so the model stops generating."""
        stop = should_stop or (lambda: False)
        started = self._clock()
        out = _SpokenStream(self._speak, self.max_sentences, stop)
        reply = AgentReply(spoken=out.spoken)
        curhat = mode == "curhat"
        model = llm or self.llm
        # Curhat gets no tools: a small model should listen, not search the web or open apps mid-story.
        schemas = [] if curhat else self.tools.schemas(user_text)  # tool retrieval: rare tools only when relevant
        # Curhat turns stay out of requests that may reach a cloud model.
        include_private = curhat or bool(getattr(model, "local", False))
        messages = [
            Message("system", build_system_prompt(self.config, context=_join_notes(note, self._context_note(user_text)), mode=mode)),
            *self.session.history(include_private=include_private),
            Message("user", user_text),
        ]

        for step in range(self.max_steps):
            if stop():
                reply.interrupted = True
                break
            out.new_step()
            offer_tools = bool(schemas) and step < self.max_steps - 1  # last step: no tools, so it must answer
            text_parts: list[str] = []
            calls: list[ToolCall] = []
            reply.llm_calls += 1
            stream = model.stream_chat(
                messages,
                schemas if offer_tools else None,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            try:
                for event in stream:
                    if stop():
                        reply.interrupted = True
                        break
                    reply.provider = event.provider or reply.provider
                    if event.kind == "text":
                        if reply.first_token_seconds is None:
                            reply.first_token_at = self._clock()
                            reply.first_token_seconds = reply.first_token_at - started
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
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()  # closes the HTTP stream, so Ollama stops generating tokens nobody will hear

            if reply.interrupted:
                break
            out.end_step()
            if not calls:
                break
            messages.append(Message("assistant", "".join(text_parts), tool_calls=calls))
            if self._run_tools(calls, messages, out, reply, user_text):
                break

        if not out.spoken and not reply.interrupted:
            out.say(EMPTY_ANSWER)

        reply.full_text = DETAIL_RE.sub("\n", "".join(out.visible)).strip()
        reply.detail = out.segmenter.detail
        self.session.add_turn(user_text, _history_text(reply), private=curhat)
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
        model_spoke = out.step_spoke  # before fillers: a filler must not suppress the action's confirmation
        quick_replies: list[str] = []
        all_quick = True
        for call in calls:
            spec = self.tools.get(call.name)
            if spec is not None and spec.filler and not out.spoke_anything:
                out.say(spec.filler)  # no dead air while a slow tool (web/file search) runs
            safe_print(f"[agent] tool {call.name} {json.dumps(call.arguments, ensure_ascii=False)}")
            result = self.tools.execute(call, tainted=reply.tainted)
            reply.tools_used.append(call.name)
            if spec is not None and spec.untrusted_output:
                reply.tainted = True  # from now on this turn may not persist anything (prompt-injection guard)
            if result.sources:
                reply.sources = list(result.sources)
            if result.detail:
                reply.tool_detail = "\n\n".join(filter(None, [reply.tool_detail, result.detail]))
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
            if not model_spoke:  # simple action done: template reply instead of a 2nd LLM round trip
                for text in quick_replies:
                    out.say(text)
            return True
        return False

    def _context_note(self, user_text: str = "") -> str:
        """Long-term memories relevant to this turn plus the last search titles, in the system prompt
        (not the chat history, where a small model tends to copy such notes into its spoken answer)."""
        notes = []
        if self.memory is not None:
            facts = self.memory.relevant(user_text, limit=8)
            if facts:
                notes.append("Yang kamu ingat tentang pengguna (pakai hanya kalau relevan): " + "; ".join(f.text for f in facts))
        results = self.session.last_results[:5]
        if results:
            listing = "; ".join(
                f"{index}. {getattr(result, 'source', '')}: {getattr(result, 'title', '')}"
                for index, result in enumerate(results, start=1)
            )
            notes.append(f"Hasil web_search terakhir (nomor untuk open_search_result): {listing}")
        return "\n".join(notes)

    def run_task(
        self,
        system: str,
        user_text: str,
        *,
        images: list[bytes] | None = None,
        llm: LLMProvider | None = None,
        should_stop: Callable[[], bool] | None = None,
        max_sentences: int | None = None,
    ) -> AgentReply:
        """One-shot job without tools or chat history (summarize the clipboard, describe the screen), still
        spoken sentence by sentence. Raises LLMError when no model is reachable, like respond()."""
        stop = should_stop or (lambda: False)
        out = _SpokenStream(self._speak, max_sentences or self.max_sentences, stop)
        reply = AgentReply(spoken=out.spoken, llm_calls=1)
        started = self._clock()
        stream = (llm or self.llm).stream_chat(
            [Message("system", system), Message("user", user_text, images=list(images or []))],
            None,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        try:
            for event in stream:
                if stop():
                    reply.interrupted = True
                    break
                reply.provider = event.provider or reply.provider
                if event.kind == "text":
                    if reply.first_token_at is None:
                        reply.first_token_at = self._clock()
                        reply.first_token_seconds = reply.first_token_at - started
                    out.feed(event.text)
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
        if not reply.interrupted:
            out.end_step()
        reply.full_text = DETAIL_RE.sub("\n", "".join(out.visible)).strip()
        reply.detail = out.segmenter.detail
        return reply


def collect_task_text(
    llm: LLMProvider, system: str, user_text: str, *, images: list[bytes] | None = None, max_tokens: int = 400
) -> str:
    """One-shot prompt without speaking (used inside tools); returns the visible text with think tags removed."""
    tags = HiddenTagFilter()
    parts: list[str] = []
    for event in llm.stream_chat([Message("system", system), Message("user", user_text, images=list(images or []))], None, max_tokens=max_tokens):
        if event.kind == "text":
            parts.append(tags.feed(event.text))
    parts.append(tags.flush())
    return "".join(parts).strip()


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


def _join_notes(*notes: str) -> str:
    """Context lines for the system prompt, empty ones skipped."""
    return "\n".join(note for note in notes if note)
