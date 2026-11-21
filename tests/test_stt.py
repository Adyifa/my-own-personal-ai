from __future__ import annotations

from types import SimpleNamespace

import pytest

from mika.audio.stt import GoogleSTT, WhisperSTT, build_stt, choose_whisper_device, hallucination_reason
from mika.audio.vad import Utterance


def utterance(seconds: float = 1.5) -> Utterance:
    return Utterance(bytes(int(seconds * 32000)), started_at=1.0, speech_end_at=2.5)


@pytest.mark.parametrize(
    ("requested", "gpu_free", "local_llm", "llm_loaded", "expected"),
    [
        ("cpu", 12000, True, False, "cpu"),
        ("cuda", None, True, False, "cuda"),
        ("auto", None, True, False, "cpu"),  # no NVIDIA GPU
        ("auto", 3961, True, False, "cpu"),  # this laptop: qwen3:4b needs the 4 GB card
        ("auto", 3961, False, False, "cuda"),  # cloud LLM only: Whisper can have the GPU
        ("auto", 600, True, True, "cpu"),  # Ollama already loaded, little VRAM left
        ("auto", 9000, True, True, "cuda"),
        ("auto", 12000, True, False, "cuda"),  # big GPU: room for both
    ],
)
def test_choose_whisper_device(requested, gpu_free, local_llm, llm_loaded, expected):
    device, compute, reason = choose_whisper_device(
        requested, "small", gpu_free=gpu_free, local_llm=local_llm, llm_loaded=llm_loaded, llm_reserve_mb=3300
    )
    assert device == expected
    assert compute == ("int8" if device == "cpu" else "int8_float16")
    assert reason


@pytest.mark.parametrize(
    ("text", "no_speech", "logprob", "seconds", "dropped"),
    [
        ("Terima kasih telah menonton!", 0.5, -0.4, 2.0, True),
        ("Terima kasih.", 0.05, -0.2, 1.2, False),  # a real "thank you" is kept
        ("Subtitle oleh Amara.org", 0.0, -0.1, 3.0, True),
        ("Halo Mika, buka YouTube.", 0.02, -0.3, 1.8, False),
        ("ya ya ya ya ya ya ya", 0.1, -0.5, 2.0, True),
        ("hmm", 0.8, -1.4, 0.5, True),
        ("", 0.0, 0.0, 1.0, True),
    ],
)
def test_hallucination_filter(text, no_speech, logprob, seconds, dropped):
    assert bool(hallucination_reason(text, no_speech, logprob, seconds)) is dropped


class FakeWhisperModel:
    def __init__(self, segments):
        self.segments = segments
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append((audio, kwargs))
        return iter(self.segments), SimpleNamespace(language="id")


def segment(text, no_speech=0.02, logprob=-0.3):
    return SimpleNamespace(text=text, no_speech_prob=no_speech, avg_logprob=logprob)


def make_whisper(config, model, devices=None, fail_on_cuda=False, gpu_free=None, llm_loaded=False):
    created = devices if devices is not None else []

    def factory(name, **kwargs):
        created.append((name, kwargs["device"], kwargs["compute_type"]))
        if fail_on_cuda and kwargs["device"] == "cuda":
            raise RuntimeError("cublas64_12.dll not found")
        return model

    return WhisperSTT(config, model_factory=factory, gpu_probe=lambda: gpu_free, llm_probe=lambda: llm_loaded)


def test_whisper_transcribes_in_indonesian_greedily(config):
    model = FakeWhisperModel([segment(" Halo Mika,"), segment(" buka YouTube.")])
    stt = make_whisper(config, model)
    result = stt.transcribe(utterance())
    assert (result.text, result.engine, result.dropped) == ("Halo Mika buka YouTube", "whisper", "")  # punctuation stripped
    audio, kwargs = model.calls[0]
    assert audio.dtype.name == "float32" and audio.size == 24000  # 1.5 s at 16 kHz
    assert kwargs["language"] == "id" and kwargs["beam_size"] == 1 and kwargs["vad_filter"] is False
    assert "Mika" in kwargs["initial_prompt"]


