"""Timers, reminders, and alarms: saved to disk so they survive restarts, fired by a background thread."""

from __future__ import annotations

import difflib
import json
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from ..text import normalize, safe_print


@dataclass
class Reminder:
    """One scheduled announcement."""

    id: str
    kind: str  # "timer" | "reminder" | "alarm"
    message: str
    due: datetime
    created: datetime
    seconds: int | None = None  # timer length, for "timer 5 menit sudah habis"

    def to_json(self) -> dict:
        """Serializable form with ISO timestamps (timezone kept)."""
        return {
            "id": self.id,
            "kind": self.kind,
            "message": self.message,
            "due": self.due.isoformat(),
            "created": self.created.isoformat(),
            "seconds": self.seconds,
        }

    @classmethod
    def from_json(cls, data: dict) -> "Reminder":
        """Inverse of to_json."""
        return cls(
            id=str(data["id"]),
            kind=str(data.get("kind", "reminder")),
            message=str(data.get("message", "")),
            due=datetime.fromisoformat(data["due"]),
            created=datetime.fromisoformat(data.get("created", data["due"])),
            seconds=data.get("seconds"),
        )


DueCallback = Callable[[Reminder, bool], None]  # (reminder, fired_late)


def local_now() -> datetime:
    """Timezone-aware local time, so stored times stay correct across DST or travel."""
    return datetime.now().astimezone()


class ReminderService:
    """Thread-safe store plus a 1-second scheduler; missed items fire late once, very old ones are dropped."""

    def __init__(
        self,
        path: Path | None,
        *,
        clock: Callable[[], datetime] = local_now,
        on_due: DueCallback | None = None,
        missed_grace_hours: float = 12,
    ):
        self.path = path
        self._clock = clock
        self.on_due = on_due
        self.missed_grace = timedelta(hours=missed_grace_hours)
        self.last_fired: tuple[Reminder, datetime] | None = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._items: list[Reminder] = self._load()

    def now(self) -> datetime:
        """Current time from the injected clock (tests use a fake one)."""
        return self._clock()

    def add(self, kind: str, message: str, due: datetime, seconds: int | None = None) -> Reminder:
        """Schedule something and save immediately."""
        item = Reminder(uuid.uuid4().hex[:8], kind, message.strip(), due, self.now(), seconds)
        with self._lock:
            self._items.append(item)
            self._save()
        return item

    def upcoming(self, kinds: tuple[str, ...] | None = None) -> list[Reminder]:
        """Pending items, soonest first."""
        with self._lock:
            items = [item for item in self._items if kinds is None or item.kind in kinds]
        return sorted(items, key=lambda item: item.due)

    def cancel(self, kinds: tuple[str, ...], query: str = "", everything: bool = False) -> list[Reminder]:
        """Cancel all, the best match for `query`, or the soonest one; returns what was removed."""
        candidates = self.upcoming(kinds)
        if not candidates:
            return []
        if everything:
            chosen = candidates
        elif query:
            chosen = _best_match(candidates, query)
        else:
            chosen = candidates[:1]
        with self._lock:
            ids = {item.id for item in chosen}
            self._items = [item for item in self._items if item.id not in ids]
            self._save()
        return chosen

    def check(self) -> list[Reminder]:
        """Fire everything that is due; called every second by the scheduler thread."""
        now = self.now()
        with self._lock:
            due = [item for item in self._items if item.due <= now]
            if not due:
                return []
            self._items = [item for item in self._items if item.due > now]
            self._save()
        fired = []
        for item in sorted(due, key=lambda item: item.due):
            if now - item.due > self.missed_grace:
                continue  # the laptop was off for too long; an announcement now would only confuse
            late = now - item.due > timedelta(seconds=90)
            self.last_fired = (item, now)
            fired.append(item)
            if self.on_due is not None:
                try:
                    self.on_due(item, late)
                except Exception as exc:
                    safe_print(f"[reminder] Gagal mengumumkan: {exc}")
        return fired

    def start(self, interval: float = 1.0) -> None:
        """Start the scheduler thread (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()

        def loop() -> None:
            """Check once per interval until stop() is called."""
            while not self._stop.wait(interval):
                self.check()

        self.check()  # announce anything missed while Mika was not running
        self._thread = threading.Thread(target=loop, name="mika-reminders", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the scheduler thread."""
        self._stop.set()

    def _load(self) -> list[Reminder]:
        """Read saved items; a corrupt file is ignored rather than crashing startup."""
        if self.path is None or not self.path.exists():
            return []
        try:
            return [Reminder.from_json(row) for row in json.loads(self.path.read_text(encoding="utf-8"))]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            safe_print(f"[reminder] File pengingat tidak terbaca, diabaikan: {exc}")
            return []

    def _save(self) -> None:
        """Atomic write (temp file + replace) so a crash never leaves half a file."""
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps([item.to_json() for item in self._items], ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.path)


def _best_match(items: list[Reminder], query: str) -> list[Reminder]:
    """Items whose message contains the query, else the closest fuzzy match."""
    wanted = normalize(query)
    contains = [item for item in items if wanted in normalize(item.message) or normalize(item.message) in wanted]
    if contains:
        return contains[:1]
    messages = {normalize(item.message): item for item in items if item.message}
    close = difflib.get_close_matches(wanted, list(messages), n=1, cutoff=0.5)
    return [messages[close[0]]] if close else []
