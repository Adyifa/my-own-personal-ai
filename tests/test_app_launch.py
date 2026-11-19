"""Opening apps by voice: Microsoft Store apps, Indonesian synonyms, and "buka spotify"."""

from __future__ import annotations

import subprocess

import pytest

from mika.brain.router import Router
from mika.skills.launcher import scan_start_apps
from mika.text import clean_conversational_command
from tests.fakes import FakeSpeaker, RecordingLauncher, ScriptedLLM
from tests.test_assistant import make

WHATSAPP = "shell:AppsFolder\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"
SPOTIFY = "shell:AppsFolder\\SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"
SETTINGS = "shell:AppsFolder\\windows.immersivecontrolpanel_cw5n1h2txyewy!microsoft.windows.immersivecontrolpanel"
STORE_APPS = {
    "whatsapp": WHATSAPP,
    "spotify": SPOTIFY,
    "settings": SETTINGS,
    "visual studio code": "shell:AppsFolder\\{6D809377-6AF0-444B-8957-A3773F02200E}\\Microsoft VS Code\\Code.exe",
    "notepad": "shell:AppsFolder\\Microsoft.WindowsNotepad_8wekyb3d8bbwe!App",
}


@pytest.fixture
def store_config(config):
    """Discovery on, but only the (faked) Store scan: never the real Start Menu, Desktop, or Steam."""
    config["auto_discovery"] = {
        "enabled": True,
        "scan_start_menu": False,
        "scan_desktop": False,
        "scan_steam": False,
        "scan_store_apps": True,
    }
    return config


@pytest.fixture
def store_launcher(store_config):
    return RecordingLauncher(store_config, store_apps=STORE_APPS)


def route_of(config, launcher, utterance):
    return Router(config, launcher).route(clean_conversational_command(utterance))


# Get-StartApps parsing ------------------------------------------------------------------


def test_scan_start_apps_turns_names_into_shell_targets():
    output = (
        '[{"Name":"WhatsApp","AppID":"5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"},'
        '{"Name":"Spotify","AppID":"SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"},'
        '{"Name":"","AppID":"no-name"},{"Name":"No id"},"junk"]'
    )
    assert scan_start_apps(lambda: output) == {"whatsapp": WHATSAPP, "spotify": SPOTIFY}


def test_scan_start_apps_handles_a_single_app_and_a_bom():
    output = '\ufeff{"Name":"Settings","AppID":"windows.immersivecontrolpanel_cw5n1h2txyewy!microsoft.windows.immersivecontrolpanel"}'
    assert scan_start_apps(lambda: output) == {"settings": SETTINGS}


@pytest.mark.parametrize("output", ["", "not json", "null", "42"])
def test_scan_start_apps_bad_output_means_no_apps(output):
    assert scan_start_apps(lambda: output) == {}


def test_scan_start_apps_survives_powershell_failures():
    def timeout():
        raise subprocess.TimeoutExpired("powershell", 20)

    def missing():
        raise FileNotFoundError("powershell")

    assert scan_start_apps(timeout) == {}
    assert scan_start_apps(missing) == {}


# Catalog --------------------------------------------------------------------------------


def test_store_apps_join_the_catalog_and_are_scanned_once(store_launcher):
    apps = store_launcher.apps()
    assert apps["whatsapp"] == WHATSAPP
    store_launcher.apps()
    store_launcher.warm_up()
    assert store_launcher.store_scans == 1


def test_user_aliases_win_over_store_apps(store_config):
    store_config["apps"]["notepad"] = "notepad.exe"
    launcher = RecordingLauncher(store_config, store_apps=STORE_APPS)
    assert launcher.apps()["notepad"] == "notepad.exe"


def test_store_scan_can_be_switched_off(store_config):
    store_config["auto_discovery"]["scan_store_apps"] = False
    launcher = RecordingLauncher(store_config, store_apps=STORE_APPS)
    assert "whatsapp" not in launcher.apps()
    assert launcher.store_scans == 0


def test_synonyms_point_at_installed_apps_only(store_launcher):
    apps = store_launcher.apps()
    assert apps["pengaturan"] == apps["setelan"] == SETTINGS
    assert apps["wa"] == WHATSAPP
    assert apps["vs code"] == apps["visual studio code"]
    assert "kamera" not in apps  # Camera was not found, so "kamera" must not open anything


def test_a_synonym_never_replaces_the_users_own_alias(store_config):
    store_config["apps"]["wa"] = "C:/Tools/wa-launcher.exe"
    launcher = RecordingLauncher(store_config, store_apps=STORE_APPS)
    assert launcher.apps()["wa"] == "C:/Tools/wa-launcher.exe"


def test_shell_targets_open_through_shell_execute(store_launcher):
    store_launcher.launch(WHATSAPP)
    assert store_launcher.started_files == [WHATSAPP]
    assert store_launcher.commands == [] and store_launcher.opened_urls == []


def test_agent_lookup_finds_store_apps_and_synonyms(store_launcher):
    assert store_launcher.resolve("WhatsApp").target == WHATSAPP
    assert store_launcher.resolve("pengaturan").target == SETTINGS


# Routing --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("utterance", "name", "target"),
    [
        ("buka whatsapp", "whatsapp", WHATSAPP),
        ("tolong bukain wa dong", "wa", WHATSAPP),
        ("buka pengaturan", "pengaturan", SETTINGS),
        ("buka aplikasi spotify", "spotify", SPOTIFY),
        ("buka spotify", "spotify", SPOTIFY),
        ("jalankan spotify", "spotify", SPOTIFY),
        ("putar spotify", "spotify", SPOTIFY),
        ("spotify", "spotify", SPOTIFY),
    ],
)
def test_open_app_routes(store_config, store_launcher, utterance, name, target):
    route = route_of(store_config, store_launcher, utterance)
    assert (route.path, route.intent, route.args) == ("rule", "open_app", {"name": name, "target": target})


def test_vs_code_abbreviation(store_config, store_launcher):
    route = route_of(store_config, store_launcher, "buka vs code")
    assert (route.intent, route.args["name"]) == ("open_app", "vs code")


def test_songs_on_spotify_are_still_a_music_search(store_config, store_launcher):
    route = route_of(store_config, store_launcher, "putar lagu santai di spotify")
    assert (route.intent, route.args) == ("music", {"query": "santai"})


def test_buka_spotify_without_the_app_opens_the_web_player(config, launcher):
    route = route_of(config, launcher, "buka spotify")
    assert (route.intent, route.args["url"]) == ("open_website", "https://open.spotify.com")


def test_buka_youtube_never_waits_for_app_discovery(store_config, store_launcher):
    assert route_of(store_config, store_launcher, "buka youtube").intent == "open_website"
    assert store_launcher.store_scans == 0


# End to end -----------------------------------------------------------------------------


def test_buka_whatsapp_opens_the_store_app_without_the_llm(store_config, store_launcher):
    speaker, llm = FakeSpeaker(), ScriptedLLM()
    assistant = make(store_config, speaker, store_launcher, llm)
    assistant.handle("halo mika bukain whatsapp dong")
    assert store_launcher.started_files == [WHATSAPP]
    assert speaker.said == ["Oke, Mika bukain whatsapp ya."]
    assert llm.calls == []
