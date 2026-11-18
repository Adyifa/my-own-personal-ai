"""Power actions. Never called directly from a voice command: always behind a confirmation."""

from __future__ import annotations

import subprocess

POWER_LABELS = {
    "shutdown": "laptop akan dimatikan",
    "restart": "laptop akan direstart",
    "sleep": "laptop masuk mode sleep",
    "lock": "laptop akan dikunci",
    "logout": "akun Windows akan logout",
}


def execute_power_action(action: str) -> None:
    if action == "shutdown":
        subprocess.Popen(["shutdown", "/s", "/t", "0"])
    elif action == "restart":
        subprocess.Popen(["shutdown", "/r", "/t", "0"])
    elif action == "logout":
        subprocess.Popen(["shutdown", "/l"])
    elif action == "lock":
        subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
    elif action == "sleep":
        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Add-Type -AssemblyName System.Windows.Forms; "
                "[System.Windows.Forms.Application]::SetSuspendState('Suspend',$false,$false)",
            ]
        )
    else:
        raise ValueError(f"Aksi power tidak dikenal: {action}")
