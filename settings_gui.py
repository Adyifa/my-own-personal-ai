"""Settings window entry point (run_settings.bat)."""

from __future__ import annotations

from mika.ui.settings import SettingsWindow, main, open_settings_window

__all__ = ["SettingsWindow", "main", "open_settings_window"]


if __name__ == "__main__":
    raise SystemExit(main())
