"""Open apps, games, websites, and files. Includes Start Menu / Desktop / Steam auto-discovery."""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from ..text import normalize, strip_command_words


@dataclass
class LaunchMatch:
    """A resolved launch target and which catalog it came from."""

    name: str
    target: str
    kind: str  # "apps" | "games" | "websites"


_SKIP_ALIAS_PREFIXES = ("uninstall", "hapus instalasi", "remove", "readme", "help")
_NAME_FILLER = re.compile(r"^(aplikasi|app|program|game|website|situs|web)\s+")
# Start Menu entries that are not apps. Uninstallers must never start by voice ("buka ... uninstall ..."), and a
# bare "Website" or "Documentation" shortcut would hijack "buka website detik.com".
_UNINSTALL_WORDS = {"uninstall", "uninstaller", "remove", "hapus"}
_GENERIC_ENTRIES = {"website", "web site", "documentation", "docs", "release notes", "readme", "read me", "manual",
                    "license", "help", "general help", "online help", "support", "changelog", "user guide", "homepage",
                    "home page"}


def is_app_name(alias: str) -> bool:
    """False for uninstallers and generic entries found during discovery (user aliases are never filtered)."""
    words = alias.split()
    return bool(words) and words[0] not in _UNINSTALL_WORDS and alias not in _GENERIC_ENTRIES

# Indonesian words and common abbreviations for apps whose Start Menu names are English.
# Added only when the app itself was discovered, so they never point at something missing.
APP_SYNONYMS = {
    "pengaturan": "settings", "setelan": "settings", "setting": "settings",
    "kamera": "camera", "foto": "photos", "galeri": "photos", "kalender": "calendar",
    "wa": "whatsapp", "vs code": "visual studio code", "vscode": "visual studio code",
    "store": "microsoft store", "explorer": "file explorer", "file manager": "file explorer",
    "penjelajah file": "file explorer", "perekam suara": "sound recorder", "cmd": "command prompt",
    "terminal": "windows terminal", "pengelola tugas": "task manager",
}


def _default_start_file(path: Path | str) -> None:
    """ShellExecute: opens files, folders, and shell: targets exactly like a double-click."""
    os.startfile(path)  # type: ignore[attr-defined]


def _default_run_command(command: str) -> None:
    subprocess.Popen(command, shell=True)


