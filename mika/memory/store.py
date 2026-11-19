"""Facts the user asked Mika to remember, in data/memory.json (git-ignored), with list/forget by voice."""

from __future__ import annotations

import difflib
import json
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from ..text import plain_words, safe_print

_STOPWORDS = {
    "aku", "saya", "kamu", "yang", "dan", "di", "ke", "dari", "itu", "ini", "untuk", "dengan", "ya", "suka", "nggak",
    "tidak", "juga", "kalau", "kalo", "bahwa", "jadi", "ada", "mau", "lagi", "sama", "pada", "atau", "apa",
    "soal", "tentang", "hal", "masalah",
}

# Never stored, even when asked: these belong in a password manager, not in a voice assistant's memory file.
_SENSITIVE = [
    (re.compile(r"\b(password|passwd|kata sandi|sandi|pin|otp|kode verifikasi|cvv|api key|token)\b"), "password, PIN, atau kode rahasia"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "nomor kartu atau nomor identitas"),
    (re.compile(r"\b(nik|no ktp|nomor ktp|nomor rekening|no rek|rekening)\b"), "nomor identitas atau rekening"),
]


@dataclass
class MemoryItem:
    """One remembered fact, in the user's own words."""

    id: str
    text: str
    created: str
    source: str  # "voice" (user command) or "agent" (the LLM's remember tool)


def sensitive_reason(text: str) -> str:
    """Why a fact must not be stored, or "" when it is fine."""
    t = plain_words(text)
    for pattern, reason in _SENSITIVE:
        if pattern.search(t):
            return reason
    return ""


def as_spoken(fact: str) -> str:
    """First person → second person for Mika's confirmation: "aku suka kopi" → "kamu suka kopi"."""
    return re.sub(r"\b(aku|saya|gue|gw)\b", "kamu", fact, flags=re.IGNORECASE)


class MemoryStore:
    """Thread-safe list of facts; relevance for the prompt is simple word overlap (no embeddings needed)."""

    def __init__(self, path: Path | None, *, clock=lambda: datetime.now().astimezone(), max_items: int = 200):
        self.path = path
        self._clock = clock
        self.max_items = max_items
        self._lock = threading.Lock()
        self._items: list[MemoryItem] = self._load()

    def items(self) -> list[MemoryItem]:
        """All facts, oldest first."""
        with self._lock:
            return list(self._items)

    def add(self, text: str, source: str = "voice") -> MemoryItem | None:
        """Store a fact (deduplicated); None if it looked sensitive or empty."""
        fact = re.sub(r"\s+", " ", text).strip(" .,")
        if not fact or sensitive_reason(fact):
            return None
        with self._lock:
            for item in self._items:
                if plain_words(item.text) == plain_words(fact):
                    return item
            item = MemoryItem(uuid.uuid4().hex[:8], fact, self._clock().isoformat(timespec="seconds"), source)
            self._items.append(item)
            del self._items[: max(0, len(self._items) - self.max_items)]
            self._save()
            return item

    def forget(self, query: str) -> list[MemoryItem]:
        """Delete the fact that best matches `query` ("kopi" → "aku suka kopi tanpa gula")."""
        wanted = plain_words(query)
        if not wanted:
            return []
        with self._lock:
            words = set(wanted.split()) - _STOPWORDS or set(wanted.split())
            scored = []
            for item in self._items:
                text = plain_words(item.text)
                overlap = len(words & set(text.split())) / len(words)
                ratio = difflib.SequenceMatcher(None, wanted, text).ratio()
                scored.append((max(overlap, ratio), item))
            scored.sort(key=lambda pair: pair[0], reverse=True)
            if not scored or scored[0][0] < 0.5:
                return []
            removed = [scored[0][1]]
            self._items = [item for item in self._items if item.id != removed[0].id]
            self._save()
            return removed

    def clear(self) -> int:
        """Delete everything (the assistant asks for voice confirmation first); returns how many were removed."""
        with self._lock:
            count = len(self._items)
            self._items = []
            self._save()
            return count

    def relevant(self, text: str, limit: int = 8) -> list[MemoryItem]:
        """Facts sharing words with the utterance first, then the newest ones, for the system prompt."""
        with self._lock:
            items = list(self._items)
        if len(items) <= limit:
            return items
        words = set(plain_words(text).split()) - _STOPWORDS
        ranked = sorted(
            enumerate(items),
            key=lambda pair: (len(words & set(plain_words(pair[1].text).split())), pair[0]),
            reverse=True,
        )
        return [item for _, item in ranked[:limit]]

    def _load(self) -> list[MemoryItem]:
        """Read saved facts; a corrupt file is ignored rather than crashing startup."""
        if self.path is None or not self.path.exists():
            return []
        try:
            return [MemoryItem(**row) for row in json.loads(self.path.read_text(encoding="utf-8"))]
        except (OSError, ValueError, TypeError) as exc:
            safe_print(f"[memory] File memori tidak terbaca, diabaikan: {exc}")
            return []

    def _save(self) -> None:
        """Atomic write so a crash never leaves half a file."""
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps([asdict(item) for item in self._items], ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.path)
