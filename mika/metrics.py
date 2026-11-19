"""Per-turn latency: end of the user's speech → transcript → first LLM token → first audio, logged as JSON lines."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .text import safe_print


class LatencyLog:
    """Prints one line per turn and appends it to data/latency.jsonl for the stage 5 benchmark."""

    def __init__(self, path: Path | None):
        self.path = path
        self.entries: list[dict[str, Any]] = []

    def record(
        self,
        *,
        route: str,
        origin: float,
        stt_engine: str = "",
        stt_seconds: float | None = None,
        first_token_at: float | None = None,
        first_audio_at: float | None = None,
        finished_at: float | None = None,
        provider: str = "",
        interrupted: bool = False,
    ) -> dict[str, Any]:
        """Store one turn; times are seconds measured from `origin` (end of speech, or text arrival when typed)."""

        def since(moment: float | None) -> float | None:
            """Seconds from the origin, rounded to milliseconds."""
            return None if moment is None else round(moment - origin, 3)

        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "route": route,
            "stt_engine": stt_engine,
            "stt_s": None if stt_seconds is None else round(stt_seconds, 3),
            "first_token_s": since(first_token_at),
            "first_audio_s": since(first_audio_at),
            "total_s": since(finished_at),
            "provider": provider,
            "interrupted": interrupted,
        }
        self.entries.append(entry)
        # "is" checks: a 0.0-second value must still be printed (0.0 == False in Python).
        parts = [f"{key}={value}" for key, value in entry.items() if key != "ts" and value is not None and value != "" and value is not False]
        safe_print("[latency] " + " ".join(parts))
        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except OSError as exc:
                safe_print(f"[latency] Gagal menulis log: {exc}")
        return entry
