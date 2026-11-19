"""Disk check ("kenapa disk C-ku penuh?") and a cleanup that may only empty a fixed list of cache folders.

Why it is built this way:
- Folder paths live in this file only. They never come from the user's words, the LLM, or a web page.
- The LLM gets a read-only report. Deleting is a fixed voice command that waits for a spoken "iya".
- Links (junctions, symlinks) inside a cache are removed as links and never followed, and a cache folder that is
  itself reached through a link is refused, so nothing outside the listed folders can be touched.
- Folders that need admin rights are emptied by a separate helper started through the normal Windows UAC prompt.
  Mika itself never runs as admin.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT: junctions, symlinks, OneDrive placeholders
_DIRECTORY = 0x10  # FILE_ATTRIBUTE_DIRECTORY

CATEGORY_LABELS = {
    "nvidia": "cache shader NVIDIA",
    "directx": "cache shader DirectX",
    "temp": "file sementara",
    "npm": "cache npm",
    "pip": "cache pip",
    "crash": "crash dump",
    "windows_update": "unduhan lama Windows Update",
}
CATEGORY_NOTES = {
    "nvidia": "Game akan sedikit lebih lama loading sekali, lalu cache-nya dibuat ulang.",
    "directx": "Game akan sedikit lebih lama loading sekali, lalu cache-nya dibuat ulang.",
    "npm": "Paket npm dan pip diunduh ulang saat dibutuhkan.",
    "pip": "Paket npm dan pip diunduh ulang saat dibutuhkan.",
}
ALL_CATEGORIES = tuple(CATEGORY_LABELS)


@dataclass(frozen=True)
class CacheFolder:
    """One folder whose contents may be deleted. `base` is the trusted root it hangs from."""

    category: str
    base: Path
    relative: tuple[str, ...]
    admin: bool = False

    @property
    def path(self) -> Path:
        return self.base.joinpath(*self.relative)


@dataclass
class Measured:
    """Size of a folder; `complete` is False when the time budget ran out (the size is then a minimum)."""

    bytes: int = 0
    files: int = 0
    complete: bool = True
    denied: bool = False


@dataclass
class ReportItem:
    """One line of the disk report."""

    label: str
    size: Measured
    kind: str  # "cache" (Mika can clean it) | "user" | "system" | "apps" | "models" | "folder"
    category: str = ""
    path: str = ""


@dataclass
class DiskReport:
    """Free space plus measured items, biggest first."""

    drive: str
    total: int
    free: int
    items: list[ReportItem] = field(default_factory=list)
    deep: bool = False
    stopped: bool = False

    @property
    def cleanable(self) -> list[ReportItem]:
        return [item for item in self.items if item.kind == "cache" and item.size.bytes > 0]

    @property
    def cleanable_total(self) -> int:
        return sum(item.size.bytes for item in self.cleanable)

    def as_data(self) -> dict[str, Any]:
        """Compact JSON for the LLM: sizes in GB and how cleaning works (the AI itself cannot delete)."""
        return {
            "drive": self.drive,
            "free_gb": _gb(self.free),
            "total_gb": _gb(self.total),
            "bisa_dibersihkan": [{"nama": item.label, "gb": _gb(item.size.bytes)} for item in self.cleanable],
            "lainnya": [
                {"nama": item.label, "gb": _gb(item.size.bytes), "jenis": item.kind}
                for item in self.items if item.kind != "cache"
            ][:12],
            "cara_membersihkan": "Pengguna bilang 'hapus cache' atau misalnya 'hapus cache nvidia'. AI tidak bisa menghapus file.",
        }


@dataclass
class CleanupPlan:
    """What a cleanup would delete, measured before asking for confirmation."""

    items: list[tuple[CacheFolder, Measured]]
    admin_allowed: bool = True

    @property
    def user_items(self) -> list[tuple[CacheFolder, Measured]]:
        return [(folder, size) for folder, size in self.items if not folder.admin]

    @property
    def admin_items(self) -> list[tuple[CacheFolder, Measured]]:
        return [(folder, size) for folder, size in self.items if folder.admin and self.admin_allowed]

    @property
    def total(self) -> int:
        return sum(size.bytes for _, size in [*self.user_items, *self.admin_items])

    @property
    def categories(self) -> list[str]:
        seen = {folder.category for folder, _ in [*self.user_items, *self.admin_items]}
        return [category for category in ALL_CATEGORIES if category in seen]


@dataclass
class CleanupResult:
    freed: int = 0
    skipped: int = 0
    admin: str = "none"  # "none" | "done" | "declined" | "failed" | "timeout"


class UnsafeTarget(Exception):
    """A cache folder that is reached through a link, or is not a folder: refused, nothing is deleted."""


# Fixed folder list --------------------------------------------------------------------------


def _ends_with(value: str | None, *tail: str) -> Path | None:
    """Trust an environment path only if it ends the expected way ("...\\AppData\\Local"), so a tampered value
    such as "C:\\" can never turn "Temp" into "C:\\Temp"."""
    if not value:
        return None
    path = Path(value)
    parts = [part.lower() for part in path.parts]
    return path if len(parts) > len(tail) and parts[-len(tail):] == [part.lower() for part in tail] else None


def cache_folders(env: Mapping[str, str] | None = None) -> list[CacheFolder]:
    """Every folder Mika may empty. Anything not listed here is never deleted."""
    env = os.environ if env is None else env
    local = _ends_with(env.get("LOCALAPPDATA"), "AppData", "Local")
    program_data = _ends_with(env.get("PROGRAMDATA"), "ProgramData")
    windows = _ends_with(env.get("SystemRoot") or env.get("SYSTEMROOT"), "Windows")
    folders: list[CacheFolder] = []
    if local is not None:
        folders += [
            CacheFolder("nvidia", local, ("NVIDIA", "DXCache")),
            CacheFolder("nvidia", local, ("NVIDIA", "GLCache")),
            CacheFolder("directx", local, ("D3DSCache",)),
            CacheFolder("temp", local, ("Temp",)),
            CacheFolder("npm", local, ("npm-cache",)),
            CacheFolder("pip", local, ("pip", "cache")),
            CacheFolder("crash", local, ("CrashDumps",)),
        ]
    if program_data is not None:
        folders.append(CacheFolder("nvidia", program_data, ("NVIDIA Corporation", "NV_Cache"), admin=True))
    if windows is not None:
        folders += [
            CacheFolder("temp", windows, ("Temp",), admin=True),
            CacheFolder("windows_update", windows, ("SoftwareDistribution", "Download"), admin=True),
        ]
    return folders


# Measuring (read-only) ------------------------------------------------------------------------


def _is_link(info: os.stat_result) -> bool:
    return bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT) or stat.S_ISLNK(info.st_mode)


def measure(path: Path, *, budget: float = 5.0, should_stop: Callable[[], bool] | None = None) -> Measured:
    """Bytes and files under `path`, never following links (AppData has junction loops). Stops at the budget."""
    result = Measured()
    deadline = time.monotonic() + budget
    stack = [path]
    while stack:
        if time.monotonic() > deadline or (should_stop is not None and should_stop()):
            result.complete = False
            return result
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        result.denied = True
                        continue
                    if _is_link(info):
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        stack.append(Path(entry.path))
                    else:
                        result.bytes += info.st_size
                        result.files += 1
        except OSError:
            result.denied = True
    return result


def _file_size(path: Path) -> Measured:
    try:
        return Measured(bytes=os.stat(path).st_size, files=1)
    except OSError:
        return Measured(complete=False)


# Deleting (only inside a listed folder) -------------------------------------------------------


def _check_no_links(folder: CacheFolder) -> None:
    """Refuse when the folder, or any folder between the trusted base and it, is a link."""
    current = folder.base
    for part in folder.relative:
        current = current / part
        info = os.lstat(current)
        if _is_link(info):
            raise UnsafeTarget(f"{current} adalah link")
        if not stat.S_ISDIR(info.st_mode):
            raise UnsafeTarget(f"{current} bukan folder")


def empty_folder(folder: CacheFolder) -> tuple[int, int]:
    """Delete everything inside a listed folder (the folder itself stays). Returns (bytes freed, items skipped).
    Files in use or read-only are skipped, not forced."""
    if not folder.path.exists():
        return 0, 0
    _check_no_links(folder)
    return _empty(folder.path)


def _empty(directory: Path) -> tuple[int, int]:
    freed = skipped = 0
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return 0, 1
    for entry in entries:
        try:
            info = entry.stat(follow_symlinks=False)
            if _is_link(info):
                # Remove the link itself; its target (possibly outside the cache) is never entered.
                if getattr(info, "st_file_attributes", 0) & _DIRECTORY or stat.S_ISDIR(info.st_mode):
                    os.rmdir(entry.path)
                else:
                    os.unlink(entry.path)
            elif stat.S_ISDIR(info.st_mode):
                sub_freed, sub_skipped = _empty(Path(entry.path))
                freed += sub_freed
                skipped += sub_skipped
                if not sub_skipped:
                    os.rmdir(entry.path)
            else:
                os.unlink(entry.path)
                freed += info.st_size
        except OSError:
            skipped += 1  # in use (a running game holds its shader cache), read-only, or access denied
    return freed, skipped


# Elevated helper (admin folders) --------------------------------------------------------------


def admin_clean_main(argv: list[str] | None = None) -> int:
    """Entry point of the helper that runs as admin: empties only the listed admin folders of the named categories.
    It takes category names, never paths, so even a hijacked call cannot point it anywhere else."""
    parser = argparse.ArgumentParser(prog="mika-admin-clean")
    parser.add_argument("--admin-clean", required=True)
    parser.add_argument("--result", required=True)
    args, _ = parser.parse_known_args(argv)
    result = Path(args.result)
    if result.suffix != ".json" or not result.name.startswith("mika-admin-clean-") or result.exists():
        return 2  # checked before deleting anything; the report file is the only thing written outside the caches
    wanted = {category for category in args.admin_clean.split(",") if category in CATEGORY_LABELS}
    freed = skipped = 0
    for folder in cache_folders():
        if folder.admin and folder.category in wanted:
            try:
                folder_freed, folder_skipped = empty_folder(folder)
            except (UnsafeTarget, OSError):
                folder_freed, folder_skipped = 0, 1
            freed += folder_freed
            skipped += folder_skipped
    try:
        with result.open("x", encoding="utf-8") as handle:  # "x": never overwrite an existing file as admin
            json.dump({"freed": freed, "skipped": skipped}, handle)
    except OSError:
        return 1
    return 0


def _helper_command() -> tuple[str, str, str]:
    """(program, parameters, working folder) that starts admin_clean_main from source or from the EXE."""
    if getattr(sys, "frozen", False):
        return sys.executable, "", str(Path(sys.executable).parent)
    windowless = Path(sys.executable).with_name("pythonw.exe")
    program = str(windowless if windowless.exists() else Path(sys.executable))
    return program, "-m mika.skills.disk", str(Path(__file__).resolve().parents[2])


def run_elevated(categories: Iterable[str], result_dir: Path, *, timeout: float = 120.0,
                 verb: str = "runas") -> tuple[str, int, int]:
    """Start the helper through the UAC prompt and wait. Returns (status, freed, skipped);
    "declined" when the user clicks No."""
    result_dir.mkdir(parents=True, exist_ok=True)
    result = result_dir / f"mika-admin-clean-{os.getpid()}-{int(time.time() * 1000)}.json"
    program, prefix, directory = _helper_command()
    parameters = f'{prefix} --admin-clean {",".join(categories)} --result "{result}"'.strip()
    status = shell_execute_and_wait(program, parameters, directory, timeout=timeout, verb=verb)
    freed = skipped = 0
    if status == "done":
        try:
            data = json.loads(result.read_text(encoding="utf-8"))
            freed, skipped = int(data.get("freed", 0)), int(data.get("skipped", 0))
        except (OSError, ValueError):
            status = "failed"
    try:
        result.unlink()
    except OSError:
        pass
    return status, freed, skipped


def shell_execute_and_wait(program: str, parameters: str, directory: str, *, timeout: float, verb: str = "runas") -> str:
    """ShellExecuteEx with a process handle, so Mika knows whether UAC was declined and when the helper is done."""
    import ctypes
    from ctypes import wintypes

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
        ]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(ShellExecuteInfo)
    # NOCLOSEPROCESS | NOASYNC | FLAG_NO_UI: no error dialogs (they would also make a missing file look like
    # a UAC "No"); the UAC prompt itself is not error UI and still appears.
    info.fMask = 0x00000040 | 0x00000100 | 0x00000400
    info.lpVerb, info.lpFile, info.lpParameters, info.lpDirectory = verb, program, parameters, directory
    info.nShow = 0  # SW_HIDE
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        return "declined" if ctypes.get_last_error() == 1223 else "failed"  # 1223: ERROR_CANCELLED (UAC "No")
    if not info.hProcess:
        return "failed"
    try:
        if kernel32.WaitForSingleObject(info.hProcess, int(timeout * 1000)) != 0:  # 0: WAIT_OBJECT_0
            return "timeout"
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return "done" if code.value == 0 else "failed"
    finally:
        kernel32.CloseHandle(info.hProcess)


# The skill -------------------------------------------------------------------------------------


class DiskCare:
    """Quick and deep disk reports, cleanup plans, and the cleanup itself. Every OS dependency is injectable."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        env: Mapping[str, str] | None = None,
        home: Path | None = None,
        disk_usage: Callable[[str], Any] = shutil.disk_usage,
        elevate: Callable[[list[str]], tuple[str, int, int]] | None = None,
        data_dir: Path | None = None,
    ):
        disk = config.get("disk", {})
        self.drive = str(disk.get("drive", "C:\\"))
        self.quick_seconds = float(disk.get("quick_seconds", 4))
        self.deep_seconds = float(disk.get("deep_seconds", 60))
        self.admin_cleanup = bool(disk.get("admin_cleanup", True))
        self.env = os.environ if env is None else env
        self.home = home or Path(self.env.get("USERPROFILE") or Path.home())
        self.disk_usage = disk_usage
        if data_dir is None:
            from ..config import DATA_DIR

            data_dir = Path(config.get("data_dir") or DATA_DIR)
        self.data_dir = data_dir
        self._elevate = elevate or (lambda categories: run_elevated(categories, self.data_dir))

    # Reports ----------------------------------------------------------------------------

    def quick_report(self, should_stop: Callable[[], bool] | None = None) -> DiskReport:
        """Caches Mika can clean plus the usual big items, in parallel within a few seconds."""
        targets = self._cache_targets(should_stop, budget=self.quick_seconds)
        for name in ("Downloads", "Documents", "Pictures", "Videos", "Desktop", "Music"):
            targets.append((name, "user", "", self._folder(self.home / name, should_stop)))
        targets.append(("model AI Whisper", "models", "", self._folder(self.home / ".cache" / "huggingface", should_stop)))
        targets.append(("model AI Ollama", "models", "", self._folder(self.home / ".ollama", should_stop)))
        root = Path(self.drive)
        for name in ("pagefile.sys", "hiberfil.sys", "swapfile.sys"):
            targets.append((name, "system", "", lambda path=root / name: _file_size(path)))
        targets.append(("Windows.old (sisa Windows lama)", "system", "", self._folder(root / "Windows.old", should_stop)))
        return self._report(targets, deep=False, should_stop=should_stop)

    def deep_report(self, should_stop: Callable[[], bool] | None = None) -> DiskReport:
        """Every top-level folder of the drive and of the user profile (about a minute on a full laptop),
        plus the cleanable caches as in the quick report."""
        root = Path(self.drive)
        skip_top = {"users", "$recycle.bin", "system volume information"}
        folders = [path for path in _subfolders(root) if path.name.lower() not in skip_top]
        folders += [path for path in _subfolders(self.home) if path.name.lower() != "appdata"]
        folders += [path for path in _subfolders(self.home / "AppData") if path.name.lower() != "local"]
        folders += _subfolders(self.home / "AppData" / "Local")
        cache_paths = {str(folder.path).lower() for folder in cache_folders(self.env)}
        cache_sizes: dict[str, int] = {}
        targets = self._cache_targets(should_stop, budget=self.deep_seconds, sizes=cache_sizes)
        for path in folders:
            if str(path).lower() in cache_paths:
                continue  # already counted as a cleanable cache
            targets.append((_spoken_name(path, root, self.home), _kind_of(path, root, self.home), str(path),
                            self._folder(path, should_stop, budget=self.deep_seconds)))
        report = self._report(targets, deep=True, should_stop=should_stop)
        for item in report.items:
            # "AppData NVIDIA 9 GB" is nearly all shader cache: say so instead of filing it under "not deleted".
            inside = sum(size for path, size in cache_sizes.items() if item.path and _is_inside(path, item.path))
            if item.kind != "cache" and item.size.bytes and inside * 2 >= item.size.bytes:
                item.kind = "mostly_cache"
        return report

    def _cache_targets(self, should_stop, *, budget: float, sizes: dict[str, int] | None = None) -> list:
        folders = cache_folders(self.env)
        return [
            (CATEGORY_LABELS[category], "cache", category,
             self._summed([folder.path for folder in folders if folder.category == category], should_stop, budget, sizes))
            for category in ALL_CATEGORIES
        ]

    def _folder(self, path: Path, should_stop, budget: float | None = None) -> Callable[[], Measured]:
        def run() -> Measured:
            return measure(path, budget=budget or self.quick_seconds, should_stop=should_stop) if path.exists() else Measured()
        return run

    def _summed(self, paths: list[Path], should_stop, budget: float, sizes: dict[str, int] | None = None) -> Callable[[], Measured]:
        def run() -> Measured:
            total = Measured()
            for path in paths:
                if path.exists():
                    part = measure(path, budget=budget, should_stop=should_stop)
                    if sizes is not None:
                        sizes[str(path)] = part.bytes
                    total.bytes += part.bytes
                    total.files += part.files
                    total.complete &= part.complete
                    total.denied |= part.denied
            return total
        return run

    def _report(self, targets, *, deep: bool, should_stop) -> DiskReport:
        usage = self.disk_usage(self.drive)
        # One thread per folder: each stops at its own deadline, so the wall time stays near the budget.
        with ThreadPoolExecutor(max_workers=min(32, max(1, len(targets)))) as pool:
            sizes = list(pool.map(lambda target: target[3](), targets))
        items = [
            ReportItem(label, size, kind, extra if kind == "cache" else "", "" if kind == "cache" else extra)
            for (label, kind, extra, _), size in zip(targets, sizes)
            if size.bytes > 0
        ]
        items.sort(key=lambda item: item.size.bytes, reverse=True)
        stopped = bool(should_stop and should_stop())
        return DiskReport(_drive_name(self.drive), int(usage.total), int(usage.free), items, deep=deep, stopped=stopped)

    # Cleanup ----------------------------------------------------------------------------

    def plan_cleanup(self, categories: Iterable[str] | None = None) -> CleanupPlan:
        """Measure what would be deleted, so the confirmation question can say how much."""
        wanted = set(categories or ALL_CATEGORIES)
        items = []
        for folder in cache_folders(self.env):
            if folder.category in wanted and folder.path.exists():
                size = measure(folder.path, budget=self.quick_seconds)
                if size.bytes > 0:
                    items.append((folder, size))
        return CleanupPlan(items, admin_allowed=self.admin_cleanup)

    def clean(self, plan: CleanupPlan) -> CleanupResult:
        """Empty the user's own cache folders, then the admin ones through one UAC prompt."""
        result = CleanupResult()
        for folder, _ in plan.user_items:
            try:
                freed, skipped = empty_folder(folder)
            except (UnsafeTarget, OSError):
                freed, skipped = 0, 1
            result.freed += freed
            result.skipped += skipped
        admin_categories = sorted({folder.category for folder, _ in plan.admin_items})
        if admin_categories:
            status, freed, skipped = self._elevate(admin_categories)
            result.admin = status
            result.freed += freed
            result.skipped += skipped
        return result

    def free_space(self) -> int:
        return int(self.disk_usage(self.drive).free)

    @property
    def drive_name(self) -> str:
        return _drive_name(self.drive)


