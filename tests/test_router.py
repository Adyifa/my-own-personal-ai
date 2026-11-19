from __future__ import annotations

import pytest

from mika.audio.wake import strip_wake_prefix
from mika.brain.router import Router
from mika.text import clean_conversational_command


def route_of(config, launcher, utterance: str):
    return Router(config, launcher).route(clean_conversational_command(utterance))


# Every example from the original README must keep its old behaviour on the fast path.
@pytest.mark.parametrize(
    ("utterance", "path", "intent"),
    [
        ("buka youtube", "rule", "open_website"),
        ("youtube", "rule", "open_website"),
        ("buka gmail", "rule", "open_website"),
        ("tolong bukain youtube dong", "rule", "open_website"),
        ("buka notepad", "rule", "open_app"),
        ("buka kalkulator", "rule", "open_app"),
        ("buka counter strike", "rule", "open_game"),
        ("main cs2", "rule", "open_game"),
        ("aku mau main cs2 dong", "rule", "open_game"),
        ("mainkan cs2", "rule", "open_game"),
        ("cari kucing lucu di youtube", "rule", "browser_search"),
        ("nonton youtube tentang valorant", "rule", "browser_search"),
        ("cari cuaca jakarta di google", "rule", "browser_search"),
        ("putar lagu malu malu dari dia dan indahkus di spotify", "rule", "music"),
        ("puterin lagu yang santai", "rule", "music"),
        ("buka file laporan", "rule", "open_file"),
        ("cari file skripsi revisi", "rule", "open_file"),
        ("buka folder downloads", "rule", "open_file"),
        ("buka downloads", "rule", "open_file_alias"),
        ("sleep laptop", "rule", "power"),
        ("matikan laptop", "rule", "power"),
        ("bantuan", "rule", "help"),
        ("keluar", "rule", "stop"),
        ("selesai ngobrol", "rule", "conversation_stop"),
        ("kompas.com", "rule", "open_website"),
        ("buka", "rule", "ask_target"),
        # Everything else goes to the LLM agent.
        ("apa kabar", "agent", "chat"),
        ("ngobrol yuk", "agent", "chat"),
        ("aku lagi capek", "agent", "chat"),
        ("cari resep rendang", "agent", "web_answer"),
        ("siapa presiden indonesia sekarang", "agent", "general"),
        ("jelaskan apa itu machine learning", "agent", "general"),
        ("buka aplikasi yang nggak ada", "agent", "open_unknown"),
    ],
)
def test_routes(config, launcher, utterance, path, intent):
    route = route_of(config, launcher, utterance)
    assert (route.path, route.intent) == (path, intent), route


@pytest.mark.parametrize(
    ("utterance", "intent"),
    [
        ("jam berapa sekarang", "time_now"),
        ("sekarang jam berapa ya", "time_now"),
        ("hari ini tanggal berapa", "date_today"),
        ("hari apa sekarang", "date_today"),
        ("pasang timer 5 menit", "timer_set"),
        ("timer sepuluh menit buat masak", "timer_set"),
        ("sisa timer berapa lagi", "timer_status"),
        ("batalkan timer", "timer_cancel"),
        ("stop timer", "timer_cancel"),
        ("ingatkan aku jam 7 malam minum obat", "reminder_set"),
        ("tolong ingetin aku 30 menit lagi angkat jemuran", "reminder_set"),
        ("bangunkan aku besok jam 5 pagi", "reminder_set"),
        ("pasang alarm jam 6 pagi", "reminder_set"),
        ("pengingat apa saja", "reminder_list"),
        ("lihat pengingat", "reminder_list"),
        ("hapus pengingat minum obat", "reminder_cancel"),
        ("matikan alarm", "reminder_cancel"),
        ("tunda 10 menit", "snooze"),
        ("ingatkan lagi 5 menit", "snooze"),
        ("cuaca hari ini", "weather"),
        ("cuaca di bandung besok gimana", "weather"),
        ("bakal hujan nggak", "weather"),
        ("suhu sekarang berapa", "weather"),
        ("pause", "media"),
        ("lagu berikutnya dong", "media"),
        ("putar lagi", "media"),
        ("lagu sebelumnya", "media"),
        ("kecilkan volume", "volume"),
        ("volume 50 persen", "volume"),
        ("matikan suara", "volume"),
        ("keraskan suara", "volume"),
        ("baterai berapa", "system"),
        ("laptop lagi dicas nggak", "system"),
        ("pemakaian cpu berapa", "system"),
        ("catat beli susu", "note_add"),
        ("bacakan catatan", "note_read"),
        ("catatanku apa saja", "note_read"),
        ("buka catatan", "note_open"),
    ],
)
def test_everyday_routes(config, launcher, utterance, intent):
    route = route_of(config, launcher, utterance)
    assert (route.path, route.intent) == ("rule", intent), route


