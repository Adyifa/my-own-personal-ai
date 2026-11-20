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


def build_vision_llm(config: dict[str, Any]) -> FallbackProvider:
    """Same chain with vision models. Screenshots go to the cloud only if vision.allow_cloud is on (off by default)."""
    from .ollama import OllamaProvider
    from .openai_compat import OpenAICompatProvider

    llm_config = config.get("llm", {})
    vision = config.get("vision", {})
    providers: list[LLMProvider] = []
    for name in llm_config.get("providers", ["ollama", "openai"]):
        if name == "ollama":
            providers.append(OllamaProvider({**llm_config.get("ollama", {}), "model": vision.get("ollama_model", "qwen2.5vl:3b")}))
        elif name in ("openai", "openai_compatible") and vision.get("allow_cloud", False):
            providers.append(OpenAICompatProvider({**llm_config.get("openai", {}), "model": vision.get("openai_model", "gpt-5-mini")}))
    return FallbackProvider(providers, cooldown_seconds=float(llm_config.get("failure_cooldown_seconds", 120)))


def build_private_llm(config: dict[str, Any]) -> FallbackProvider | None:
    """The chain for curhat: local models only, unless companion.allow_cloud is on. None when nothing is left."""
    from .ollama import OllamaProvider
    from .openai_compat import OpenAICompatProvider

    llm_config = config.get("llm", {})
    allow_cloud = bool(config.get("companion", {}).get("allow_cloud", False))
    providers: list[LLMProvider] = []
    for name in llm_config.get("providers", ["ollama", "openai"]):
        if name == "ollama":
            provider: LLMProvider = OllamaProvider(llm_config.get("ollama", {}))
        elif name in ("openai", "openai_compatible"):
            provider = OpenAICompatProvider(llm_config.get("openai", {}))
        else:
            continue
        if allow_cloud or getattr(provider, "local", False):
            providers.append(provider)
    if not providers:
        return None
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
    "build_private_llm",
    "build_vision_llm",
]