def _powershell_start_apps() -> str:
    """JSON of Get-StartApps: every Start Menu entry, including Microsoft Store apps that have no .lnk file."""
    script = (
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
        "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return result.stdout.decode("utf-8", errors="replace")


def scan_start_apps(runner: Callable[[], str] = _powershell_start_apps) -> dict[str, str]:
    """name → "shell:AppsFolder\\<AppID>", the same target the Start Menu itself launches."""
    try:
        rows = json.loads((runner() or "[]").lstrip("﻿"))  # UTF-8 console output may start with a BOM
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
    if isinstance(rows, dict):
        rows = [rows]  # ConvertTo-Json returns an object, not a list, for a single app
    apps: dict[str, str] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        name, app_id = normalize(str(row.get("Name", ""))), str(row.get("AppID", "")).strip()
        if name and app_id and is_app_name(name):
            apps.setdefault(name, f"shell:AppsFolder\\{app_id}")
    return apps


class Launcher:
    """App, game, website, and file catalog plus the side effects of opening them (injectable for tests)."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        open_url: Callable[[str], Any] | None = None,
        start_file: Callable[[Path], Any] | None = None,
        run_command: Callable[[str], Any] | None = None,
        start_apps_scanner: Callable[[], dict[str, str]] = scan_start_apps,
    ):
        self.config = config
        self._open_url = open_url or webbrowser.open
        self._start_file = start_file or _default_start_file
        self._run_command = run_command or _default_run_command
        self._scan_start_apps = start_apps_scanner
        self._discovered_apps: dict[str, str] | None = None
        self._discovered_store_apps: dict[str, str] | None = None
        self._discovered_games: dict[str, str] | None = None
        self._lock = threading.Lock()
        self._store_lock = threading.Lock()  # the PowerShell scan is the slowest; it must not hold up games

    # Catalog --------------------------------------------------------------------------

    def websites(self) -> dict[str, str]:
        return dict(self.config.get("websites", {}))

    def file_aliases(self) -> dict[str, str]:
        return dict(self.config.get("files", {}))

    def apps(self) -> dict[str, str]:
        """Store apps, then shortcuts (they win on equal names), the user's aliases, and synonyms for apps that exist."""
        merged = dict(self._store_apps_discovered())
        merged.update(self._apps_discovered())
        merged.update(self.config.get("apps", {}))
        by_name = {normalize(alias): target for alias, target in merged.items()}
        for synonym, canonical in APP_SYNONYMS.items():
            if synonym not in by_name and canonical in by_name:
                merged[synonym] = by_name[canonical]
        return merged

    def games(self) -> dict[str, str]:
        merged = dict(self._games_discovered())
        merged.update(self.config.get("games", {}))
        return merged

    def warm_up(self) -> None:
        """Scan Start Menu, Steam, and Store apps ahead of time so the first "buka X" waits for nothing."""
        self._apps_discovered()
        self._games_discovered()
        self._store_apps_discovered()

    def _apps_discovered(self) -> dict[str, str]:
        with self._lock:
            if self._discovered_apps is None:
                discovery = self.config.get("auto_discovery", {})
                apps: dict[str, str] = {}
                if discovery.get("enabled", True):
                    if discovery.get("scan_start_menu", True):
                        apps.update(scan_shortcuts(start_menu_paths()))
                    if discovery.get("scan_desktop", True):
                        apps.update(scan_shortcuts(desktop_paths()))
                self._discovered_apps = apps
            return self._discovered_apps

    def _store_apps_discovered(self) -> dict[str, str]:
        """Microsoft Store apps (WhatsApp, Spotify, Settings, Camera...) have no .lnk file, so ask Windows for them."""
        with self._store_lock:
            if self._discovered_store_apps is None:
                discovery = self.config.get("auto_discovery", {})
                enabled = discovery.get("enabled", True) and discovery.get("scan_store_apps", True)
                self._discovered_store_apps = self._scan_start_apps() if enabled else {}
            return self._discovered_store_apps

    def _games_discovered(self) -> dict[str, str]:
        with self._lock:
            if self._discovered_games is None:
                discovery = self.config.get("auto_discovery", {})
                if discovery.get("enabled", True) and discovery.get("scan_steam", True):
                    self._discovered_games = scan_steam_games()
                else:
                    self._discovered_games = {}
            return self._discovered_games

    # Actions --------------------------------------------------------------------------

    def open_url(self, url: str) -> None:
        self._open_url(url)

    def launch(self, target: str) -> None:
        """Open a URL/URI, a shell: target (Store apps), a file or shortcut, or run a command from the user's config."""
        expanded = os.path.expandvars(target)
        if expanded.lower().startswith("shell:"):
            self._start_file(expanded)  # shell:AppsFolder\<AppID> opens a Store app like the Start Menu does
            return
        if re.match(r"^[a-z][a-z0-9+.-]*://", expanded, flags=re.IGNORECASE):
            self._open_url(expanded)
            return
        path = Path(expanded).expanduser()
        if path.exists():
            self._start_file(path)
            return
        self._run_command(expanded)

    def open_path(self, path: Path) -> bool:
        path = Path(os.path.expandvars(str(path))).expanduser()
        if not path.exists():
            return False
        self._start_file(path)
        return True

    # Lookup ---------------------------------------------------------------------------

    def resolve(self, name: str, kinds: Iterable[str] = ("apps", "games", "websites")) -> LaunchMatch | None:
        """Resolve a spoken name to a launch target: exact → token subset → fuzzy."""
        query = _NAME_FILLER.sub("", normalize(name)).strip()
        if not query:
            return None
        entries = self._entries(kinds)

        for kind, alias, target in entries:
            if normalize(alias) == query:
                return LaunchMatch(alias, target, kind)

        query_tokens = set(query.split())
        subset = [
            (len(normalize(alias)), kind, alias, target)
            for kind, alias, target in entries
            if query_tokens <= set(normalize(alias).split()) and not normalize(alias).startswith(_SKIP_ALIAS_PREFIXES)
        ]
        if subset:
            _, kind, alias, target = min(subset, key=lambda item: item[0])
            return LaunchMatch(alias, target, kind)

        superset = [
            (len(normalize(alias)), kind, alias, target)
            for kind, alias, target in entries
            if normalize(alias) and set(normalize(alias).split()) <= query_tokens
        ]
        if superset:
            _, kind, alias, target = max(superset, key=lambda item: item[0])
            return LaunchMatch(alias, target, kind)

        by_alias = {normalize(alias): (kind, alias, target) for kind, alias, target in entries}
        close = difflib.get_close_matches(query, list(by_alias), n=1, cutoff=0.82)
        if close:
            kind, alias, target = by_alias[close[0]]
            return LaunchMatch(alias, target, kind)
        return None

    def suggest(self, name: str, kinds: Iterable[str] = ("apps", "games"), limit: int = 3) -> list[str]:
        aliases = [alias for _, alias, _ in self._entries(kinds)]
        return difflib.get_close_matches(normalize(name), aliases, n=limit, cutoff=0.5)

    def _entries(self, kinds: Iterable[str]) -> list[tuple[str, str, str]]:
        sources = {"apps": self.apps, "games": self.games, "websites": self.websites}
        entries: list[tuple[str, str, str]] = []
        for kind in kinds:
            for alias, target in sources[kind]().items():
                entries.append((kind, alias, target))
        return entries

    def resolve_file(self, query: str, command: str | None = None) -> Path | None:
        for alias, file_path in self.file_aliases().items():
            alias_norm = normalize(alias)
            if alias_norm and (alias_norm == normalize(query) or (command and alias_norm in normalize(command))):
                return Path(os.path.expandvars(file_path)).expanduser()
        found = self.find_file(query)
        if found is None and command:
            found = self.find_file(command)
        return found

    def find_file(self, target: str) -> Path | None:
        search_name = strip_command_words(target)
        if not search_name:
            return None

        started_at = time.time()
        max_seconds = float(self.config.get("file_search", {}).get("max_seconds", 5))
        wanted = _loose(search_name)
        for folder in self.config.get("search_folders", []):
            root = Path(os.path.expandvars(folder)).expanduser()
            if not root.exists():
                continue
            direct = root / search_name
            if direct.exists():
                return direct
            try:
                for path in root.rglob("*"):
                    if time.time() - started_at > max_seconds:
                        return None
                    if wanted in _loose(path.stem) or wanted in _loose(path.name):
                        return path
            except (PermissionError, OSError):
                continue
        return None


def _loose(text: str) -> str:
    """Spoken names have spaces where file names have _ - or dots: "laporan q3" ~ "laporan_q3"."""
    return re.sub(r"[\s_.-]+", " ", normalize(text)).strip()


# Discovery helpers (unchanged behaviour from the original assistant.py) -----------------


def start_menu_paths() -> list[Path]:
    paths = [
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    ]
    return [path for path in paths if path.exists()]


def desktop_paths() -> list[Path]:
    paths = [
        Path.home() / "Desktop",
        Path(os.environ.get("PUBLIC", "C:/Users/Public")) / "Desktop",
    ]
    return [path for path in paths if path.exists()]


def scan_shortcuts(roots: list[Path]) -> dict[str, str]:
    shortcuts: dict[str, str] = {}
    for root in roots:
        for pattern in ("*.lnk", "*.url", "*.exe"):
            try:
                for path in root.rglob(pattern):
                    alias = normalize(path.stem)
                    if alias and alias not in shortcuts and is_app_name(alias):
                        shortcuts[alias] = str(path)
            except OSError:
                continue
    return shortcuts


def scan_steam_games() -> dict[str, str]:
    library_paths: list[Path] = []
    for root in possible_steam_roots():
        steamapps = root / "steamapps"
        if steamapps.exists():
            library_paths.append(steamapps)
        library_paths.extend(parse_steam_libraries(root / "steamapps" / "libraryfolders.vdf"))

    games: dict[str, str] = {}
    for steamapps in dedupe_paths(library_paths):
        try:
            for manifest in steamapps.glob("appmanifest_*.acf"):
                appid, name = parse_steam_manifest(manifest)
                if appid and name:
                    games[normalize(name)] = f"steam://rungameid/{appid}"
        except OSError:
            continue
    return games


def possible_steam_roots() -> list[Path]:
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Steam",
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Steam",
    ]
    return [path for path in candidates if path.exists()]


def parse_steam_libraries(vdf_path: Path) -> list[Path]:
    if not vdf_path.exists():
        return []
    try:
        text = vdf_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    libraries: list[Path] = []
    for match in re.finditer(r'"path"\s+"([^"]+)"', text):
        steamapps = Path(match.group(1).replace("\\\\", "\\")) / "steamapps"
        if steamapps.exists():
            libraries.append(steamapps)
    return libraries


def parse_steam_manifest(manifest_path: Path) -> tuple[str | None, str | None]:
    try:
        text = manifest_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None, None
    appid_match = re.search(r'"appid"\s+"([^"]+)"', text)
    name_match = re.search(r'"name"\s+"([^"]+)"', text)
    return (appid_match.group(1) if appid_match else None, name_match.group(1) if name_match else None)


def dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result
