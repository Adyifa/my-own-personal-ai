"""Quick voice notes in a plain Markdown file the user can open and edit (data/notes.md, never committed)."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

_LINE = re.compile(r"^- (?P<stamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}) [-—] (?P<text>.+)$")


class NotesStore:
    """Append-only note list; reading returns the newest first."""

    def __init__(self, path: Path):
        self.path = path

    def add(self, text: str, now: datetime) -> str:
        """Append one note with a timestamp and return the cleaned text."""
        text = re.sub(r"\s+", " ", text).strip()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("# Catatan Mika\n\n", encoding="utf-8")
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(f"- {now:%Y-%m-%d %H:%M} — {text}\n")
        return text

    def recent(self, count: int = 10) -> list[tuple[str, str]]:
        """Newest notes first as (timestamp, text)."""
        if not self.path.exists():
            return []
        notes = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            match = _LINE.match(line.strip())
            if match:
                notes.append((match.group("stamp"), match.group("text")))
        return list(reversed(notes))[:count]
