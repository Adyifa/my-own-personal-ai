"""Everyday skills behind one interface, shared by the rule path and the agent tools so both answer the same way."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from ..config import DATA_DIR
from ..text import normalize
from .media import MediaControl, VolumeControl
from .notes import NotesStore
from .reminders import Reminder, ReminderService
from .system_info import SystemInfo
from .timeparse import (
    find_duration,
    parse_when,
    remove_spans,
    speak_clock,
    speak_date,
    speak_duration,
    speak_when,
    words_to_digits,
)
from .weather import WeatherService, parse_weather_request


@dataclass
class SkillReply:
    """What a skill says, plus optional screen detail, an action to run after speaking, and a follow-up question."""

    text: str
    ok: bool = True
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    after: Callable[[], Any] | None = None  # e.g. mute only after "Oke, suara Mika bisukan" was heard
    follow_up: Callable[[str], "SkillReply | None"] | None = None  # handles the answer to a question like "jam berapa?"


_REMIND_LEAD = re.compile(
    r"^(?:tolong\s+)?(?:(?:pasang|setel|set|bikin|buat|buatkan|tambah|tambahkan)\s+)?"
    r"(?:pengingat|reminder|alarm)?\s*"
    r"(?:ingatkan|ingetin|ingatin|ingetkan|bangunkan|bangunin)?\s*"
    r"(?:aku|saya|gue|gw|kami|kita)?\b"
)
_LEAD_FILLER = re.compile(r"^(?:untuk|buat|supaya|agar|bahwa|kalau|soal|tentang|tuk|biar|pada|ya|dong|kamu)\s+")
_TAIL_FILLER = re.compile(r"\s+(?:ya|dong|nanti|ini|pukul|jam|pada|di|untuk|buat)$")
_ALARM = re.compile(r"\b(alarm|bangunkan|bangunin)\b")
_TIMER_WORDS = re.compile(
    r"\b(?:tolong|pasang|setel|set|bikin|buat|buatkan|mulai|mulaikan|nyalakan|jalankan|timer|countdown|hitung mundur"
    r"|pengatur waktu|selama|ya|dong|untuk|batalkan|batal|hapus|stop|matikan|hentikan|cancel|semua|yang)\b"
)
_CANCEL_WORDS = re.compile(
    r"\b(?:tolong|batalkan|batal|hapus|hapuskan|stop|matikan|hentikan|cancel|buang|pengingat|pengingatku|reminder|alarm"
    r"|yang|untuk|buat|soal|tentang|aku|saya|semua|nya|dong|ya)\b"
)
_NOTE_LEAD = re.compile(
    r"^(?:tolong\s+)?(?:catatlah|catat|catet|tulis catatan|simpan catatan|bikin catatan|buat catatan|tambah catatan"
    r"|tambahkan catatan)\b\s*(?::\s*)?(?:bahwa\s+|ini\s+)?"
)
_MUTE = re.compile(r"\b(mute|bisukan|senyapkan|matikan suara|matiin suara|diamkan suara)\b")
_UNMUTE = re.compile(r"\b(unmute|nyalakan suara|nyalain suara|hidupkan suara|aktifkan suara|bunyikan)\b")
_UP = re.compile(r"\b(naik|naikkan|naikin|keraskan|kerasin|besarkan|besarin|gedein|tambah|tambahin|tingkatkan|kencengin|kencangkan)\b")
_DOWN = re.compile(r"\b(turun|turunkan|turunin|kecilkan|kecilin|pelankan|pelanin|kurangi|kurangin|rendahkan)\b")


def join_words(items: list[str]) -> str:
    """Indonesian list: "a", "a dan b", "a, b, dan c"."""
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return f"{items[0]} dan {items[1]}"
    return ", ".join(items[:-1]) + f", dan {items[-1]}"


def reminder_message(text: str) -> str:
    """Strip "ingatkan aku untuk" and similar filler, leaving what to be reminded about."""
    message = _REMIND_LEAD.sub("", normalize(text)).strip()
    previous = None
    while previous != message:
        previous = message
        message = _LEAD_FILLER.sub("", message).strip()
        message = _TAIL_FILLER.sub("", message).strip()
    return message


class SkillHub:
    """Time, timers, reminders, weather, media, volume, system status, and notes."""

    def __init__(
        self,
        *,
        reminders: ReminderService,
        weather: WeatherService | None,
        media: MediaControl,
        volume: VolumeControl,
        system: SystemInfo,
        notes: NotesStore,
        open_path: Callable[[Path], Any] | None = None,
        volume_step: int = 10,
        snooze_minutes: int = 5,
    ):
        self.snooze_minutes = snooze_minutes
        self.reminders = reminders
        self.weather_service = weather
        self.media_control = media
        self.volume_control = volume
        self.system_info = system
        self.notes = notes
        self.open_path = open_path
        self.volume_step = volume_step

    def now(self) -> datetime:
        """Current time from the reminder clock (one injectable clock for every skill)."""
        return self.reminders.now()

    # Time ------------------------------------------------------------------------------

    def tell_time(self) -> SkillReply:
        """Works offline, straight from the system clock."""
        now = self.now()
        return SkillReply(f"Sekarang {speak_clock(now)}.", data={"waktu": now.isoformat()})

    def tell_date(self) -> SkillReply:
        """Today's day and date."""
        now = self.now()
        return SkillReply(f"Hari ini {speak_date(now)}.", data={"tanggal": now.date().isoformat()})

    # Timers ----------------------------------------------------------------------------

    def set_timer(self, text: str) -> SkillReply:
        """"pasang timer 5 menit buat masak mie"; asks for the length when it is missing."""
        t = words_to_digits(text)
        found = find_duration(t)
        label = _timer_label(t, found[1] if found else None)
        if not found:
            return SkillReply("Timernya berapa lama?", ok=False, follow_up=lambda answer: self._timer_answer(answer, label))
        return self.start_timer(found[0], label)

    def _timer_answer(self, answer: str, label: str) -> SkillReply | None:
        """Follow-up: accept the answer only if it contains a duration."""
        found = find_duration(words_to_digits(answer))
        return self.start_timer(found[0], label) if found else None

    def start_timer(self, seconds: int, label: str = "") -> SkillReply:
        """Start a timer of `seconds` (max 24 hours)."""
        if seconds > 86400:
            return SkillReply("Timer paling lama 24 jam, ya.", ok=False)
        item = self.reminders.add("timer", label, self.now() + timedelta(seconds=seconds), seconds)
        name = f"timer {label} " if label else "timer "
        return SkillReply(f"Oke, {name}{speak_duration(seconds)} mulai sekarang.", data={"id": item.id, "detik": seconds, "label": label})

    def timer_status(self) -> SkillReply:
        """How long the running timers have left."""
        now = self.now()
        timers = self.reminders.upcoming(("timer",))
        if not timers:
            return SkillReply("Nggak ada timer yang jalan.")
        parts = [
            f"{('timer ' + item.message) if item.message else 'timer'} {speak_duration((item.due - now).total_seconds())} lagi"
            for item in timers[:3]
        ]
        prefix = "Sisa " if len(timers) == 1 else f"Ada {len(timers)} timer: "
        return SkillReply(prefix + join_words(parts) + ".", data={"timer": [t.to_json() for t in timers]})

    def cancel_timers(self, text: str) -> SkillReply:
        """Cancel all timers, a named one, or the soonest."""
        t = normalize(text)
        query = re.sub(r"\s+", " ", _TIMER_WORDS.sub(" ", t)).strip()
        removed = self.reminders.cancel(("timer",), query=query, everything="semua" in t.split())
        if not removed:
            return SkillReply("Nggak ada timer yang cocok untuk dibatalkan.", ok=False)
        if len(removed) > 1:
            return SkillReply(f"Oke, {len(removed)} timer dibatalkan.")
        label = f"timer {removed[0].message}" if removed[0].message else "timernya"
        return SkillReply(f"Oke, {label} dibatalkan.")

    # Reminders -------------------------------------------------------------------------

    def set_reminder(self, text: str) -> SkillReply:
        """"ingatkan aku jam 7 malam minum obat"; asks "kapan?" when no time was said."""
        kind = "alarm" if _ALARM.search(normalize(text)) else "reminder"
        when = parse_when(text, self.now())
        if when is None:
            message = reminder_message(words_to_digits(text))
            question = "Alarmnya jam berapa?" if kind == "alarm" else "Mau diingatkan kapan?"
            return SkillReply(question, ok=False, follow_up=lambda answer: self._reminder_answer(answer, message, kind))
        message = reminder_message(remove_spans(when.text, when.spans))
        return self._schedule(kind, message, when.at, when.relative)

    def set_reminder_parts(self, when_text: str, message: str = "", kind: str = "reminder") -> SkillReply:
        """Agent entry point: the LLM extracts "kapan" and "apa"; our parser does the time math."""
        when = parse_when(when_text, self.now())
        if when is None:
            return SkillReply(
                "Waktunya belum kebaca.",
                ok=False,
                data={"error": "Format waktu tidak dikenali. Contoh: 'jam 19.30', '30 menit lagi', 'besok jam 7 pagi'."},
            )
        message = reminder_message(message) if message else reminder_message(remove_spans(when.text, when.spans))
        return self._schedule("alarm" if kind == "alarm" else "reminder", message, when.at, when.relative)

    def _reminder_answer(self, answer: str, message: str, kind: str) -> SkillReply | None:
        """Follow-up: accept the answer only if it contains a time."""
        when = parse_when(answer, self.now())
        if when is None:
            return None
        extra = reminder_message(remove_spans(when.text, when.spans))
        return self._schedule(kind, message or extra, when.at, when.relative)

    def _schedule(self, kind: str, message: str, at: datetime, relative: bool) -> SkillReply:
        """Save the reminder and confirm the resolved time out loud, so a misheard time is caught."""
        now = self.now()
        if at <= now:
            return SkillReply("Waktu itu sudah lewat. Coba sebut waktu yang lain, ya.", ok=False)
        if kind == "alarm":
            message = message or "bangun"
        item = self.reminders.add(kind, message, at)
        data = {"id": item.id, "waktu": at.isoformat(), "pesan": message}
        if kind == "alarm":
            return SkillReply(f"Oke, alarm {speak_when(at, now)} sudah dipasang.", data=data)
        what = message or "kamu"
        if relative and at - now < timedelta(days=1):
            return SkillReply(f"Oke, {speak_duration((at - now).total_seconds())} lagi Mika ingatkan {what}.", data=data)
        return SkillReply(f"Oke, Mika ingatkan {what} {speak_when(at, now)}.", data=data)

    def list_reminders(self) -> SkillReply:
        """Upcoming reminders (three spoken, all on screen) plus a count of running timers."""
        now = self.now()
        items = self.reminders.upcoming(("reminder", "alarm"))
        timers = self.reminders.upcoming(("timer",))
        if not items and not timers:
            return SkillReply("Belum ada pengingat atau timer yang aktif.")
        sentences = []
        if items:
            spoken = [f"{item.message or 'pengingat'} {speak_when(item.due, now)}" for item in items[:3]]
            lead = f"Kamu punya {len(items)} pengingat" + (". Tiga terdekat: " if len(items) > 3 else ": ")
            sentences.append(lead + join_words(spoken) + ".")
        if timers:
            sentences.append(f"Ada juga {len(timers)} timer yang jalan." if items else f"Ada {len(timers)} timer yang jalan.")
        detail = "\n".join(f"{item.due:%a %d %b %H.%M}  {item.kind}: {item.message or '-'}" for item in [*items, *timers])
        return SkillReply(" ".join(sentences), detail=detail, data={"pengingat": [item.to_json() for item in items]})

    def cancel_reminders(self, text: str) -> SkillReply:
        """Cancel all, one by name ("batalkan pengingat minum obat"), or ask which one."""
        t = normalize(text)
        everything = "semua" in t.split()
        query = re.sub(r"\s+", " ", _CANCEL_WORDS.sub(" ", t)).strip()
        pending = self.reminders.upcoming(("reminder", "alarm"))
        if not pending:
            return SkillReply("Belum ada pengingat yang aktif.", ok=False)
        if not everything and not query and len(pending) > 1:
            names = join_words([item.message or "pengingat" for item in pending[:3]])
            return SkillReply(f"Pengingat yang mana? Ada {names}.", ok=False)
        removed = self.reminders.cancel(("reminder", "alarm"), query=query, everything=everything)
        if not removed:
            return SkillReply("Mika nggak nemu pengingat itu.", ok=False)
        if len(removed) > 1:
            return SkillReply(f"Oke, {len(removed)} pengingat dibatalkan.")
        return SkillReply(f"Oke, pengingat {removed[0].message or 'itu'} dibatalkan.")

    def snooze(self, text: str) -> SkillReply:
        """"tunda 10 menit" right after an announcement repeats it later."""
        last = self.reminders.last_fired
        now = self.now()
        if last is None or now - last[1] > timedelta(minutes=30):
            return SkillReply("Belum ada pengingat yang bisa ditunda.", ok=False)
        found = find_duration(words_to_digits(text))
        seconds = found[0] if found else self.snooze_minutes * 60
        item = last[0]
        self.reminders.add(item.kind, item.message, now + timedelta(seconds=seconds), item.seconds)
        return SkillReply(f"Oke, Mika ingatkan lagi {speak_duration(seconds)} lagi.")

    def announcement(self, item: Reminder, late: bool) -> str:
        """What Mika says when something is due (or was missed while the laptop was off)."""
        if item.kind == "timer":
            name = f"Timer {item.message}" if item.message else f"Timer {speak_duration(item.seconds or 0)}"
            return f"{name} sudah selesai{' tadi' if late else ''}!"
        if late:
            label = "alarm" if item.kind == "alarm" else "pengingat"
            return f"Tadi {speak_clock(item.due)} ada {label}: {item.message or 'dari kamu'}."
        if item.kind == "alarm":
            return f"Waktunya {item.message or 'bangun'}! Sekarang {speak_clock(self.now())}."
        return f"Waktunya {item.message}!" if item.message else "Ini pengingat yang kamu pasang tadi."

    # Weather ---------------------------------------------------------------------------

    def weather(self, text: str) -> SkillReply:
        """"cuaca di bandung besok" → spoken forecast."""
        location, day = parse_weather_request(text)
        return self.weather_for(location, day)

    def weather_for(self, location: str | None, day: int = 0) -> SkillReply:
        """Forecast for a city (default from config) and day offset."""
        if self.weather_service is None:
            return SkillReply("Fitur cuaca belum aktif.", ok=False)
        report = self.weather_service.report(location, day)
        return SkillReply(report.spoken, ok=report.ok, detail=report.detail, data=report.data)

    # Media and volume --------------------------------------------------------------------

    def media(self, action: str) -> SkillReply:
        """Pause acts before speaking (so the reply is heard); play/next/previous act after it."""
        if action == "pause":
            self.media_control.play_pause()
            return SkillReply("Oke, Mika pause.")
        actions = {
            "play": ("Oke, lanjut.", self.media_control.play_pause),
            "next": ("Oke, lagu berikutnya.", self.media_control.next),
            "previous": ("Oke, lagu sebelumnya.", self.media_control.previous),
        }
        if action not in actions:
            return SkillReply("Perintah media itu belum Mika kenal.", ok=False)
        text, run = actions[action]
        return SkillReply(text, after=run)

    def volume_command(self, text: str) -> SkillReply:
        """Parse "kecilkan volume", "volume 50 persen", "naikkan volume 20", "mute"."""
        t = words_to_digits(text)
        number = re.search(r"\b(\d{1,3})\s*(?:persen|%)?", t)
        level = int(number.group(1)) if number else None
        if _UNMUTE.search(t):
            return self.volume_action("unmute")
        if _MUTE.search(t):
            return self.volume_action("mute")
        absolute = level is not None and (re.search(r"\b(ke|jadi|di|atur|set|setel)\b", t) or not (_UP.search(t) or _DOWN.search(t)))
        if absolute:
            return self.volume_action("set_volume", level)
        if _UP.search(t):
            return self.volume_action("volume_up", level)
        if _DOWN.search(t):
            return self.volume_action("volume_down", level)
        return self.volume_action("get")

    def volume_action(self, action: str, level: int | None = None) -> SkillReply:
        """Apply one volume action and report the new level when Windows can tell us."""
        control = self.volume_control
        if action == "mute":
            return SkillReply("Oke, suara Mika bisukan.", after=lambda: control.mute(True))
        if action == "unmute":
            control.mute(False)
            return SkillReply("Suaranya sudah nyala lagi.")
        if action == "set_volume" and level is not None:
            new_level = control.set(level)
            return SkillReply(f"Volume jadi {new_level} persen.", data={"volume": new_level})
        if action in ("volume_up", "volume_down"):
            step = level or self.volume_step
            new_level = control.change(step if action == "volume_up" else -step)
            if new_level is not None:
                return SkillReply(f"Volume jadi {new_level} persen.", data={"volume": new_level})
            return SkillReply("Oke, volume Mika naikkan." if action == "volume_up" else "Oke, volume Mika kecilkan.")
        current = control.get()
        if current is None:
            return SkillReply("Mika nggak bisa membaca volume sekarang.", ok=False)
        return SkillReply(f"Volume sekarang {current} persen.", data={"volume": current})

    # System -----------------------------------------------------------------------------

    def system(self, kind: str = "battery") -> SkillReply:
        """Battery status, or CPU/RAM/disk usage."""
        try:
            if kind == "battery":
                return self._battery()
            usage = self.system_info.usage()
        except ImportError:
            return SkillReply("Info sistem belum tersedia, paket psutil belum terpasang.", ok=False)
        disk = usage["disk"].rstrip(":\\/")
        text = (
            f"CPU terpakai {usage['cpu_percent']} persen, RAM {usage['ram_percent']} persen, "
            f"dan sisa disk {disk} {usage['disk_free_gb']} GB."
        )
        detail = f"CPU {usage['cpu_percent']}%\nRAM {usage['ram_percent']}%\nDisk {disk}: {usage['disk_free_gb']} / {usage['disk_total_gb']} GB kosong"
        return SkillReply(text, detail=detail, data=usage)

    def _battery(self) -> SkillReply:
        """Spoken battery level with charging state and time left."""
        battery = self.system_info.battery()
        if battery is None:
            return SkillReply("Mika nggak bisa membaca baterai di perangkat ini.", ok=False)
        percent, plugged, minutes = battery["percent"], battery["plugged"], battery["minutes_left"]
        if plugged:
            text = f"Baterai {percent} persen, lagi dicas."
        elif minutes:
            text = f"Baterai {percent} persen, cukup untuk sekitar {speak_duration(minutes * 60)} lagi."
        else:
            text = f"Baterai {percent} persen."
        if percent <= 20 and not plugged:
            text += " Sebaiknya dicas sekarang."
        return SkillReply(text, data=battery)

    # Notes ------------------------------------------------------------------------------

    def add_note(self, text: str) -> SkillReply:
        """"catat beli susu" → appended to data/notes.md; asks what to note if empty."""
        note = _NOTE_LEAD.sub("", normalize(text)).strip()
        if not note:
            return SkillReply("Mau Mika catat apa?", ok=False, follow_up=self._note_answer)
        saved = self.notes.add(note, self.now())
        spoken = f"Oke, sudah Mika catat: {saved}." if len(saved) <= 80 else "Oke, sudah Mika catat."
        return SkillReply(spoken, data={"catatan": saved})

    def _note_answer(self, answer: str) -> SkillReply | None:
        """Follow-up: the next sentence is the note."""
        return self.add_note(answer) if answer.strip() else None

    def read_notes(self, count: int = 3) -> SkillReply:
        """Newest notes: three spoken, ten on screen."""
        notes = self.notes.recent(10)
        if not notes:
            return SkillReply("Belum ada catatan.")
        spoken = join_words([text for _, text in notes[:count]])
        detail = "\n".join(f"{stamp}  {text}" for stamp, text in notes)
        return SkillReply(f"Catatan terbaru: {spoken}.", detail=detail, data={"catatan": [text for _, text in notes]})

    def open_notes(self) -> SkillReply:
        """Open data/notes.md in the default editor."""
        if not self.notes.path.exists():
            self.notes.path.parent.mkdir(parents=True, exist_ok=True)
            self.notes.path.write_text("# Catatan Mika\n\n", encoding="utf-8")
        if self.open_path is None:
            return SkillReply("Mika belum bisa membuka file catatan.", ok=False)
        self.open_path(self.notes.path)
        return SkillReply("Oke, Mika bukain catatanmu.")


def _timer_label(text: str, span: tuple[int, int] | None) -> str:
    """"pasang timer 5 menit buat masak mie" → "masak mie"."""
    remaining = remove_spans(text, [span]) if span else text
    label = re.sub(r"\s+", " ", _TIMER_WORDS.sub(" ", remaining)).strip()
    return reminder_message(label)


def build_skill_hub(config: dict[str, Any], *, open_path: Callable[[Path], Any] | None = None) -> SkillHub:
    """Default services; files go to data/ (git-ignored) or config["data_dir"]."""
    data_dir = Path(config.get("data_dir") or DATA_DIR)
    reminder_config = config.get("reminders", {})
    return SkillHub(
        reminders=ReminderService(
            data_dir / "reminders.json",
            missed_grace_hours=float(reminder_config.get("missed_grace_hours", 12)),
        ),
        weather=WeatherService(config),
        media=MediaControl(),
        volume=VolumeControl(),
        system=SystemInfo(),
        notes=NotesStore(data_dir / "notes.md"),
        open_path=open_path,
        volume_step=int(config.get("volume", {}).get("step_percent", 10)),
        snooze_minutes=int(reminder_config.get("snooze_minutes", 5)),
    )
