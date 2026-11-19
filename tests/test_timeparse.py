from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from mika.skills.hub import reminder_message
from mika.skills.timeparse import (
    parse_when,
    remove_spans,
    speak_clock,
    speak_date,
    speak_duration,
    speak_when,
    words_to_digits,
)
from tests.conftest import NOW, WIB


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=WIB)


# NOW is Thursday 19 November 2026, 10:00 WIB.
@pytest.mark.parametrize(
    ("text", "expected", "relative"),
    [
        ("30 menit lagi", at(19, 10, 30), True),
        ("dalam 2 jam", at(19, 12), True),
        ("setengah jam lagi", at(19, 10, 30), True),
        ("satu setengah jam lagi", at(19, 11, 30), True),
        ("lima belas menit lagi", at(19, 10, 15), True),
        ("1 jam 30 menit lagi", at(19, 11, 30), True),
        ("sejam lagi", at(19, 11), True),
        ("2 hari lagi", at(21, 10), True),
        ("jam 7 malam", at(19, 19), False),
        ("jam tujuh malam", at(19, 19), False),
        ("jam 7", at(19, 19), False),  # 07:00 already passed, so the evening
        ("jam 11", at(19, 11), False),
        ("jam setengah 8 malam", at(19, 19, 30), False),  # Indonesian "setengah 8" is 7:30
        ("jam 19.30", at(19, 19, 30), False),
        ("jam 7 30 malam", at(19, 19, 30), False),
        ("pukul 14.00", at(19, 14), False),
        ("jam 10 kurang seperempat", at(19, 21, 45), False),
        ("jam 7 lewat 15 pagi", at(20, 7, 15), False),
        ("jam 2 siang", at(19, 14), False),
        ("jam 6 sore", at(19, 18), False),
        ("jam 12 malam", at(20, 0), False),
        ("jam 1 malam", at(20, 1), False),
        ("besok jam 7 pagi", at(20, 7), False),
        ("besok jam 3", at(20, 15), False),
        ("besok", at(20, 8), False),
        ("besok pagi", at(20, 7), False),
        ("nanti malam", at(19, 19), False),
        ("lusa jam 8", at(21, 8), False),
        ("hari senin jam 9", at(23, 9), False),
        ("kamis jam 9", at(26, 9), False),  # today's 9:00 has passed: next week
        ("minggu depan", at(26, 8), False),
    ],
)
def test_parse_when(text, expected, relative):
    when = parse_when(text, NOW)
    assert when is not None, text
    assert (when.at, when.relative) == (expected, relative)


@pytest.mark.parametrize("text", ["minum obat", "ingatkan aku nanti", "hari ini", "jam berapa sekarang"])
def test_no_time_means_none(text):
    assert parse_when(text, NOW) is None


def test_duration_inside_message_is_not_the_time():
    when = parse_when("jam 7 malam olahraga 30 menit", NOW)
    assert when.at == at(19, 19)
    assert remove_spans(when.text, when.spans) == "olahraga 30 menit"


def test_timer_length_is_not_a_clock():
    # "1 jam 30 menit" must not be read as "jam 30" (30 o'clock).
    when = parse_when("timer 1 jam 30 menit", NOW)
    assert when.relative and when.at == at(19, 11, 30)


@pytest.mark.parametrize(
    ("utterance", "message"),
    [
        ("ingatkan aku jam 7 malam minum obat", "minum obat"),
        ("ingatkan aku untuk angkat jemuran 30 menit lagi", "angkat jemuran"),
        ("besok pagi ingatkan aku meeting jam 9", "meeting"),
        ("tolong ingetin saya beli dua telur jam 5 sore", "beli 2 telur"),
        ("pasang pengingat jam 7 minum obat", "minum obat"),
        ("ingatkan aku jam 7", ""),
    ],
)
def test_reminder_message_extraction(utterance, message):
    when = parse_when(utterance, NOW)
    assert reminder_message(remove_spans(when.text, when.spans)) == message


def test_words_to_digits():
    assert words_to_digits("dua puluh lima menit") == "25 menit"
    assert words_to_digits("lima belas") == "15"
    assert words_to_digits("sejam setengah") == "1 jam setengah"


@pytest.mark.parametrize(
    ("hour", "minute", "spoken"),
    [(19, 0, "jam 7 malam"), (19, 30, "jam setengah 8 malam"), (18, 0, "jam 6 sore"), (7, 15, "jam 7 lewat 15 pagi"),
     (0, 0, "jam 12 malam"), (13, 0, "jam 1 siang"), (2, 0, "jam 2 dini hari")],
)
def test_speak_clock(hour, minute, spoken):
    assert speak_clock(at(19, hour, minute)) == spoken


def test_speak_when_and_duration():
    assert speak_when(at(20, 0), NOW) == "jam 12 malam"  # midnight belongs to tonight
    assert speak_when(at(20, 7), NOW) == "besok jam 7 pagi"
    assert speak_when(at(23, 9), NOW) == "hari Senin jam 9 pagi"
    assert speak_when(at(26, 9), NOW) == "hari Kamis depan jam 9 pagi"
    assert speak_duration(5400) == "1 jam 30 menit"
    assert speak_duration(130) == "2 menit 10 detik"
    assert speak_duration(45) == "45 detik"
    assert speak_date(NOW) == "Kamis, 19 November 2026"
    assert speak_when(NOW + timedelta(days=30), NOW) == "tanggal 19 Desember jam 10 pagi"