# Speech and screen text -------------------------------------------------------------------------


def speak_size(size: int) -> str:
    """Rounded for the voice: "9 GB", "1,5 GB", "160 MB"."""
    gib = size / 1024**3
    if gib >= 10:
        return f"{gib:.0f} GB"
    if gib >= 1:
        text = f"{gib:.1f}".replace(".", ",")
        return f"{text[:-2] if text.endswith(',0') else text} GB"
    mib = size / 1024**2
    return f"{mib:.0f} MB" if mib >= 1 else "kurang dari 1 MB"


def _precise(size: Measured) -> str:
    """Screen sizes: "  9,03 GB", " 160 MB"; "≥" when the time budget ran out before the folder was fully counted."""
    gib = size.bytes / 1024**3
    text = f"{gib:6.2f} GB".replace(".", ",") if gib >= 1 else f"{size.bytes / 1024**2:6.0f} MB"
    return text if size.complete else f"≥{text.strip()}"


def report_text(report: DiskReport) -> tuple[str, str]:
    """(spoken summary, screen detail) for a disk report."""
    spoken = [f"Disk {report.drive} tinggal {speak_size(report.free)} dari {speak_size(report.total)}."]
    cleanable = report.cleanable
    if report.deep:
        top = [item for item in report.items if item.kind not in ("cache", "mostly_cache")][:3]
        if top:
            spoken.append("Yang paling besar: " + _join([f"{item.label} {speak_size(item.size.bytes)}" for item in top]) + ".")
    if report.cleanable_total >= 100 * 1024**2:
        names = _join([f"{item.label} {speak_size(item.size.bytes)}" for item in cleanable[:2]])
        if report.deep:
            spoken.append(f"Cache yang bisa Mika bersihkan total {speak_size(report.cleanable_total)}, bilang hapus cache kalau mau.")
        else:
            spoken.append(f"Yang bisa Mika bersihkan: {names}, total {speak_size(report.cleanable_total)}.")
            spoken.append("Bilang hapus cache kalau mau Mika bersihkan.")
    elif not report.deep:
        spoken.append("Cache-nya kecil, jadi yang makan tempat kebanyakan file sistem, aplikasi, dan file kamu.")

    lines = [f"Disk {report.drive}: {speak_size(report.free)} kosong dari {speak_size(report.total)}", ""]
    visible = [item for item in report.items if item.size.bytes >= 1024**2]  # below 1 MB is noise on screen
    shown_caches = [item for item in visible if item.kind == "cache"]
    if shown_caches:
        lines.append('Bisa dibersihkan Mika (bilang "hapus cache" atau "hapus cache nvidia"):')
        lines += [f"  {_precise(item.size)}  {item.label}" for item in shown_caches]
        lines.append("")
    others = [item for item in visible if item.kind != "cache"]
    if others:
        lines.append("Lainnya, tidak dihapus Mika:")
        kinds = {"user": "file kamu", "system": "sistem, diatur Windows", "apps": "aplikasi", "models": "model AI Mika",
                 "mostly_cache": "isinya cache di atas", "folder": ""}
        for item in others[: 15 if report.deep else 10]:
            kind = kinds.get(item.kind, "")
            where = f"  {item.path}" if report.deep and item.path else ""
            lines.append(f"  {_precise(item.size)}  {item.label}" + (f" ({kind})" if kind else "") + where)
    if not report.deep:
        lines += ["", 'Bilang "cek detail disk" untuk mengukur semua folder (paling lama satu menit).']
    if report.stopped:
        lines += ["", "Scan dihentikan, jadi sebagian ukuran belum lengkap."]
    return " ".join(spoken), "\n".join(lines)


