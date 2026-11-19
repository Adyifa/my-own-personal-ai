"""Battery and resource usage via psutil."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


class SystemInfo:
    """Reads battery, CPU, RAM, and disk; psutil is injectable for tests."""

    def __init__(self, psutil_module: Any = None, disk_root: str | None = None):
        self._psutil = psutil_module
        self.disk_root = disk_root or str(Path.home().anchor or "C:\\")

    def _ps(self) -> Any:
        """psutil, imported lazily so a missing package only disables this skill."""
        if self._psutil is None:
            import psutil

            self._psutil = psutil
        return self._psutil

    def battery(self) -> dict[str, Any] | None:
        """{"percent", "plugged", "minutes_left"} or None on a desktop without a battery."""
        battery = self._ps().sensors_battery()
        if battery is None:
            return None
        seconds = battery.secsleft if isinstance(battery.secsleft, (int, float)) else -1
        minutes = int(seconds // 60) if seconds and seconds > 0 else None
        return {"percent": int(round(battery.percent)), "plugged": bool(battery.power_plugged), "minutes_left": minutes}

    def usage(self) -> dict[str, Any]:
        """CPU and RAM percent, plus free and total disk space in GB."""
        ps = self._ps()
        disk = shutil.disk_usage(self.disk_root)
        return {
            "cpu_percent": round(ps.cpu_percent(interval=0.3)),
            "ram_percent": round(ps.virtual_memory().percent),
            "disk_free_gb": round(disk.free / 1024**3),
            "disk_total_gb": round(disk.total / 1024**3),
            "disk": self.disk_root,
        }
