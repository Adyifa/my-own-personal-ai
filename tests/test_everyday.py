"""Everyday skills (stage 2) through the hub, on a fake clock with fake devices."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest

from mika.skills.media import VK_MEDIA_NEXT, VK_MEDIA_PLAY_PAUSE, VK_VOLUME_DOWN, VK_VOLUME_UP
from mika.skills.weather import WeatherService, parse_weather_request
from tests.conftest import NOW
from tests.fakes import make_everyday, weather_transport


# Time ----------------------------------------------------------------------------------


def test_time_and_date(everyday):
    everyday.clock.advance(minutes=15)
    assert everyday.hub.tell_time().text == "Sekarang jam 10 lewat 15 pagi."
    assert everyday.hub.tell_date().text == "Hari ini Kamis, 19 November 2026."


# Timers --------------------------------------------------------------------------------


def test_timer_with_label_and_status(everyday):
    hub = everyday.hub
    reply = hub.set_timer("pasang timer 5 menit buat masak mie")
    assert reply.text == "Oke, timer masak mie 5 menit mulai sekarang."
    timer = hub.reminders.upcoming(("timer",))[0]
    assert (timer.message, timer.seconds, timer.due) == ("masak mie", 300, NOW + timedelta(minutes=5))

    everyday.clock.advance(minutes=2)
    assert hub.timer_status().text == "Sisa timer masak mie 3 menit lagi."
    assert hub.cancel_timers("batalkan timer").text == "Oke, timer masak mie dibatalkan."
    assert hub.timer_status().text == "Nggak ada timer yang jalan."


def test_timer_asks_for_length(everyday):
    reply = everyday.hub.set_timer("pasang timer")
    assert (reply.ok, reply.text) == (False, "Timernya berapa lama?")
    assert reply.follow_up("buka youtube") is None  # unrelated answer is not swallowed
    assert reply.follow_up("sepuluh menit").text == "Oke, timer 10 menit mulai sekarang."


def test_timer_limit(everyday):
    assert not everyday.hub.set_timer("timer 2 hari").ok


# Reminders -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("utterance", "spoken"),
    [
        ("ingatkan aku jam 7 malam minum obat", "Oke, Mika ingatkan minum obat jam 7 malam."),
        ("ingatkan aku untuk angkat jemuran 30 menit lagi", "Oke, 30 menit lagi Mika ingatkan angkat jemuran."),
        ("besok pagi ingatkan aku meeting jam 9", "Oke, Mika ingatkan meeting besok jam 9 pagi."),
        ("bangunkan aku besok jam 5 pagi", "Oke, alarm besok jam 5 pagi sudah dipasang."),
        ("ingatkan aku jam 7", "Oke, Mika ingatkan kamu jam 7 malam."),
    ],
)
def test_set_reminder_confirms_the_resolved_time(everyday, utterance, spoken):
    assert everyday.hub.set_reminder(utterance).text == spoken


def test_reminder_without_time_asks_when(everyday):
    reply = everyday.hub.set_reminder("ingatkan aku minum obat")
    assert reply.text == "Mau diingatkan kapan?"
    done = reply.follow_up("jam 9 malam")
    assert done.text == "Oke, Mika ingatkan minum obat jam 9 malam."
    assert everyday.hub.reminders.upcoming()[0].message == "minum obat"


def test_list_and_cancel_reminders(everyday):
    hub = everyday.hub
    hub.set_reminder("ingatkan aku jam 7 malam minum obat")
    hub.set_reminder("besok ingatkan aku jam 9 pagi meeting")
    hub.set_timer("timer 10 menit")
    assert hub.list_reminders().text == (
        "Kamu punya 2 pengingat: minum obat jam 7 malam dan meeting besok jam 9 pagi. Ada juga 1 timer yang jalan."
    )
    assert hub.cancel_reminders("batalkan pengingat").text == "Pengingat yang mana? Ada minum obat dan meeting."
    assert hub.cancel_reminders("hapus pengingat minum obat").text == "Oke, pengingat minum obat dibatalkan."
    assert hub.cancel_reminders("batalkan pengingat").text == "Oke, pengingat meeting dibatalkan."
    assert not hub.cancel_reminders("batalkan pengingat").ok


def test_announcements_and_snooze(everyday):
    hub = everyday.hub
    heard = []
    hub.reminders.on_due = lambda item, late: heard.append(hub.announcement(item, late))
    hub.set_timer("timer 5 menit buat teh")
    hub.set_reminder("ingatkan aku 10 menit lagi angkat jemuran")
    hub.set_timer("timer 3 menit")

    for minutes in (3, 2, 5):  # the scheduler checks every second, so each item fires on time
        everyday.clock.advance(minutes=minutes)
        hub.reminders.check()
    assert heard == ["Timer 3 menit sudah selesai!", "Timer teh sudah selesai!", "Waktunya angkat jemuran!"]

    assert hub.snooze("tunda 10 menit").text == "Oke, Mika ingatkan lagi 10 menit lagi."
    everyday.clock.advance(minutes=10)
    hub.reminders.check()
    assert heard[-1] == "Waktunya angkat jemuran!"


def test_snooze_needs_a_recent_announcement(everyday):
    assert not everyday.hub.snooze("tunda").ok


def test_missed_reminder_is_announced_late(everyday):
    hub = everyday.hub
    hub.set_reminder("ingatkan aku jam 11 telpon ibu")
    everyday.clock.advance(hours=3)
    assert hub.announcement(hub.reminders.upcoming()[0], late=True) == "Tadi jam 11 siang ada pengingat: telpon ibu."


# Weather -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("utterance", "location", "day"),
    [
        ("cuaca hari ini", None, 0),
        ("cuaca di bandung besok gimana", "bandung", 1),
        ("cuaca jakarta", "jakarta", 0),
        ("bakal hujan nggak lusa", None, 2),
        ("cuaca kota malang", "malang", 0),
    ],
)
def test_parse_weather_request(utterance, location, day):
    assert parse_weather_request(utterance) == (location, day)


def test_weather_today_uses_default_city(everyday):
    reply = everyday.hub.weather("cuaca hari ini")
    assert reply.text == (
        "Di Jakarta sekarang 24 derajat, mendung. Hari ini 19 sampai 27 derajat, peluang hujan 80 persen. "
        "Jangan lupa bawa payung, ya."
    )
    assert "kelembapan 80%" in reply.detail
    geocode = everyday.weather_requests[0]
    assert geocode.url.params["countryCode"] == "ID" and geocode.url.params["name"] == "Jakarta"


def test_weather_tomorrow_in_named_city(everyday):
    reply = everyday.hub.weather("besok di bandung cuacanya gimana")
    assert reply.text.startswith("Besok di Bandung diperkirakan badai petir, 19 sampai 26 derajat, peluang hujan 90 persen.")
    assert reply.data["lokasi"] == "Bandung"


def test_weather_unknown_city_and_offline(config):
    unknown = WeatherService(config, client=httpx.Client(transport=weather_transport()))
    assert unknown.report("atlantis").spoken == "Mika nggak nemu lokasi atlantis."
    offline = WeatherService(config, client=httpx.Client(transport=weather_transport(offline=True)))
    report = offline.report()
    assert not report.ok and "internet" in report.spoken


# Media and volume ----------------------------------------------------------------------


def test_media_keys(everyday):
    hub = everyday.hub
    assert hub.media("pause").text == "Oke, Mika pause."
    assert everyday.keys == [VK_MEDIA_PLAY_PAUSE]  # pressed before speaking, so the reply is audible
    reply = hub.media("next")
    assert everyday.keys == [VK_MEDIA_PLAY_PAUSE]  # next happens after Mika finished talking
    reply.after()
    assert everyday.keys == [VK_MEDIA_PLAY_PAUSE, VK_MEDIA_NEXT]


@pytest.mark.parametrize(
    ("utterance", "spoken", "level"),
    [
        ("volume 50 persen", "Volume jadi 50 persen.", 0.5),
        ("naikkan volume", "Volume jadi 40 persen.", 0.4),
        ("kecilkan suara", "Volume jadi 20 persen.", 0.2),
        ("turunkan volume 25 persen", "Volume jadi 5 persen.", 0.05),
        ("naikkan volume ke 80", "Volume jadi 80 persen.", 0.8),
        ("volume berapa", "Volume sekarang 30 persen.", 0.3),
    ],
)
def test_volume_commands(everyday, utterance, spoken, level):
    assert everyday.hub.volume_command(utterance).text == spoken
    assert everyday.endpoint.level == pytest.approx(level)


def test_mute_happens_after_the_reply(everyday):
    reply = everyday.hub.volume_command("matikan suara")
    assert everyday.endpoint.muted == 0
    reply.after()
    assert everyday.endpoint.muted == 1
    assert everyday.hub.volume_command("nyalakan suara").text == "Suaranya sudah nyala lagi."
    assert everyday.endpoint.muted == 0


def test_volume_without_core_audio_uses_keys(config, tmp_path):
    fallback = make_everyday(config, tmp_path, NOW, endpoint=False)
    assert fallback.hub.volume_command("volume 10").text == "Volume jadi 10 persen."
    assert fallback.keys == [VK_VOLUME_DOWN] * 50 + [VK_VOLUME_UP] * 5
    assert fallback.hub.volume_command("volume berapa").ok is False


# System --------------------------------------------------------------------------------


def test_battery_states(config, tmp_path):
    charging = make_everyday(config, tmp_path, NOW).hub
    assert charging.system("battery").text == "Baterai 47 persen, lagi dicas."
    low = make_everyday(config, tmp_path, NOW, battery=SimpleNamespace(percent=15, secsleft=2400, power_plugged=False)).hub
    assert low.system("battery").text == "Baterai 15 persen, cukup untuk sekitar 40 menit lagi. Sebaiknya dicas sekarang."
    desktop = make_everyday(config, tmp_path, NOW, battery=None).hub
    assert not desktop.system("battery").ok


def test_system_usage(everyday):
    reply = everyday.hub.system("system")
    assert reply.text.startswith("CPU terpakai 15 persen, RAM 77 persen, dan sisa disk")


# Notes ---------------------------------------------------------------------------------


def test_notes_add_read_open(everyday):
    hub = everyday.hub
    assert hub.add_note("catat beli susu").text == "Oke, sudah Mika catat: beli susu."
    everyday.clock.advance(minutes=1)
    hub.add_note("tulis catatan bahwa besok rapat jam 9")
    assert hub.read_notes().text == "Catatan terbaru: besok rapat jam 9 dan beli susu."
    assert "2026-11-19 10:00  beli susu" in hub.read_notes().detail
    assert hub.open_notes().text == "Oke, Mika bukain catatanmu."
    assert everyday.opened == [hub.notes.path]


def test_note_without_text_asks(everyday):
    reply = everyday.hub.add_note("catat")
    assert reply.text == "Mau Mika catat apa?"
    assert reply.follow_up("telpon ibu jam 8").text == "Oke, sudah Mika catat: telpon ibu jam 8."


def test_no_notes_yet(everyday):
    assert everyday.hub.read_notes().text == "Belum ada catatan."
