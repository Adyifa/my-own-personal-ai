"""Tray entry point (run_background.bat, startup shortcut, PyInstaller target)."""

from __future__ import annotations

from mika.ui.tray import TrayVoiceAssistant, main

__all__ = ["TrayVoiceAssistant", "main"]


if __name__ == "__main__":
    import sys

    if "--admin-clean" in sys.argv:  # the EXE started as the cache-cleanup helper through the UAC prompt
        from mika.skills.disk import admin_clean_main

        raise SystemExit(admin_clean_main(sys.argv[1:]))
    raise SystemExit(main())
