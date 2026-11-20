"""Stage B: curhat mode. Local model only, listening rules, no tools, and curhat stays out of cloud requests."""

from __future__ import annotations

import time

import pytest

from mika.app import build_assistant
from mika.brain.llm import build_private_llm
from mika.brain.llm.base import ProviderUnavailable
from mika.brain.llm.ollama import OllamaProvider
from mika.brain.llm.openai_compat import OpenAICompatProvider
from mika.brain.prompts import build_system_prompt
from mika.persona import CONVERSATION_REPLIES
from tests.fakes import FakeSearcher, FakeSpeaker, RecordingLauncher, ScriptedLLM, text

LISTEN = "Kedengarannya capek banget ya. Bagian mana yang paling berat buat kamu?"
NO_LOCAL_MODEL = "Otak AI lokal Mika belum aktif, jadi untuk sekarang Mika cuma bisa dengerin."


def make(config, *, llm=None, private=None, hub=None):
    speaker = FakeSpeaker()
    assistant = build_assistant(config, speaker=speaker, launcher=RecordingLauncher(config), searcher=FakeSearcher(),
                                llm=llm if llm is not None else ScriptedLLM(), private_llm=private, hub=hub)
    return assistant, speaker


def system_prompt(call) -> str:
    return call["messages"][0].content


def spoken_history(call) -> str:
    return " ".join(message.content for message in call["messages"][1:])


def test_curhat_goes_to_the_local_model_with_listening_rules_and_no_tools(config):
    cloud, local = ScriptedLLM(), ScriptedLLM(text(LISTEN))
    assistant, speaker = make(config, llm=cloud, private=local)
    assistant.handle("halo mika aku capek banget sama kerjaan")
    assert speaker.text == LISTEN  # spoken sentence by sentence
    assert cloud.calls == []
    assert local.calls[0]["tools"] is None  # no web search or app opening in the middle of a story
    assert "Mode curhat" in system_prompt(local.calls[0]) and "bukan psikolog" in system_prompt(local.calls[0])


def test_follow_ups_stay_curhat_until_the_window_ends(config):
    cloud = ScriptedLLM(text("Canberra."))
    local = ScriptedLLM(text(LISTEN), text("Itu pasti bikin kamu ngerasa sendirian."))
    assistant, speaker = make(config, llm=cloud, private=local)
    assistant.handle("aku berantem sama pacar semalam")
    assistant.handle("dia nggak pernah dengerin aku")  # on its own just a sentence; inside curhat, part of the story
    assert len(local.calls) == 2 and cloud.calls == []
    assert assistant.conversation_until >= time.time() + 40  # a longer listening window than the usual 18 s
    assistant.curhat_until = 0.0  # the story is over
    assistant.handle("ibu kota australia apa")
    assert len(cloud.calls) == 1 and cloud.calls[0]["tools"]  # back to normal, tools offered again


def test_commands_still_work_during_curhat(config, everyday):
    local = ScriptedLLM(text(LISTEN))
    assistant, speaker = make(config, private=local, hub=everyday.hub)
    assistant.handle("aku capek banget sama kerjaan")
    assistant.handle("pasang timer 5 menit")
    assert speaker.said[-1] == "Oke, timer 5 menit mulai sekarang."
    assert len(local.calls) == 1


def test_curhat_never_rides_along_to_a_cloud_model(config):
    cloud = ScriptedLLM(text("Canberra."))  # a scripted model does not claim to be local, so it counts as cloud
    local = ScriptedLLM(text(LISTEN))
    assistant, _ = make(config, llm=cloud, private=local)
    assistant.handle("pacarku selingkuh sama sahabatku")
    assistant.curhat_until = 0.0
    assistant.handle("ibu kota australia apa")
    assert "selingkuh" not in spoken_history(cloud.calls[0])


def test_curhat_history_is_kept_for_a_local_model(config):
    local = ScriptedLLM(text(LISTEN), text("Iya, aku ingat."))
    local.local = True  # the whole default chain runs on this laptop
    assistant, _ = make(config, llm=local, private=local)
    assistant.handle("pacarku selingkuh sama sahabatku")
    assistant.curhat_until = 0.0
    assistant.handle("tadi aku cerita apa ya")
    assert "selingkuh" in spoken_history(local.calls[1])


def test_without_a_local_model_mika_says_so_once_and_listens(config):
    assistant, speaker = make(config)
    assistant.private_llm = None  # Ollama not installed and cloud not allowed for curhat
    assistant.handle("aku capek banget sama kerjaan")
    assert speaker.said[0] == NO_LOCAL_MODEL and speaker.said[1] in CONVERSATION_REPLIES["cute"]["curhat_work"]
    assistant.handle("bos aku marah marah terus")
    assert speaker.said.count(NO_LOCAL_MODEL) == 1
    assert assistant.conversation_is_active()


def test_failing_local_model_falls_back_to_listening(config):
    local = ScriptedLLM([ProviderUnavailable("Ollama tidak bisa dihubungi")])
    assistant, speaker = make(config, private=local)
    assistant.handle("aku ngerasa gagal")
    assert speaker.said[0] == NO_LOCAL_MODEL and speaker.said[1] in CONVERSATION_REPLIES["cute"]["curhat_feeling"]


def test_conversation_stop_ends_curhat_mode(config):
    assistant, _ = make(config, private=ScriptedLLM(text(LISTEN)))
    assistant.handle("aku berantem sama ibu")
    assistant.handle("selesai ngobrol")
    assert assistant.curhat_until == 0.0 and len(assistant.agent.session) == 0


def test_after_a_crisis_reply_the_conversation_continues_as_curhat(config):
    local = ScriptedLLM(text("Aku di sini. Kamu nggak sendirian."))
    assistant, speaker = make(config, private=local)
    assistant.handle("aku pengen mati aja")
    assistant.handle("semuanya terasa berantakan")
    assert speaker.text.endswith("Aku di sini. Kamu nggak sendirian.")
    assert "pengen mati" in spoken_history(local.calls[0])  # the local model sees what came before


# The local-only chain ------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_env_override(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)


def test_private_chain_keeps_only_local_models(config):
    chain = build_private_llm(config)
    assert [provider.name for provider in chain.providers] == ["ollama"] and chain.local
    config["companion"]["allow_cloud"] = True
    assert [provider.name for provider in build_private_llm(config).providers] == ["ollama", "openai"]
    config["companion"]["allow_cloud"] = False
    config["llm"]["providers"] = ["openai"]
    assert build_private_llm(config) is None


@pytest.mark.parametrize(
    ("provider", "local"),
    [
        (OllamaProvider({}), True),
        (OllamaProvider({"base_url": "http://192.168.1.20:11434"}), False),
        (OpenAICompatProvider({}), False),
        (OpenAICompatProvider({"base_url": "http://localhost:1234/v1"}), True),  # LM Studio
    ],
)
def test_providers_know_whether_they_are_local(provider, local):
    assert provider.local is local


def test_curhat_prompt_only_in_curhat_mode(config):
    config["safety"]["crisis_call"] = "telepon 119 ekstensi 8"
    curhat = build_system_prompt(config, mode="curhat")
    assert "Mode curhat" in curhat and "telepon 119 ekstensi 8" in curhat
    assert "Mode curhat" not in build_system_prompt(config)
