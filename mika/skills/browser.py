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


def spotify_url(config: dict[str, Any], query: str, *, app_installed: bool = False) -> str:
    """"auto" searches in the Spotify app when it is installed and in the web player otherwise."""
    encoded = urllib.parse.quote(query)
    open_mode = normalize(str(config.get("music", {}).get("open_mode", "auto")))
    if open_mode == "app" or (open_mode == "auto" and app_installed):
        return f"spotify:search:{encoded}"
    return f"https://open.spotify.com/search/{encoded}"


def has_spotify_app(launcher: Any) -> bool:
    """True when the app catalog has Spotify itself (a shortcut or a Store app), not just a website alias."""
    try:
        apps = launcher.apps()
    except Exception:
        return False
    return any(normalize(alias) == "spotify" and not str(target).startswith("http") for alias, target in apps.items())
