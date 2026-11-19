from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from mika.config import DEFAULT_CONFIG, apply_personality_preset
from tests.fakes import FakeSpeaker, RecordingLauncher, make_everyday

WIB = timezone(timedelta(hours=7))
NOW = datetime(2026, 11, 19, 10, 0, tzinfo=WIB)  # a Thursday, 10:00 WIB


@pytest.fixture
def config(tmp_path) -> dict[str, Any]:
    cfg = apply_personality_preset(copy.deepcopy(DEFAULT_CONFIG))
    cfg["data_dir"] = str(tmp_path / "data")  # never touch the real reminders or notes
    cfg["reminders"]["chime"] = False
    cfg["auto_discovery"]["enabled"] = False  # never scan the real Start Menu in tests
    cfg["voice"]["enabled"] = False
    cfg["files"] = {"downloads": str(tmp_path)}
    cfg["search_folders"] = [str(tmp_path)]
    cfg["web_search"]["providers"] = []
    # Single-choice templates so assertions are deterministic.
    cfg["personality"]["open_reply"] = "Oke, Mika bukain {target} ya."
    cfg["personality"]["open_website_reply"] = "Oke, Mika bukain website {target} ya."
    cfg["personality"]["search_reply"] = "Mika cari {query} di {provider}."
    cfg["personality"]["music_reply"] = "Mika cariin {query} di Spotify."
    return cfg


@pytest.fixture
def speaker() -> FakeSpeaker:
    return FakeSpeaker()


@pytest.fixture
def launcher(config) -> RecordingLauncher:
    return RecordingLauncher(config)


@pytest.fixture
def everyday(config, tmp_path):
    """Skill hub on a fake clock (Thursday 19 Nov 2026, 10:00 WIB) with fake media, volume, battery, weather."""
    return make_everyday(config, tmp_path, NOW)