def cleanup_question(plan: CleanupPlan) -> str:
    """The confirmation question: what, how much, and that it is permanent."""
    categories = plan.categories
    if len(categories) > 3:  # a long list is hard to follow by ear; the screen shows the breakdown
        what = f"semua cache yang aman dihapus ({len(categories)} jenis, rinciannya di layar)"
    else:
        what = _join([CATEGORY_LABELS[category] for category in categories])
    question = f"Mika mau hapus permanen {what}, total {speak_size(plan.total)}."
    if plan.admin_items:
        question += " Sebagian butuh izin admin, nanti muncul jendela izin Windows."
    notes = [CATEGORY_NOTES[category] for category in categories if category in CATEGORY_NOTES]
    if notes:
        question += " " + notes[0]  # one note is enough to hear; games matter most, so NVIDIA/DirectX come first
    return question + " Bilang iya untuk lanjut, atau batal."


def cleanup_detail(plan: CleanupPlan) -> str:
    """Screen breakdown shown while Mika asks for confirmation."""
    lines = ["Yang akan dihapus permanen:"]
    for folder, size in [*plan.user_items, *plan.admin_items]:
        admin = "  (butuh izin admin)" if folder.admin else ""
        lines.append(f"  {_precise(size)}  {CATEGORY_LABELS[folder.category]}: {folder.path}{admin}")
    lines += ["", "Tidak disentuh: Downloads, Documents, game, aplikasi, dan file sistem."]
    return "\n".join(lines)


