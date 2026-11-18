"""Tray entry point (run_background.bat, startup shortcut, PyInstaller target)."""

from __future__ import annotations

from mika.ui.tray import TrayVoiceAssistant, main

__all__ = ["TrayVoiceAssistant", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
