from __future__ import annotations

import copy
from typing import Any

import pytest

from mika.config import DEFAULT_CONFIG, apply_personality_preset
from tests.fakes import FakeSpeaker, RecordingLauncher


@pytest.fixture
def config(tmp_path) -> dict[str, Any]:
    cfg = apply_personality_preset(copy.deepcopy(DEFAULT_CONFIG))
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
