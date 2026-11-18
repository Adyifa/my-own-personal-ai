"""Open apps, games, websites, and files. Includes Start Menu / Desktop / Steam auto-discovery."""

from __future__ import annotations

import difflib
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
    name: str
    target: str
    kind: str  # "apps" | "games" | "websites"


_SKIP_ALIAS_PREFIXES = ("uninstall", "hapus instalasi", "remove", "readme", "help")
_NAME_FILLER = re.compile(r"^(aplikasi|app|program|game|website|situs|web)\s+")


def _default_start_file(path: Path) -> None:
    os.startfile(path)  # type: ignore[attr-defined]


def _default_run_command(command: str) -> None:
    subprocess.Popen(command, shell=True)


class Launcher:
    def __init__(
        self,
        config: dict[str, Any],
        *,
        open_url: Callable[[str], Any] | None = None,
        start_file: Callable[[Path], Any] | None = None,
        run_command: Callable[[str], Any] | None = None,
    ):
        self.config = config
        self._open_url = open_url or webbrowser.open
        self._start_file = start_file or _default_start_file
        self._run_command = run_command or _default_run_command
        self._discovered_apps: dict[str, str] | None = None
        self._discovered_games: dict[str, str] | None = None
        self._lock = threading.Lock()

    # Catalog --------------------------------------------------------------------------

    def websites(self) -> dict[str, str]:
        return dict(self.config.get("websites", {}))

    def file_aliases(self) -> dict[str, str]:
        return dict(self.config.get("files", {}))

    def apps(self) -> dict[str, str]:
        merged = dict(self._apps_discovered())
        merged.update(self.config.get("apps", {}))
        return merged

    def games(self) -> dict[str, str]:
        merged = dict(self._games_discovered())
        merged.update(self.config.get("games", {}))
        return merged

    def warm_up(self) -> None:
        """Scan Start Menu/Steam ahead of time so the first "buka X" is not slowed by disk I/O."""
        self._apps_discovered()
        self._games_discovered()

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
        expanded = os.path.expandvars(target)
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
                    if alias and alias not in shortcuts:
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
