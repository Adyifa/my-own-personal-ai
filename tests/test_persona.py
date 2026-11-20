"""Stage A: one persona for the whole system, offline curhat, and "X terus Y" sequences."""

from __future__ import annotations

import pytest

from mika.app import build_assistant
from mika.brain.prompts import build_system_prompt
from mika.brain.router import Router
from mika.persona import CONVERSATION_REPLIES, Persona, PersonaSpeaker
from mika.skills.browser import spotify_url
from mika.text import clean_conversational_command
from tests.fakes import FakeSearcher, FakeSpeaker, RecordingLauncher


def make(config, *, store_apps=None, power_calls=None):
    config["llm"]["enabled"] = False  # offline: template replies, the part the persona converter rewrites
    speaker = FakeSpeaker()
    launcher = RecordingLauncher(config, store_apps=store_apps)
    runner = power_calls.append if power_calls is not None else _refuse_power
    assistant = build_assistant(config, speaker=speaker, launcher=launcher, searcher=FakeSearcher(), power_runner=runner)
    return assistant, speaker, launcher


def _refuse_power(action):
    raise AssertionError(f"power action {action} must not run in this test")


def route_of(config, launcher, utterance):
    return Router(config, launcher).route(clean_conversational_command(utterance))


# The persona profile ---------------------------------------------------------------------------------


def test_unknown_settings_fall_back_to_defaults():
    persona = Persona.from_config({"persona": {"register": "alay", "advice": "", "humor": None, "user_name": "  Yasa "}})
    assert persona == Persona(user_name="Yasa", register="santai", advice="tanya_dulu", humor="sedikit")


@pytest.mark.parametrize(
    ("register", "text", "spoken"),
    [
        ("santai", "Aku dengerin. Kamu lagi ngerasa gimana?", "Aku dengerin. Kamu lagi ngerasa gimana?"),
        ("gaul", "Aku dengerin. Kamu lagi ngerasa gimana?", "Gue dengerin. Lo lagi ngerasa gimana?"),
        ("gaul", "Lihat catatanmu kapan aja.", "Lihat catatan lo kapan aja."),
        ("gaul", "Mika belum nemu file itu, belum ketemu juga.", "Mika belum nemu file itu, belum ketemu juga."),
        ("sopan", "Oke, Mika bukain youtube ya.", "Baik, Mika bukakan youtube."),
        ("sopan", "Hehe, sama-sama. Ada yang mau Mika bantu lagi?", "Sama-sama. Ada yang mau Mika bantu lagi?"),
        ("sopan", "Aku dengerin. Kamu lagi ngerasa gimana sekarang?", "Saya mendengarkan. Anda lagi merasa bagaimana sekarang?"),
    ],
)
def test_registers(register, text, spoken):
    assert Persona(register=register).speak(text) == spoken


@pytest.mark.parametrize(
    ("text", "greeted"),
    [
        ("Halo, Mika di sini.", "Halo Yasa, Mika di sini."),
        ("Pagi. Semoga harimu enak.", "Pagi, Yasa. Semoga harimu enak."),
        ("Sama-sama. Mika senang kalau kepake.", "Sama-sama, Yasa. Mika senang kalau kepake."),
        ("Mika baik.", "Mika baik."),  # not a greeting: unchanged
    ],
)
def test_greetings_use_the_users_name(text, greeted):
    assert Persona(user_name="Yasa").greet(text) == greeted
    assert Persona().greet(text) == text  # no name set: unchanged


def test_ai_gets_the_same_persona_and_the_human_decides(config):
    config["persona"] = {"user_name": "Yasa", "register": "gaul", "advice": "dengar_saja", "humor": "tidak"}
    prompt = build_system_prompt(config)
    assert "'gue' dan 'lo'" in prompt and "Panggil pengguna 'Yasa'" in prompt and "Jangan bercanda." in prompt
    assert "jangan memberi saran kecuali diminta" in prompt
    assert "biarkan pengguna yang memutuskan" in prompt


def test_persona_speaker_rewrites_and_delegates():
    speaker = FakeSpeaker()
    wrapped = PersonaSpeaker(speaker, Persona(register="gaul"))
    wrapped.say("Aku di sini.")
    wrapped.say_async("Kamu oke?")
    wrapped.stop()
    assert speaker.said == ["Gue di sini.", "Lo oke?"] and speaker.stopped


