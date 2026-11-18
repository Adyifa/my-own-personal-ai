"""Short-term memory: the last few (question, answer) pairs, small enough for a 4k-token context."""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Callable

from .llm.base import Message


class ConversationSession:
    """Rolling chat history that forgets everything after the user has been idle for a while."""

    def __init__(
        self,
        max_turns: int = 6,
        idle_seconds: float = 900,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._turns: deque[tuple[str, str]] = deque(maxlen=max(1, max_turns))  # answers only, never raw tool output
        self.idle_seconds = idle_seconds
        self._clock = clock
        self._last_activity: float | None = None
        self.last_results: list[Any] = []  # last web results, kept outside the prompt for "buka yang kedua"

    def _expired(self) -> bool:
        """True when the conversation has been idle longer than the limit."""
        return self._last_activity is not None and self._clock() - self._last_activity > self.idle_seconds

    def history(self) -> list[Message]:
        """Previous turns as chat messages, or nothing if the session went stale."""
        if self._expired():
            self.clear()
        messages: list[Message] = []
        for user_text, assistant_text in self._turns:
            messages.append(Message("user", user_text))
            messages.append(Message("assistant", assistant_text))
        return messages

    def add_turn(self, user_text: str, assistant_text: str) -> None:
        """Remember one finished turn."""
        if self._expired():
            self.clear()
        self._turns.append((user_text, assistant_text))
        self._last_activity = self._clock()

    def clear(self) -> None:
        """Forget the conversation (e.g. after "selesai ngobrol")."""
        self._turns.clear()
        self.last_results = []
        self._last_activity = None

    def __len__(self) -> int:
        return len(self._turns)