def test_whisper_drops_silence_hallucination(config):
    stt = make_whisper(config, FakeWhisperModel([segment("Terima kasih telah menonton.", no_speech=0.7, logprob=-1.2)]))
    result = stt.transcribe(utterance())
    assert result.text == ""
    assert "hening" in result.dropped


def test_whisper_loads_once_on_cpu_next_to_local_llm(config):
    devices = []
    stt = make_whisper(config, FakeWhisperModel([segment("halo")]), devices=devices, gpu_free=3961)
    stt.warm_up()
    stt.transcribe(utterance())
    stt.transcribe(utterance())
    assert devices == [("small", "cpu", "int8")]
    assert "VRAM tidak cukup" in stt.device_reason


def test_whisper_falls_back_to_cpu_when_cuda_libraries_are_missing(config):
    config["stt"]["whisper"]["device"] = "cuda"
    devices = []
    stt = make_whisper(config, FakeWhisperModel([segment("halo")]), devices=devices, fail_on_cuda=True)
    assert stt.transcribe(utterance()).text == "halo"
    assert [device for _, device, _ in devices] == ["cuda", "cpu"]
    assert stt.device == "cpu"


class CudaLibsMissingModel(FakeWhisperModel):
    """Like CTranslate2 on a machine without cuBLAS: creating the model works, the first decode fails."""

    def transcribe(self, audio, **kwargs):
        raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")


def test_missing_cuda_libraries_are_caught_at_load_time(config):
    devices = []
    cpu_model = FakeWhisperModel([segment("halo")])

    def factory(name, **kwargs):
        devices.append(kwargs["device"])
        return CudaLibsMissingModel([]) if kwargs["device"] == "cuda" else cpu_model

    config["stt"]["whisper"]["llm_vram_reserve_mb"] = 3300  # pinned: this test is about the CUDA failure, not the reserve
    stt = WhisperSTT(config, model_factory=factory, gpu_probe=lambda: 3961, llm_probe=lambda: False)
    stt.model_name = "tiny"  # small enough that "auto" picks the GPU next to the LLM reserve
    assert stt.transcribe(utterance()).text == "halo"
    assert devices == ["cuda", "cpu"] and stt.device == "cpu" and "GPU gagal" in stt.device_reason


def test_cuda_failure_during_use_moves_to_cpu_and_retries(config):
    config["stt"]["whisper"]["device"] = "cuda"
    devices = []
    gpu_model = FakeWhisperModel([segment("x")])
    cpu_model = FakeWhisperModel([segment("buka youtube")])

    def factory(name, **kwargs):
        devices.append(kwargs["device"])
        return gpu_model if kwargs["device"] == "cuda" else cpu_model

    stt = WhisperSTT(config, model_factory=factory, gpu_probe=lambda: None)
    stt.warm_up()  # the probe passes, e.g. the driver breaks later
    gpu_model.transcribe = CudaLibsMissingModel([]).transcribe
    assert stt.transcribe(utterance()).text == "buka youtube"
    assert devices == ["cuda", "cpu"] and stt.device == "cpu"


def test_google_stt(monkeypatch):
    sr = pytest.importorskip("speech_recognition")

    class Recognizer:
        def __init__(self, result):
            self.result = result

        def recognize_google(self, audio, language):
            assert audio.sample_rate == 16000 and language == "id-ID"
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

    assert GoogleSTT(recognizer=Recognizer("buka youtube")).transcribe(utterance()).text == "buka youtube"
    unknown = GoogleSTT(recognizer=Recognizer(sr.UnknownValueError())).transcribe(utterance())
    assert unknown.text == "" and unknown.dropped
    offline = GoogleSTT(recognizer=Recognizer(sr.RequestError("no internet"))).transcribe(utterance())
    assert "Google" in offline.dropped


def test_build_stt_picks_engine(config):
    assert build_stt(config).name == "google"
    config["stt"]["engine"] = "whisper"
    pytest.importorskip("faster_whisper")
    assert build_stt(config).name == "whisper"
