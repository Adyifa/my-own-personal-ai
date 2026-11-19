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


def make(config, speaker, launcher, llm=None, *, searcher=None, power_calls=None, display=None, hub=None):
    return build_assistant(
        config,
        speaker=speaker,
        display=display,
        llm=llm if llm is not None else ScriptedLLM(),
        searcher=searcher or FakeSearcher(),
        launcher=launcher,
        power_runner=power_calls.append if power_calls is not None else _refuse_power,
        hub=hub,
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


# Everyday skills end to end (stage 2) ------------------------------------------------------


def test_timer_is_instant_and_offline(config, speaker, launcher, everyday):
    llm = ScriptedLLM()
    assistant = make(config, speaker, launcher, llm, hub=everyday.hub)
    assistant.handle("halo mika pasang timer lima menit")
    assert speaker.said == ["Oke, timer 5 menit mulai sekarang."]
    assert len(everyday.hub.reminders.upcoming(("timer",))) == 1
    assert llm.calls == []


def test_follow_up_question_needs_no_wake_word(config, speaker, launcher, everyday):
    assistant = make(config, speaker, launcher, hub=everyday.hub)
    assistant.handle("halo mika ingatkan aku minum obat")
    assert speaker.said[-1] == "Mau diingatkan kapan?"
    assert assistant.conversation_is_active()  # tray listens without "Halo Mika"
    assistant.handle("jam sembilan malam")
    assert speaker.said[-1] == "Oke, Mika ingatkan minum obat jam 9 malam."


def test_unrelated_answer_cancels_the_follow_up(config, speaker, launcher, everyday):
    llm = ScriptedLLM(text("Jam 9 malam kenapa?"))
    assistant = make(config, speaker, launcher, llm, hub=everyday.hub)
    assistant.handle("ingatkan aku minum obat")
    assistant.handle("buka youtube")
    assert launcher.opened_urls == ["https://www.youtube.com"]
    assistant.handle("jam 9 malam")  # the question was dropped, so this goes to the LLM instead
    assert everyday.hub.reminders.upcoming() == []
    assert speaker.said[-1] == "Jam 9 malam kenapa?"


def test_due_timer_is_announced(config, speaker, launcher, everyday):
    display = RecordingDisplay()
    assistant = make(config, speaker, launcher, hub=everyday.hub, display=display)
    assistant.handle("timer 3 menit buat teh")
    everyday.clock.advance(minutes=3)
    everyday.hub.reminders.check()
    assert speaker.said[-1] == "Timer teh sudah selesai!"
    assert display.shown[-1] == ("Pengingat", "Timer teh sudah selesai!")
    assistant.handle("tunda 2 menit")
    assert speaker.said[-1] == "Oke, Mika ingatkan lagi 2 menit lagi."


def test_mute_runs_after_speaking(config, speaker, launcher, everyday):
    assistant = make(config, speaker, launcher, hub=everyday.hub)
    assistant.handle("matikan suara")
    assert speaker.said[-1] == "Oke, suara Mika bisukan." and everyday.endpoint.muted == 1


def test_weather_details_go_to_screen(config, speaker, launcher, everyday):
    display = RecordingDisplay()
    assistant = make(config, speaker, launcher, hub=everyday.hub, display=display)
    assistant.handle("halo mika cuaca besok di bandung")
    assert speaker.said[-1].startswith("Besok di Bandung diperkirakan badai petir")
    assert "Cuaca Bandung, Jawa Barat" in display.shown[-1][1]


def test_agent_can_set_reminders_with_our_time_parser(config, speaker, launcher, everyday):
    llm = ScriptedLLM(tool("reminders", action="set", when="30 menit lagi", message="angkat jemuran"))
    assistant = make(config, speaker, launcher, llm, hub=everyday.hub)
    assistant.handle("eh nanti setengah jam lagi kasih tahu aku buat angkat jemuran ya")
    assert speaker.said[-1] == "Oke, 30 menit lagi Mika ingatkan angkat jemuran."
    assert llm.calls and len(llm.calls) == 1  # skill reply is spoken directly, no 2nd LLM call
    assert everyday.hub.reminders.upcoming()[0].message == "angkat jemuran"


def test_agent_bad_time_is_reported_back_to_the_model(config, speaker, launcher, everyday):
    llm = ScriptedLLM(tool("reminders", action="set", when="kapan-kapan"), text("Mau diingatkan jam berapa?"))
    assistant = make(config, speaker, launcher, llm, hub=everyday.hub)
    assistant.handle("tolong kabari aku kapan-kapan buat olahraga")
    assert len(llm.calls) == 2
    assert speaker.said[-1] == "Mau diingatkan jam berapa?"


# Barge-in and latency (stage 3) --------------------------------------------------------------


def test_interrupt_cancels_the_running_agent_turn(config, speaker, launcher):
    assistant = None

    class BargeInLLM(ScriptedLLM):
        def stream_chat(self, messages, tools=None, **kwargs):
            yield from text("Ini kalimat pertama. ", "Lalu")[:-1]  # "Lalu" completes the first sentence
            assistant.interrupt()  # the barge-in thread fires while the model is still writing
            yield from text(" kalimat ini tidak boleh terdengar.")

    assistant = make(config, speaker, launcher, BargeInLLM())
    assistant.handle("ceritakan sejarah indonesia")
    assert speaker.said == ["Ini kalimat pertama."]
    assert speaker.stopped
    assert assistant.latency.entries[-1]["interrupted"] is True


def test_latency_is_measured_from_end_of_speech(config, speaker, launcher):
    import json
    from pathlib import Path

    from mika.audio.voice import Heard

    speaker.first_audio_at = None
    assistant = make(config, speaker, launcher)
    heard = Heard("halo mika buka youtube", speech_end_at=100.0, stt_seconds=0.42, engine="whisper")

    original_mark = speaker.mark_turn

    def mark_turn():
        original_mark()
        speaker.first_audio_at = 100.9  # pretend audio started 0.9 s after the user stopped talking

    speaker.mark_turn = mark_turn
    assistant.handle("halo mika buka youtube", heard=heard)
    entry = assistant.latency.entries[-1]
    assert entry["route"] == "rule:open_website"
    assert (entry["stt_engine"], entry["stt_s"], entry["first_audio_s"]) == ("whisper", 0.42, 0.9)
    logged = Path(config["data_dir"], "latency.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(logged[-1])["first_audio_s"] == 0.9


def test_stop_during_a_skill_reply_cancels_its_action(config, speaker, launcher, everyday):
    assistant = make(config, speaker, launcher, hub=everyday.hub)
    original_say = speaker.say

    def say_and_get_interrupted(text):
        original_say(text)
        assistant.interrupt()  # user: "stop" while Mika says "Oke, suara Mika bisukan."

    speaker.say = say_and_get_interrupted
    assistant.handle("matikan suara")
    assert everyday.endpoint.muted == 0
