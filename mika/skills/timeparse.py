"""Indonesian time expressions → datetimes ("30 menit lagi", "jam setengah 8 malam", "besok pagi"); pure and offline."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..text import normalize

_UNITS = {"satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5, "enam": 6, "tujuh": 7, "delapan": 8, "sembilan": 9}
_U = "|".join(_UNITS)
UNIT_SECONDS = {"detik": 1, "dtk": 1, "menit": 60, "mnt": 60, "jam": 3600, "hari": 86400, "minggu": 604800}

_NUM = r"\d+(?:[.,]\d+)?"
_UNIT = r"(?:jam|menit|mnt|detik|dtk|hari|minggu)"
_QTY = rf"(?:{_NUM}\s*(?:setengah|seperempat)?|setengah|seperempat)\s*{_UNIT}\b"
DURATION_RE = re.compile(rf"(?<![\w.]){_QTY}(?:\s+(?:dan\s+)?{_QTY})*(?:\s+setengah\b(?!\s*\d))?")
_RELATIVE_MARK = re.compile(r"\b(lagi|dalam|setelah|sesudah)\b")

CLOCK_RE = re.compile(
    r"\b(?:jam|pukul|pkl)\s+"
    r"(?:setengah\s+(?P<half>\d{1,2})"
    r"|(?P<h>\d{1,2})(?:\s*[.:]\s*(?P<m>\d{2})|\s+(?P<m2>\d{2})(?!\s*(?:menit|detik|jam)))?"
    r"(?:\s+(?P<rel>lewat|lebih|kurang)\s+(?P<rm>\d{1,2}|seperempat|setengah)(?:\s+menit)?)?)"
)
BARE_CLOCK_RE = re.compile(r"(?<![\d.])(?P<h>\d{1,2})[.:](?P<m>\d{2})(?![\d.])")
PART_RE = re.compile(r"\b(pagi|siang|sore|malam|subuh|dini hari|tengah malam)\b")
_WEEKDAYS = {"senin": 0, "selasa": 1, "rabu": 2, "kamis": 3, "jumat": 4, "jum at": 4, "sabtu": 5, "minggu": 6}
DAY_RE = re.compile(
    r"\b(hari ini|nanti|besok|bsk|lusa|minggu depan"
    r"|(?:hari\s+)?(?:senin|selasa|rabu|kamis|jumat|jum at|sabtu)"
    r"|hari\s+minggu|minggu(?!\s+(?:depan|lagi|ini)))\b"
)
PART_DEFAULT_HOUR = {"pagi": 7, "subuh": 5, "siang": 12, "sore": 16, "malam": 19, "dini hari": 3, "tengah malam": 0}
_DAY_NAMES = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
_MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]


@dataclass
class When:
    """A resolved time plus the text spans that described it (removed later to get the reminder message)."""

    at: datetime
    relative: bool
    spans: list[tuple[int, int]] = field(default_factory=list)
    text: str = ""  # the digit-normalized utterance the spans refer to


def words_to_digits(text: str) -> str:
    """Speech recognizers sometimes spell numbers out: "lima belas menit" → "15 menit", "sejam" → "1 jam"."""
    t = f" {normalize(text)} "
    t = re.sub(rf"\b({_U}) puluh ({_U})\b", lambda m: str(_UNITS[m[1]] * 10 + _UNITS[m[2]]), t)
    t = re.sub(rf"\b({_U}) puluh\b", lambda m: str(_UNITS[m[1]] * 10), t)
    t = re.sub(rf"\b({_U}) belas\b", lambda m: str(10 + _UNITS[m[1]]), t)
    t = re.sub(r"\bsepuluh\b", "10", t)
    t = re.sub(r"\bsebelas\b", "11", t)
    t = re.sub(r"\bseratus\b", "100", t)
    t = re.sub(r"\bse(jam|menit|detik|hari|minggu)\b", r"1 \1", t)
    t = re.sub(rf"\b({_U})\b", lambda m: str(_UNITS[m[1]]), t)
    t = re.sub(r"\bnol\b", "0", t)
    return re.sub(r"\s+", " ", t).strip()


def duration_seconds(text: str) -> int:
    """Total seconds in a duration phrase: "1 jam 30 menit" → 5400, "setengah jam" → 1800."""
    total = 0.0
    last_unit = ""
    for match in re.finditer(rf"(?:(?P<num>{_NUM})\s*)?(?P<frac>setengah|seperempat)?\s*(?P<unit>{_UNIT})\b", text):
        num, frac, unit = match.group("num"), match.group("frac"), match.group("unit")
        value = float(num.replace(",", ".")) if num else 0.0
        if frac == "setengah":
            value += 0.5
        elif frac == "seperempat":
            value += 0.25
        elif not num:
            continue
        total += value * UNIT_SECONDS[unit]
        last_unit = unit
    if last_unit and re.search(r"\bsetengah\s*$", text):  # "1 jam setengah"
        total += 0.5 * UNIT_SECONDS[last_unit]
    return int(round(total))


def find_duration(text: str) -> tuple[int, tuple[int, int]] | None:
    """First duration in already digit-normalized text, with its span."""
    match = DURATION_RE.search(text)
    if not match:
        return None
    seconds = duration_seconds(match.group())
    return (seconds, match.span()) if seconds > 0 else None


def parse_when(text: str, now: datetime) -> When | None:
    """Resolve a relative ("30 menit lagi") or absolute ("besok jam 7 pagi") time; None if the text has none."""
    t = words_to_digits(text)
    duration = find_duration(t)
    clock = _find_clock(t, duration[1] if duration else None)
    # A duration is the time only when marked ("lagi", "dalam") or when no clock is given;
    # otherwise it belongs to the message ("jam 7 olahraga 30 menit").
    if duration and (_RELATIVE_MARK.search(t) or not clock):
        seconds, span = duration
        spans = [span] + [m.span() for m in _RELATIVE_MARK.finditer(t)]
        return When(now + timedelta(seconds=seconds), relative=True, spans=spans, text=t)

    parts = list(PART_RE.finditer(t))
    days = list(DAY_RE.finditer(t))
    if not clock and not parts and not days:
        return None

    part = parts[0].group(1) if parts else None
    day = days[0].group(1) if days else None
    if not clock and not part and day in ("hari ini", "nanti"):
        return None  # "nanti" alone is not a time; better to ask "jam berapa?"
    explicit_24h = False
    if clock:
        hour, minute, explicit_24h = _clock_from_match(clock)
    elif part:
        hour, minute = PART_DEFAULT_HOUR[part], 0
        explicit_24h = True
    else:
        hour, minute = 8, 0  # "besok" alone: a sensible morning default, confirmed back to the user
        explicit_24h = True

    hour, extra_days = _apply_part(hour, part, explicit_24h)
    base, weekday_given = _base_date(day, now)
    at = _at(base, hour, minute) + timedelta(days=extra_days)

    if day is None or day in ("hari ini", "nanti"):
        if not part and not explicit_24h and hour <= 12:
            # "jam 7" with no part of day: the next 7:00 or 19:00, whichever comes first.
            candidates = [at, at + timedelta(hours=12), at + timedelta(days=1)]
            at = min(candidate for candidate in candidates if candidate > now)
        elif at <= now:
            at += timedelta(days=1)
    elif not part and not explicit_24h and 1 <= hour <= 4:
        at += timedelta(hours=12)  # "besok jam 3" is 15:00, not 03:00
    if weekday_given and at <= now:
        at += timedelta(days=7)

    spans = ([clock.span()] if clock else []) + [m.span() for m in parts] + [m.span() for m in days]
    return When(at, relative=False, spans=spans, text=t)


def _find_clock(text: str, duration_span: tuple[int, int] | None) -> re.Match | None:
    """First valid clock that is not part of a duration ("1 jam 30 menit" contains no 30 o'clock)."""
    for pattern in (CLOCK_RE, BARE_CLOCK_RE):
        for match in pattern.finditer(text):
            if duration_span and match.start() < duration_span[1] and match.end() > duration_span[0]:
                continue
            hour = int(match.groupdict().get("half") or match.group("h"))
            minute = int(match.groupdict().get("m") or match.groupdict().get("m2") or 0)
            if hour <= 24 and minute <= 59:
                return match
    return None


def _clock_from_match(match: re.Match) -> tuple[int, int, bool]:
    """(hour, minute, is_24h) from a clock match, handling "setengah 8" (7:30), "lewat", and "kurang"."""
    if match.groupdict().get("half"):
        return (int(match.group("half")) - 1) % 24, 30, False
    raw_hour = match.group("h")
    hour = int(raw_hour)
    minute = int(match.groupdict().get("m") or match.groupdict().get("m2") or 0)
    rel, rm = match.groupdict().get("rel"), match.groupdict().get("rm")
    if rel:
        offset = 15 if rm == "seperempat" else 30 if rm == "setengah" else int(rm)
        minute = minute + offset if rel in ("lewat", "lebih") else minute - offset
        hour += minute // 60
        minute %= 60
    explicit_24h = hour > 12 or hour == 0 or raw_hour.startswith("0")
    return hour % 24, minute, explicit_24h


def _apply_part(hour: int, part: str | None, explicit_24h: bool) -> tuple[int, int]:
    """Shift an hour by "pagi/siang/sore/malam"; returns (hour, extra days) for times after midnight."""
    if part is None or (explicit_24h and hour > 12):
        return hour, 0
    if part in ("pagi", "subuh", "dini hari"):
        return (0 if hour == 12 else hour), 0
    if part == "siang":
        return (hour + 12 if 1 <= hour <= 5 else hour), 0
    if part == "sore":
        return (hour + 12 if 1 <= hour <= 11 else hour), 0
    if part == "tengah malam":
        return 0, 1
    if 6 <= hour <= 11:  # malam
        return hour + 12, 0
    if hour == 12 or hour == 0:
        return 0, 1  # "jam 12 malam" is the midnight at the end of that day
    return hour, 0  # "jam 1 malam" is 01:00; the caller rolls it to the next day if already past


def _base_date(day: str | None, now: datetime) -> tuple[datetime, bool]:
    """Midnight of the day referred to, and whether it was a weekday name."""
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if day in (None, "hari ini", "nanti"):
        return today, False
    if day in ("besok", "bsk"):
        return today + timedelta(days=1), False
    if day == "lusa":
        return today + timedelta(days=2), False
    if day == "minggu depan":
        return today + timedelta(days=7), False
    name = day.replace("hari ", "").strip()
    target = _WEEKDAYS[name]
    return today + timedelta(days=(target - now.weekday()) % 7), True


def _at(base: datetime, hour: int, minute: int) -> datetime:
    return base + timedelta(hours=hour, minutes=minute)


# Spoken and written formats -------------------------------------------------------------


def speak_duration(seconds: float) -> str:
    """5400 → "1 jam 30 menit"; rounds to whole seconds."""
    seconds = max(0, int(round(seconds)))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    if hours:
        parts.append(f"{hours} jam")
    if minutes:
        parts.append(f"{minutes} menit")
    if secs and not hours:
        parts.append(f"{secs} detik")
    return " ".join(parts) or "0 detik"


def part_of_day(hour: int) -> str:
    """Indonesian part of day for an hour (0-23)."""
    if 4 <= hour <= 10:
        return "pagi"
    if 11 <= hour <= 14:
        return "siang"
    if 15 <= hour <= 18:
        return "sore"
    if 19 <= hour <= 23 or hour == 0:
        return "malam"
    return "dini hari"


def speak_clock(at: datetime) -> str:
    """How people say the time: 19:00 → "jam 7 malam", 19:30 → "jam setengah 8 malam"."""
    part = part_of_day(at.hour)
    hour12 = at.hour % 12 or 12
    if at.minute == 0:
        return f"jam {hour12} {part}"
    if at.minute == 30:
        next_hour = (at.hour + 1) % 12 or 12
        return f"jam setengah {next_hour} {part}"
    return f"jam {hour12} lewat {at.minute} {part}"


def speak_day(at: datetime, now: datetime) -> str:
    """"" for today, "besok", "lusa", "hari Senin" within a week, else "tanggal 25 Desember"."""
    if at.hour == 0:
        at = at - timedelta(hours=1)  # 00:xx is said as "jam 12 malam" of the evening before
    days = (at.date() - now.date()).days
    if days == 0:
        return ""
    if days == 1:
        return "besok"
    if days == 2:
        return "lusa"
    if 0 < days < 7:
        return f"hari {_DAY_NAMES[at.weekday()]}"
    if days == 7:
        return f"hari {_DAY_NAMES[at.weekday()]} depan"
    return f"tanggal {at.day} {_MONTHS[at.month - 1]}"


def speak_when(at: datetime, now: datetime) -> str:
    """Day and clock together: "besok jam 7 pagi"."""
    return f"{speak_day(at, now)} {speak_clock(at)}".strip()


def speak_date(at: datetime) -> str:
    """"Kamis, 19 November 2026"."""
    return f"{_DAY_NAMES[at.weekday()]}, {at.day} {_MONTHS[at.month - 1]} {at.year}"


def remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Text with the given spans cut out (used to get the reminder message)."""
    keep = list(text)
    for start, end in spans:
        for index in range(start, end):
            keep[index] = " "
    return re.sub(r"\s+", " ", "".join(keep)).strip()
