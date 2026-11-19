"""Clipboard text for "rangkum/terjemahkan yang aku copy"; the text is untrusted data, never instructions."""

from __future__ import annotations

import re
from typing import Any, Callable

from .web_search import sanitize_untrusted

_LANGUAGES = {
    "inggris": "Inggris", "english": "Inggris", "indonesia": "Indonesia", "jepang": "Jepang", "korea": "Korea",
    "arab": "Arab", "mandarin": "Mandarin", "china": "Mandarin", "cina": "Mandarin", "jerman": "Jerman",
    "prancis": "Prancis", "perancis": "Prancis", "spanyol": "Spanyol", "belanda": "Belanda", "jawa": "Jawa",
    "sunda": "Sunda", "melayu": "Melayu", "thailand": "Thailand", "rusia": "Rusia", "italia": "Italia",
}


def target_language(command: str) -> str | None:
    """"terjemahkan ke bahasa jepang" → "Jepang"; None lets the model pick (Indonesian ⇄ English)."""
    match = re.search(r"\bke\s+(?:dalam\s+)?(?:bahasa\s+)?(\w+)", command)
    if match and match.group(1) in _LANGUAGES:
        return _LANGUAGES[match.group(1)]
    for word, language in _LANGUAGES.items():
        if re.search(rf"\bbahasa\s+{word}\b", command):
            return language
    return None


def task_instruction(action: str, language: str | None) -> str:
    """What the LLM is asked to do with the clipboard text."""
    if action == "translate":
        if language:
            return f"Terjemahkan teks berikut ke bahasa {language}. Tulis terjemahannya saja, tanpa pengantar."
        return (
            "Terjemahkan teks berikut ke bahasa Indonesia; kalau teksnya sudah bahasa Indonesia, terjemahkan ke "
            "bahasa Inggris. Tulis terjemahannya saja, tanpa pengantar."
        )
    if action == "explain":
        return "Jelaskan maksud teks berikut dengan bahasa sederhana dalam 1-3 kalimat."
    return "Rangkum teks berikut dalam 1-3 kalimat yang paling penting. Kalau ada poin penting lain, tulis setelah [DETAIL]."


class Clipboard:
    """Read and write clipboard text through pyperclip (injectable for tests)."""

    def __init__(self, paste: Callable[[], Any] | None = None, copy: Callable[[str], Any] | None = None, max_chars: int = 6000):
        self._paste = paste
        self._copy = copy
        self.max_chars = max_chars  # ~1500-2000 tokens: fits the 4k context of the local model

    def read(self) -> tuple[str, bool]:
        """(sanitized text, was_truncated); empty when the clipboard holds no text."""
        paste = self._paste
        if paste is None:
            import pyperclip

            paste = pyperclip.paste
        try:
            text = str(paste() or "")
        except Exception:
            return "", False
        text = sanitize_untrusted(text)
        return text[: self.max_chars], len(text) > self.max_chars

    def write(self, text: str) -> bool:
        """Put text on the clipboard (used to hand back a translation); False if that failed."""
        copy = self._copy
        if copy is None:
            import pyperclip

            copy = pyperclip.copy
        try:
            copy(text)
            return True
        except Exception:
            return False
