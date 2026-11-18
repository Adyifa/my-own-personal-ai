"""Where long answers go. Voice replies stay short (1-3 sentences); details and sources are
shown instead of read aloud."""

from __future__ import annotations

from typing import Any, Protocol

from ..text import safe_print


class Display(Protocol):
    def show(self, title: str, body: str) -> None: ...


class ConsoleDisplay:
    def show(self, title: str, body: str) -> None:
        line = "-" * 60
        safe_print(f"{line}\n[{title}]\n{body}\n{line}")


class TrayDisplay:
    """Windows toast via pystray. Toasts truncate around 250 characters, so the full text
    also goes to the console log; a proper detail window is planned for stage 5."""

    def __init__(self, icon: Any, limit: int = 240):
        self.icon = icon
        self.limit = limit

    def show(self, title: str, body: str) -> None:
        safe_print(f"[detail] {body}")
        text = body if len(body) <= self.limit else body[: self.limit - 3].rstrip() + "..."
        try:
            self.icon.notify(text, title)
        except Exception:
            pass