@pytest.mark.parametrize(
    "utterance",
    [
        "kenapa baterai laptop cepat habis",
        "jelaskan cuaca ekstrem",
        "apa itu volume dalam matematika",
        "suhu cpu laptop aman berapa",
    ],
)
def test_explanations_about_skill_topics_go_to_agent(config, launcher, utterance):
    assert route_of(config, launcher, utterance).path == "agent"


def test_media_and_music_do_not_collide(config, launcher):
    assert route_of(config, launcher, "putar lagi").intent == "media"
    assert route_of(config, launcher, "putar lagu santai").intent == "music"
    assert route_of(config, launcher, "stop").intent == "stop"  # still exits Mika
    assert route_of(config, launcher, "cari cuaca jakarta di google").intent == "browser_search"


def test_search_arguments(config, launcher):
    route = route_of(config, launcher, "nonton youtube tentang valorant")
    assert route.args == {"provider": "youtube_first", "query": "valorant"}

    route = route_of(config, launcher, "cari cuaca jakarta di google")
    assert route.args == {"provider": "google", "query": "cuaca jakarta"}

    route = route_of(config, launcher, "cari tahu tentang gempa hari ini")
    assert route.args == {"query": "gempa hari ini"}


def test_music_uses_song_alias(config, launcher):
    route = route_of(config, launcher, "putar lagu malu malu dari dia dan indahkus di spotify")
    assert route.args["query"] == "malu malu dia indahkus"


def test_power_carries_action(config, launcher):
    route = route_of(config, launcher, "tolong matikan laptop")
    assert route.args == {"action": "shutdown", "label": "laptop akan dimatikan"}


def test_question_mentioning_an_app_goes_to_agent(config, launcher):
    # The old parser matched app aliases as substrings anywhere, so this launched Python.
    config["apps"]["python"] = "python.exe"
    assert route_of(config, launcher, "apa itu python").path == "agent"
    assert route_of(config, launcher, "buka python").intent == "open_app"


def test_alias_must_be_a_whole_word(config, launcher):
    config["apps"]["word"] = "winword.exe"
    route = route_of(config, launcher, "buka password manager")
    assert route.intent != "open_app"


def test_longest_alias_wins_across_catalogs(config, launcher):
    config["apps"]["google chrome"] = "chrome.lnk"
    route = route_of(config, launcher, "buka google chrome")
    assert (route.intent, route.args["name"]) == ("open_app", "google chrome")


def test_partial_app_name_resolves_with_open_verb(config, launcher):
    config["apps"]["google chrome"] = "chrome.lnk"
    config["apps"]["uninstall chrome helper"] = "x.lnk"
    route = route_of(config, launcher, "buka chrome")
    assert (route.intent, route.args["name"]) == ("open_app", "google chrome")


def test_play_video_is_not_spotify(config, launcher):
    route = route_of(config, launcher, "putar video kucing")
    assert (route.intent, route.args["provider"]) == ("browser_search", "youtube_first")


def test_plain_search_can_stay_in_browser(config, launcher):
    config["search"]["plain_search_mode"] = "browser"
    route = route_of(config, launcher, "cari resep rendang")
    assert (route.path, route.intent, route.args["provider"]) == ("rule", "browser_search", "google")


def test_file_explorer_is_an_app_not_a_file_search(config, launcher):
    config["apps"]["file explorer"] = "explorer.exe"
    assert route_of(config, launcher, "buka file explorer").intent == "open_app"


@pytest.mark.parametrize(
    ("heard", "matched", "rest"),
    [
        ("halo mika buka youtube", True, "buka youtube"),
        ("ini random halo mika buka youtube", True, "buka youtube"),
        ("halo mica buka youtube", True, "buka youtube"),
        ("hai mikha cari berita", True, "cari berita"),
        ("halo mika", True, ""),
        ("buka youtube", False, "buka youtube"),
    ],
)
def test_wake_phrase(config, heard, matched, rest):
    assert strip_wake_prefix(heard, config["wake"]) == (matched, rest)


def test_conversational_cleanup():
    assert clean_conversational_command("tolong bukain youtube dong") == "buka youtube"
    assert clean_conversational_command("aku mau main cs2 dong") == "main cs2"
    assert clean_conversational_command("cariin resep rendang ya") == "cari resep rendang"
