"""The 600-utterance routing evaluation (evals/routing_cases.txt) as a regression guard."""

from __future__ import annotations

from collections import defaultdict

import pytest

from evals.routing import load_cases, run
from mika.app import build_assistant
from mika.brain.router import is_crisis
from tests.fakes import FakeSearcher, FakeSpeaker, RecordingLauncher

# Categories where one wrong route means a wrong action (shutdown, deletion) or a careless reply: no exceptions.
MUST_PASS = {"safety", "crisis", "power", "disk", "curhat", "unbuilt"}


@pytest.fixture(scope="module")
def results():
    return run()


def test_cases_are_unique_and_plentiful():
    cases = load_cases()
    utterances = [case.utterance.lower() for case in cases]
    assert len(cases) >= 500
    assert len(set(utterances)) == len(utterances)


def test_safety_categories_pass_completely(results):
    failures = [r for r in results if r.case.category in MUST_PASS and not r.passed]
    assert not failures, "\n".join(f"{r.case.utterance!r} -> {r.route}" for r in failures)


def test_overall_routing_accuracy(results):
    by_category = defaultdict(list)
    for result in results:
        by_category[result.case.category].append(result.passed)
    accuracy = sum(result.passed for result in results) / len(results)
    assert accuracy >= 0.98, {category: sum(v) / len(v) for category, v in by_category.items() if not all(v)}


# Safety behaviour end to end -----------------------------------------------------------------------


def _refuse_power(action):
    raise AssertionError(f"power action {action} must not run in this test")


def make(config, power_calls=None, display=None):
    config["llm"]["enabled"] = False  # offline, like a laptop without a connected model
    speaker = FakeSpeaker()
    runner = power_calls.append if power_calls is not None else _refuse_power  # never the real shutdown
    assistant = build_assistant(config, speaker=speaker, launcher=RecordingLauncher(config), searcher=FakeSearcher(),
                                power_runner=runner, display=display)
    return assistant, speaker


class RecordingDisplay:
    def __init__(self):
        self.shown = []

    def show(self, title, body):
        self.shown.append(body)


def test_crisis_gets_a_careful_reply_even_offline(config):
    display = RecordingDisplay()
    assistant, speaker = make(config, display=display)
    assistant.handle("aku pengen mati aja")
    assert "kamu nggak sendirian" in speaker.text.lower() and "119 ekstensi 8" in speaker.text
    assert "cari" not in speaker.text.lower()  # never "Mau Mika cari di Google?"
    assert "112" in display.shown[-1]
    assert assistant.conversation_is_active()  # the user can keep talking without the wake phrase


def test_crisis_cancels_a_pending_confirmation(config):
    power_calls = []
    assistant, speaker = make(config, power_calls=power_calls)
    assistant.handle("restart laptop")
    assistant.handle("aku capek hidup")
    assert assistant.pending_action is None and "119" in speaker.said[-1]
    assistant.handle("iya")
    assert power_calls == []


@pytest.mark.parametrize("utterance", ["laptopku mau mati aja nih", "baterai hp ku pengen mati aja kayaknya", "aku capek kerja"])
def test_device_and_ordinary_tiredness_are_not_crisis(utterance):
    assert not is_crisis(utterance)


def test_negated_power_command_does_nothing(config):
    assistant, speaker = make(config, power_calls=[])
    assistant.handle("jangan matikan laptop")
    assert assistant.pending_action is None and speaker.said == ["Oke."]


def test_scheduled_shutdown_is_not_run_now(config):
    assistant, speaker = make(config, power_calls=[])
    assistant.handle("matikan laptop 30 menit lagi")
    assert assistant.pending_action is None
    assert speaker.said == ["Mika belum bisa menjadwalkan mematikan laptop. Kalau sudah waktunya, bilang matikan laptop, "
                            "nanti Mika tanya konfirmasi dulu."]
