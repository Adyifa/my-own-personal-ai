"""Composition root: wires config → speaker, launcher, LLM, tools, agent → Assistant."""

from __future__ import annotations

from typing import Any

from .assistant import Assistant
from .audio.speech import Speaker
from .text import safe_print


def build_assistant(
    config: dict[str, Any],
    *,
    speaker: Any = None,
    display: Any = None,
    llm: Any = None,
    searcher: Any = None,
    launcher: Any = None,
    power_runner: Any = None,
    hub: Any = None,
) -> Assistant:
    """Every dependency is injectable, which is how tests run without mic, speakers, model, or network."""
    speaker = speaker or Speaker.from_config(config)
    extra: dict[str, Any] = {"power_runner": power_runner} if power_runner is not None else {}
    assistant = Assistant(config, speaker, display=display, launcher=launcher, hub=hub, **extra)
    if config.get("llm", {}).get("enabled", True):
        try:
            assistant.agent = build_agent(config, assistant, speaker, llm=llm, searcher=searcher)
        except ImportError as exc:
            # The rule path must keep working even if the AI extras are not installed.
            safe_print(f"[llm] Mode AI nonaktif, dependency belum terpasang: {exc}")
    return assistant


def build_agent(config: dict[str, Any], assistant: Assistant, speaker: Any, *, llm: Any = None, searcher: Any = None) -> Any:
    """LLM chain + tools + session → Agent; risky tools confirm through the assistant's voice prompt."""
    from .brain.agent import Agent
    from .brain.llm import build_llm
    from .brain.session import ConversationSession
    from .brain.tools import ToolRegistry
    from .brain.toolset import build_default_tools
    from .skills.web_search import WebSearcher

    agent_config = config.get("agent", {})
    session = ConversationSession(
        max_turns=int(agent_config.get("history_turns", 6)),
        idle_seconds=float(agent_config.get("session_idle_minutes", 15)) * 60,
    )
    tools = ToolRegistry(
        build_default_tools(
            launcher=assistant.launcher,
            searcher=searcher if searcher is not None else WebSearcher(config),
            session=session,
            message=assistant.message,
            config=config,
            power_runner=assistant.power_runner,
            hub=assistant.hub,
        ),
        confirm=assistant.request_confirmation,
    )
    return Agent(
        llm if llm is not None else build_llm(config),
        tools,
        session,
        config,
        speak=speaker.say_async,
    )
