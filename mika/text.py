"""Text helpers shared by the rule router, the wake-phrase matcher, and logging."""

from __future__ import annotations

import re
import sys


def safe_print(message: str) -> None:
    """Print that survives pythonw (no console) and non-UTF-8 Windows consoles."""
    stream = sys.stdout
    if not stream:
        return
    try:
        print(message, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        print(message.encode(encoding, errors="replace").decode(encoding, errors="replace"), flush=True)
    except (OSError, ValueError):
        pass


def normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s./:-]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def plain_words(text: str) -> str:
    """Lowercase words only, all punctuation removed (for fuzzy comparisons, not for URLs or times)."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def clean_transcript(text: str) -> str:
    """Drop sentence punctuation that Whisper adds ("Kecilkan volume." → "Kecilkan volume") while keeping
    dots inside tokens such as "kompas.com" or "19.30"."""
    text = re.sub(r"[.!?…]+(?=\s|$)", " ", text)
    text = re.sub(r"[,;:\"“”]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def contains_phrase(text: str, phrase: str) -> bool:
    """Whole-word match, so the alias "word" does not fire inside "password"."""
    if not phrase:
        return False
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


_URL_LIKE = re.compile(
    r"^(https?://)?[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}(:\d+)?(/\S*)?$",
    re.IGNORECASE,
)


def looks_like_url(text: str) -> bool:
    return bool(_URL_LIKE.match(text.strip()))


_COMMAND_PREFIXES = [
    r"^(tolong\s+)?buka\s+(website|web|situs|file|folder|aplikasi|app|program)?\s*",
    r"^(tolong\s+)?cari\s+(file|folder|dokumen)?\s*",
    r"^(tolong\s+)?jalankan\s+(aplikasi|app|program)?\s*",
    r"^(tolong\s+)?open\s+",
]


def strip_command_words(text: str) -> str:
    result = normalize(text)
    for pattern in _COMMAND_PREFIXES:
        result = re.sub(pattern, "", result).strip()
    return result


_CONVERSATIONAL_REPLACEMENTS = {
    "bukain": "buka",
    "bukakan": "buka",
    "carikan": "cari",
    "cariin": "cari",
    "puterin": "putar",
    "putarkan": "putar",
    "nyalain": "buka",
    "matikanin": "matikan",
}

_CONVERSATIONAL_PATTERNS = [
    r"^((zeta|mika)\s+)?(tolong|coba|please)\s+",
    r"^(aku\s+)?(mau|pengen|ingin)\s+",
    r"^(bisa\s+)?(tolong\s+)?",
    r"\s+(dong|ya|please)$",
]


def clean_conversational_command(command: str) -> str:
    """Turn casual speech ("tolong bukain youtube dong") into a command ("buka youtube")."""
    command = normalize(command)
    for source, replacement in _CONVERSATIONAL_REPLACEMENTS.items():
        command = re.sub(rf"\b{re.escape(source)}\b", replacement, command)

    previous = None
    while previous != command:
        previous = command
        for pattern in _CONVERSATIONAL_PATTERNS:
            command = re.sub(pattern, "", command).strip()
    return normalize(command)
