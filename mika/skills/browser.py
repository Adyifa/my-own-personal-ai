"""Browser search pages (Google/YouTube) and Spotify search URLs."""

from __future__ import annotations

import urllib.parse
from typing import Any

from ..text import normalize


def search_url(config: dict[str, Any], provider: str, query: str) -> str | None:
    template = config.get("search", {}).get("providers", {}).get(provider)
    if not template:
        return None
    return str(template).format(query=urllib.parse.quote_plus(query))


def spotify_url(config: dict[str, Any], query: str) -> str:
    encoded = urllib.parse.quote(query)
    open_mode = normalize(str(config.get("music", {}).get("open_mode", "web")))
    if open_mode == "app":
        return f"spotify:search:{encoded}"
    return f"https://open.spotify.com/search/{encoded}"
