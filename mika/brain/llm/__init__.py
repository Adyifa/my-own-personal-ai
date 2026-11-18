"""LLM providers (Ollama, OpenAI-compatible) and the fallback chain that joins them."""

from __future__ import annotations

from typing import Any

from .base import LLMError, LLMProvider, Message, ProviderUnavailable, StreamEvent, ToolCall
from .fallback import FallbackProvider


def build_llm(config: dict[str, Any]) -> FallbackProvider:
    """Build the provider chain in the order given by config["llm"]["providers"]."""
    from .ollama import OllamaProvider
    from .openai_compat import OpenAICompatProvider

    llm_config = config.get("llm", {})
    providers: list[LLMProvider] = []
    for name in llm_config.get("providers", ["ollama", "openai"]):
        if name == "ollama":
            providers.append(OllamaProvider(llm_config.get("ollama", {})))
        elif name in ("openai", "openai_compatible"):
            providers.append(OpenAICompatProvider(llm_config.get("openai", {})))
    return FallbackProvider(providers, cooldown_seconds=float(llm_config.get("failure_cooldown_seconds", 120)))


__all__ = [
    "FallbackProvider",
    "LLMError",
    "LLMProvider",
    "Message",
    "ProviderUnavailable",
    "StreamEvent",
    "ToolCall",
    "build_llm",
]