def test_template_replies_follow_the_persona(config):
    config["persona"] = {"user_name": "Yasa", "register": "gaul"}
    config["personality"]["preset"] = "cute"
    assistant, speaker, _ = make(config)
    assistant.handle("halo")
    assert speaker.said[-1].startswith(("Halo Yasa", "Hai, Yasa", "Halo halo, Yasa"))
    assistant.handle("aku berantem sama pacar semalam")
    assert speaker.said[-1] in {Persona(register="gaul").speak(text) for text in CONVERSATION_REPLIES["cute"]["curhat_love"]}


# Curhat offline ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("utterance", "category"),
    [
        ("aku capek banget sama kerjaan", "curhat_work"),
        ("bos aku marah marah terus hari ini", "curhat_work"),
        ("aku stres mikirin skripsi", "curhat_work"),
        ("pacarku jarang bales chat", "curhat_love"),
        ("orang tuaku nggak setuju sama pacarku", "curhat_love"),
        ("aku berantem sama ibu", "curhat_family"),
        ("temanku ngomongin aku di belakang", "curhat_friend"),
        ("aku ngerasa gagal", "curhat_feeling"),
        ("menurut kamu aku harus gimana", "curhat_advice"),
        ("aku capek nih", "tired"),  # plain tiredness keeps its own template
    ],
)
def test_curhat_categories(config, launcher, utterance, category):
    route = route_of(config, launcher, utterance)
    assert (route.path, route.intent, route.args["category"]) == ("agent", "chat", category)


@pytest.mark.parametrize("utterance", ["apa itu gaji pokok", "jelaskan sejarah keluarga kerajaan inggris"])
def test_questions_about_those_topics_are_not_curhat(config, launcher, utterance):
    assert route_of(config, launcher, utterance).intent == "general"


def test_offline_curhat_listens_and_keeps_the_conversation_open(config):
    assistant, speaker, _ = make(config)
    assistant.handle("aku capek banget sama kerjaan")
    assert speaker.said[-1] in CONVERSATION_REPLIES["cute"]["curhat_work"]
    assert "google" not in speaker.text.lower()
    assert assistant.conversation_is_active()


# Sequences --------------------------------------------------------------------------------------------------


def test_sequence_runs_each_step_in_order(config):
    config["apps"].update({"discord": "discord.exe", "steam": "steam.exe"})
    assistant, speaker, launcher = make(config)
    assistant.handle("buka discord terus buka steam")
    assert launcher.commands == ["discord.exe", "steam.exe"]
    assert len(speaker.said) == 2


def test_confirmation_step_comes_last_and_waits(config, everyday):
    power_calls = []
    assistant, speaker, _ = make(config, power_calls=power_calls)
    assistant.hub = everyday.hub
    assistant.handle("matikan suara terus kunci laptop")
    assert everyday.endpoint.muted == 1 and power_calls == []
    assert assistant.pending_action is not None
    assistant.handle("iya")
    assert power_calls == ["lock"]


def test_negated_sequence_does_nothing(config, launcher):
    assert route_of(config, launcher, "jangan buka youtube terus matikan laptop").intent == "never_mind"


def test_open_then_search_on_the_same_service_is_one_step(config):
    config["auto_discovery"] = {"enabled": True, "scan_start_menu": False, "scan_desktop": False, "scan_steam": False,
                                "scan_store_apps": True}  # only the faked Store scan below, never the real Start Menu
    assistant, _, launcher = make(config, store_apps={"spotify": "shell:AppsFolder\\SpotifyAB.SpotifyMusic!Spotify"})
    assistant.handle("buka spotify terus putar lagu tulus")
    assert launcher.opened_urls == ["spotify:search:tulus"]  # straight into the app, no separate "open Spotify" step
    assert launcher.started_files == []


def test_notes_with_terus_stay_one_note(config, launcher):
    route = route_of(config, launcher, "catat besok rapat terus makan siang sama klien")
    assert (route.intent, route.args["text"]) == ("note_add", "catat besok rapat terus makan siang sama klien")


# Spotify opens in the app when it is installed --------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "installed", "url"),
    [
        ("auto", True, "spotify:search:hindia"),
        ("auto", False, "https://open.spotify.com/search/hindia"),
        ("web", True, "https://open.spotify.com/search/hindia"),
        ("app", False, "spotify:search:hindia"),
    ],
)
def test_spotify_open_mode(mode, installed, url):
    assert spotify_url({"music": {"open_mode": mode}}, "hindia", app_installed=installed) == url
