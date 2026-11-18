"""Wake phrase matching on a transcript ("halo mika buka youtube" -> "buka youtube")."""

from __future__ import annotations

from typing import Any

from ..text import normalize


HELLO_LIKE = {"halo", "hai", "hey", "helo", "hello"}
# Common mis-hearings of "Mika" by Google STT, plus the old "Zeta" name.
NAME_LIKE = {"mika", "mica", "mikha", "nika", "zeta", "zetta", "seta", "jeta", "zita", "ceta"}


def strip_wake_prefix(command: str, wake_config: dict[str, Any]) -> tuple[bool, str]:
    """Return (matched, rest_of_command). The phrase may appear mid-transcript."""
    phrases = wake_config.get("phrases", [])
    normalized_command = normalize(command)
    normalized_phrases = sorted(
        {normalize(str(phrase)) for phrase in phrases if normalize(str(phrase))},
        key=len,
        reverse=True,
    )
    for phrase in normalized_phrases:
        if normalized_command == phrase:
            return True, ""
        if normalized_command.startswith(f"{phrase} "):
            return True, normalized_command[len(phrase) :].strip()

        if wake_config.get("match_anywhere", True):
            marker = f" {phrase} "
            padded = f" {normalized_command} "
            index = padded.find(marker)
            if index >= 0:
                return True, padded[index + len(marker) :].strip()

    fuzzy = strip_fuzzy_wake(normalized_command)
    if fuzzy is not None:
        return True, fuzzy

    return False, normalized_command


def strip_fuzzy_wake(command: str) -> str | None:
    tokens = command.split()
    for index, token in enumerate(tokens):
        if token not in HELLO_LIKE:
            continue
        if index + 1 < len(tokens) and tokens[index + 1] in NAME_LIKE:
            return " ".join(tokens[index + 2 :]).strip()
    return None
