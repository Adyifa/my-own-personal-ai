from __future__ import annotations

import json
import time
from datetime import timedelta

from mika.skills.reminders import ReminderService
from tests.conftest import NOW
from tests.fakes import FakeClock


def make(tmp_path, clock=None, **kwargs):
    fired = []
    clock = clock or FakeClock(NOW)
    service = ReminderService(tmp_path / "reminders.json", clock=clock, on_due=lambda item, late: fired.append((item.message, late)), **kwargs)
    return service, clock, fired


def test_reminders_survive_a_restart(tmp_path):
    service, clock, _ = make(tmp_path)
    service.add("reminder", "minum obat", NOW + timedelta(hours=9))
    service.add("timer", "masak", NOW + timedelta(minutes=5), seconds=300)

    reloaded, _, _ = make(tmp_path, clock)
    assert [(item.kind, item.message) for item in reloaded.upcoming()] == [("timer", "masak"), ("reminder", "minum obat")]
    assert reloaded.upcoming()[0].due.utcoffset() == timedelta(hours=7)  # timezone kept


def test_check_fires_due_items_once(tmp_path):
    service, clock, fired = make(tmp_path)
    service.add("timer", "teh", NOW + timedelta(minutes=3), seconds=180)
    service.add("reminder", "meeting", NOW + timedelta(hours=1))
    assert service.check() == []
    clock.advance(minutes=3)
    service.check()
    service.check()
    assert fired == [("teh", False)]
    assert [item.message for item in service.upcoming()] == ["meeting"]
    assert json.loads((tmp_path / "reminders.json").read_text(encoding="utf-8"))[0]["message"] == "meeting"


def test_missed_while_off_is_announced_late_and_old_ones_dropped(tmp_path):
    service, clock, _ = make(tmp_path)
    service.add("reminder", "minum obat", NOW + timedelta(hours=1))
    service.add("reminder", "kemarin", NOW - timedelta(hours=20))

    clock.advance(hours=3)  # laptop was off
    restarted, _, fired = make(tmp_path, clock)
    restarted.check()
    assert fired == [("minum obat", True)]
    assert restarted.upcoming() == []


def test_cancel_by_name_all_or_soonest(tmp_path):
    service, _, _ = make(tmp_path)
    for minutes, label in [(5, "teh"), (10, "mie"), (20, "nasi")]:
        service.add("timer", label, NOW + timedelta(minutes=minutes), seconds=minutes * 60)
    service.add("reminder", "minum obat", NOW + timedelta(hours=2))

    assert [item.message for item in service.cancel(("timer",), query="mie")] == ["mie"]
    assert [item.message for item in service.cancel(("timer",))] == ["teh"]
    assert [item.message for item in service.cancel(("timer",), query="nasy")] == ["nasi"]  # fuzzy
    assert service.cancel(("timer",)) == []
    assert [item.message for item in service.cancel(("reminder",), everything=True)] == ["minum obat"]


def test_corrupt_file_does_not_crash(tmp_path):
    (tmp_path / "reminders.json").write_text("{not json", encoding="utf-8")
    service, _, _ = make(tmp_path)
    assert service.upcoming() == []


def test_background_thread_fires(tmp_path):
    clock = FakeClock(NOW)
    service, _, fired = make(tmp_path, clock)
    service.add("timer", "cepat", NOW + timedelta(seconds=1), seconds=1)
    service.start(interval=0.01)
    clock.advance(seconds=2)
    deadline = time.time() + 2
    while not fired and time.time() < deadline:
        time.sleep(0.01)
    service.stop()
    assert fired == [("cepat", False)]
