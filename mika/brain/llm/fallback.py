"""Fallback chain: try LLM providers in order (local first) and skip ones that failed recently."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any, Callable, Iterator, Sequence

from ...text import safe_print
from .base import LLMError, LLMProvider, Message, ProviderUnavailable, StreamEvent


class FallbackProvider:
    """Looks like one provider to the agent; falls back only before the first token is heard."""

    name = "fallback"

    def __init__(
        self,
        providers: Sequence[LLMProvider],
        *,
        cooldown_seconds: float = 120,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.providers = list(providers)
        self.cooldown_seconds = cooldown_seconds  # avoid paying a dead provider's timeout on every turn
        self._clock = clock
        self._failed_at: dict[str, float] = {}
        self.last_provider = ""

    def is_configured(self) -> bool:
        """True if at least one provider could be used."""
        return any(provider.is_configured() for provider in self.providers)

    def _cooling_down(self, provider: LLMProvider) -> bool:
        """True while a recently failed provider should be skipped."""
        failed_at = self._failed_at.get(provider.name)
        return failed_at is not None and self._clock() - failed_at < self.cooldown_seconds

    def _mark_failed(self, provider: LLMProvider, error: Exception) -> None:
        """Start the cooldown for a provider and log why."""
        self._failed_at[provider.name] = self._clock()
        safe_print(f"[llm] {provider.name} gagal, coba provider berikutnya: {error}")

    def warmup(self) -> None:
        """Load the first usable provider; a dead one goes on cooldown before the user's first question."""
        for provider in self.providers:
            if not provider.is_configured() or self._cooling_down(provider):
                continue
            try:
                provider.warmup()
                return
            except Exception as exc:  # warm-up must never crash the app
                self._mark_failed(provider, exc)

    def stream_chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[StreamEvent]:
        """Stream from the first working provider; switching mid-answer would restart the sentence, so it never does."""
        errors: list[str] = []
        for provider in self.providers:
            if not provider.is_configured():
                continue
            if self._cooling_down(provider):
                errors.append(f"{provider.name}: cooldown")
                continue
            started = False
            try:
                for event in provider.stream_chat(messages, tools, temperature=temperature, max_tokens=max_tokens):
                    if not started:
                        started = True
                        self.last_provider = provider.name
                    yield replace(event, provider=provider.name)
                self._failed_at.pop(provider.name, None)
                return
            except Exception as exc:  # any provider bug becomes a fallback, not a crash
                if started:
                    if isinstance(exc, LLMError):
                        raise
                    raise LLMError(f"{provider.name}: {exc}") from exc
                self._mark_failed(provider, exc)
                errors.append(f"{provider.name}: {exc}")
        raise ProviderUnavailable("Tidak ada provider LLM yang bisa dipakai. " + "; ".join(errors))
