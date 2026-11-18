"""End-to-end: utterance in → route → actions and speech out, with every device faked."""

from __future__ import annotations

import pytest

from mika.app import build_assistant
from mika.assistant import Assistant
from mika.brain.llm.base import ProviderUnavailable
from mika.persona import CONVERSATION_REPLIES
from tests.fakes import FakeSearcher, ScriptedLLM, make_result, text, tool


class RecordingDisplay:
    def __init__(self):
        self.shown = []

    def show(self, title, body):
        self.shown.append((title, body))


@pytest.fixture
def power_calls():
    return []


def make(config, speaker, launcher, llm=None, *, searcher=None, power_calls=None, display=None):
    return build_assistant(
        config,
        speaker=speaker,
        display=display,
        llm=llm if llm is not None else ScriptedLLM(),
        searcher=searcher or FakeSearcher(),
        launcher=launcher,
        power_runner=power_calls.append if power_calls is not None else _refuse_power,
    )


def _refuse_power(action):
    raise AssertionError(f"power action {action} must not run in this test")


def test_buka_youtube_takes_the_fast_path(config, speaker, launcher):
    llm = ScriptedLLM()
    assistant = make(config, speaker, launcher, llm)
    assert assistant.handle("halo mika buka youtube") is True
    assert launcher.opened_urls == ["https://www.youtube.com"]
    assert speaker.said == ["Oke, Mika bukain youtube ya."]
    assert llm.calls == []  # never waits for the model


def test_question_goes_to_the_agent_and_opens_follow_up_window(config, speaker, launcher):
    llm = ScriptedLLM(text("Ibu kota Indonesia sekarang masih Jakarta secara hukum."))
    assistant = make(config, speaker, launcher, llm)
    assistant.handle("halo mika ibu kota indonesia apa")
    assert speaker.said == ["Ibu kota Indonesia sekarang masih Jakarta secara hukum."]
    assert llm.calls[0]["messages"][-1].content == "ibu kota indonesia apa"
    assert assistant.conversation_is_active()


def test_typed_input_keeps_original_wording_for_the_llm(config, speaker, launcher):
    llm = ScriptedLLM(text("Boleh."))
    assistant = make(config, speaker, launcher, llm)
    assistant.handle("Aku mau tahu, siapa penemu telepon?")
    assert llm.calls[0]["messages"][-1].content == "Aku mau tahu, siapa penemu telepon?"


def test_cari_dan_bacakan_with_sources_on_screen(config, speaker, launcher):
    searcher = FakeSearcher([make_result(1, "Kompas"), make_result(2, "detikcom")])
    llm = ScriptedLLM(
        tool("web_search", query="resep rendang"),
        text("Menurut Kompas, rendang dimasak lama dengan santan. [DETAIL] Bahan: daging, santan, bumbu."),
    )
    display = RecordingDisplay()
    assistant = make(config, speaker, launcher, llm, searcher=searcher, display=display)

    assistant.handle("halo mika cari resep rendang")
    assert assistant.last_route.intent == "web_answer"
    assert searcher.queries == ["resep rendang"]
    assert speaker.said == ["Bentar, Mika cariin dulu ya.", "Menurut Kompas, rendang dimasak lama dengan santan."]
    assert launcher.opened_urls == []
    title, body = display.shown[0]
    assert "Bahan: daging" in body and "1. Kompas - Judul 1" in body and "https://example1.com/artikel" in body


def test_offline_llm_falls_back_to_old_behaviour(config, speaker, launcher):
    down = ScriptedLLM(*[[ProviderUnavailable("ollama mati")] for _ in range(3)])
    assistant = make(config, speaker, launcher, down)

    assistant.handle("apa kabar")
    assert speaker.said[-1] in CONVERSATION_REPLIES["cute"]["how_are_you"]

    assistant.handle("cari resep rendang")
    assert launcher.opened_urls == ["https://www.google.com/search?q=resep+rendang"]

    assistant.handle("jelaskan teori relativitas")
    assert speaker.said[-1] in CONVERSATION_REPLIES["cute"]["unknown_chat"]


def test_llm_disabled_never_builds_an_agent(config, speaker, launcher):
    config["llm"]["enabled"] = False
    assistant = make(config, speaker, launcher)
    assert assistant.agent is None
    assistant.handle("apa kabar")
    assert speaker.said[-1] in CONVERSATION_REPLIES["cute"]["how_are_you"]


def test_power_command_needs_voice_confirmation(config, speaker, launcher, power_calls):
    assistant = make(config, speaker, launcher, power_calls=power_calls)
    assistant.handle("halo mika matikan laptop")
    assert power_calls == []
    assert assistant.pending_action is not None
    assistant.handle("buka youtube")  # anything but yes/no keeps waiting
    assert launcher.opened_urls == [] and "nunggu" in speaker.said[-1]
    assistant.handle("iya")
    assert power_calls == ["shutdown"]
    assert speaker.said[-1] == "Siap, laptop akan dimatikan."


def test_agent_power_request_is_cancelled_by_voice(config, speaker, launcher, power_calls):
    llm = ScriptedLLM(tool("system_power", action="restart"))
    assistant = make(config, speaker, launcher, llm, power_calls=power_calls)
    assistant.handle("tolong restart dong habis update")
    assert assistant.pending_action is not None and power_calls == []
    assert not assistant.conversation_is_active()
    assistant.handle("batal")
    assert power_calls == [] and assistant.pending_action is None


def test_agent_power_request_runs_after_yes(config, speaker, launcher, power_calls):
    llm = ScriptedLLM(tool("system_power", action="sleep"))
    assistant = make(config, speaker, launcher, llm, power_calls=power_calls)
    assistant.handle("aku mau tidurin laptopnya")
    assistant.handle("iya")
    assert power_calls == ["sleep"]


def test_expired_confirmation_does_nothing(config, speaker, launcher, power_calls):
    config["safety"]["confirmation_seconds"] = -1
    assistant = make(config, speaker, launcher, power_calls=power_calls)
    assistant.handle("restart laptop")
    assistant.handle("iya")
    assert power_calls == []


def test_stop_returns_false(config, speaker, launcher):
    assistant = make(config, speaker, launcher)
    assert assistant.handle("halo mika keluar") is False


def test_conversation_stop_clears_context(config, speaker, launcher):
    llm = ScriptedLLM(text("Halo juga."))
    assistant = make(config, speaker, launcher, llm)
    assistant.handle("hai, aku Budi")
    assert len(assistant.agent.session) == 1
    assistant.handle("selesai ngobrol")
    assert len(assistant.agent.session) == 0 and not assistant.conversation_is_active()


def test_assistant_constructor_is_backwards_compatible(config, speaker):
    assistant = Assistant(config, speaker)
    assert assistant.agent is None and assistant.name == "Mika"


def test_legacy_entry_point_exports():
    import assistant as legacy

    for name in ("Assistant", "Speaker", "ensure_config", "listen_once", "CONFIG_PATH", "DEFAULT_CONFIG", "main"):
        assert hasattr(legacy, name)