def cleanup_summary(result: CleanupResult, free_after: int, drive: str) -> str:
    """What happened, in one or two sentences."""
    if result.freed:
        text = f"Beres, {speak_size(result.freed)} lega. Disk {drive} sekarang sisa {speak_size(free_after)}."
    else:
        text = "Nggak ada yang bisa dihapus."
    if result.skipped:
        text += f" {result.skipped} file dilewati karena sedang dipakai atau dilindungi."
    if result.admin == "declined":
        text += " Bagian yang butuh admin dilewati karena izinnya ditolak."
    elif result.admin in ("failed", "timeout"):
        text += " Bagian yang butuh admin gagal dibersihkan."
    return text


def _join(parts: list[str]) -> str:
    """Indonesian list: "a", "a dan b", "a, b, dan c"."""
    if len(parts) <= 1:
        return "".join(parts)
    if len(parts) == 2:
        return f"{parts[0]} dan {parts[1]}"
    return ", ".join(parts[:-1]) + f", dan {parts[-1]}"


def _gb(size: int) -> float:
    return round(size / 1024**3, 2)


def _drive_name(drive: str) -> str:
    """The drive letter as it is said aloud: "C:\\" → "C"."""
    return Path(drive).drive.rstrip(":").upper() or drive


def _subfolders(path: Path) -> list[Path]:
    try:
        with os.scandir(path) as entries:
            return [Path(entry.path) for entry in entries
                    if entry.is_dir(follow_symlinks=False) and not _is_link(entry.stat(follow_symlinks=False))]
    except OSError:
        return []


def _kind_of(path: Path, root: Path, home: Path) -> str:
    name = path.name.lower()
    if path.parent == root and name in {"windows", "programdata", "recovery", "perflogs"}:
        return "system"
    if path.parent == root and name.startswith("program files"):
        return "apps"
    if path.parent == home and name in {"downloads", "documents", "pictures", "videos", "desktop", "music", "onedrive"}:
        return "user"
    return "folder"


def _is_inside(child: str, parent: str) -> bool:
    return child.lower().startswith(parent.lower().rstrip("\\") + "\\")


def _spoken_name(path: Path, root: Path, home: Path) -> str:
    """Folder name as it is said aloud: "Windows", "Documents", "AppData NVIDIA"."""
    if path.parent == home / "AppData" / "Local" or path.parent == home / "AppData":
        return f"AppData {path.name}"
    return path.name


if __name__ == "__main__":  # the elevated helper: python -m mika.skills.disk --admin-clean nvidia,temp --result ...
    sys.exit(admin_clean_main(sys.argv[1:]))
