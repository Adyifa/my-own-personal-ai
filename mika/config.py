"""Settings live in commands.json (Settings GUI); secrets such as API keys only in .env, so they never reach Git."""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

from .persona import VOICE_PERSONALITY_PRESETS
from .text import normalize


if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent.parent

CONFIG_PATH = APP_DIR / "commands.json"
ENV_PATH = APP_DIR / ".env"
DATA_DIR = APP_DIR / "data"
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

_HOME = Path.home().as_posix()


DEFAULT_CONFIG: dict[str, Any] = {
    "assistant_name": "Mika",
    "wake": {
        "enabled": True,
        "phrases": [
            "halo mika",
            "hai mika",
            "hey mika",
            "halo mica",
            "halo nika",
            "halo mikha",
            "halo zeta",
            "halo zetta",
            "halo seta",
            "halo jeta",
        ],
        "next_command_seconds": 8,
        "match_anywhere": True,
    },
    "voice": {
        "enabled": True,
        "provider": "edge",
        "edge_voice": "id-ID-GadisNeural",
        "edge_rate": "+12%",
        "edge_volume": "+0%",
        "edge_pitch": "+10Hz",
        "coqui_model": "tts_models/multilingual/multi-dataset/xtts_v2",
        "coqui_model_path": "",
        "coqui_config_path": "",
        "coqui_speaker_wav": "",
        "coqui_language": "id",
        "coqui_gpu": False,
        "rate": 185,
        "volume": 1.0,
        "name_contains": "",
    },
    "personality": {
        "preset": "cute",
        "confirm_prefix": "Siap",
        "not_found": "Mika belum nemu",
        "listening_reply": "Iya, Mika denger.",
        "empty_command": "Mika belum nangkep perintahnya.",
        "stop_reply": "Oke, Mika diem dulu ya.",
        "ask_target": "Mau Mika bukain apa?",
        "file_not_found": "Mika belum nemu file atau folder itu.",
        "confirm_question": "Yakin? Kalau iya bilang iya, kalau enggak bilang batal.",
        "confirm_expired": "Konfirmasinya kelewat. Mika batalin dulu, ya.",
        "confirm_cancelled": "Oke, Mika batalin.",
        "confirm_waiting": "Mika masih nunggu iya atau batal.",
        "open_reply": "Oke, Mika bukain {target} ya.",
        "open_website_reply": "Oke, Mika bukain website {target} ya.",
        "search_reply": "Sebentar, Mika cari {query} di {provider}.",
        "youtube_first_reply": "Mika bukain hasil YouTube paling cocok untuk {query}.",
        "music_reply": "Sebentar, Mika cariin {query} di Spotify.",
        "startup_reply": "Halo, aku {name}. Panggil aku dengan Halo Mika, lalu sebutin yang kamu mau.",
        "text_startup_reply": "Halo, aku {name}. Mode ketik aktif. Ketik bantuan kalau mau contoh perintah.",
    },
    "conversation": {
        "enabled": True,
        "continue_seconds": 18,
    },
    "safety": {
        "confirmation_seconds": 12,
        "yes_words": ["iya", "ya", "yes", "yup", "boleh", "lanjut", "gas", "oke"],
        "no_words": ["tidak", "nggak", "ga", "gak", "no", "batal", "jangan"],
    },
    "listen": {
        "language": "id-ID",
        "device_index": None,
        "timeout_seconds": 6,
        "phrase_time_limit_seconds": 8,
        "wake_timeout_seconds": 2,
        "wake_phrase_time_limit_seconds": 4,
        "command_timeout_seconds": 6,
        "command_phrase_time_limit_seconds": 8,
        "ambient_adjust_seconds": 0.15,
        "pause_threshold": 0.45,
        "non_speaking_duration": 0.2,
        "dynamic_energy_threshold": True,
        "energy_threshold": None,
    },
    "websites": {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "gmail": "https://mail.google.com",
        "chatgpt": "https://chatgpt.com",
    },
    "apps": {
        "notepad": "notepad.exe",
        "kalkulator": "calc.exe",
        "paint": "mspaint.exe",
    },
    "auto_discovery": {
        "enabled": True,
        "scan_start_menu": True,
        "scan_desktop": True,
        "scan_steam": True,
        "scan_store_apps": True,  # Microsoft Store apps via Get-StartApps (WhatsApp, Spotify, Settings, ...)
    },
    "games": {
        "counter strike": "steam://rungameid/730",
        "counter-strike": "steam://rungameid/730",
        "cs": "steam://rungameid/730",
        "cs2": "steam://rungameid/730",
        "cs 2": "steam://rungameid/730",
        "si es tu": "steam://rungameid/730",
        "si es 2": "steam://rungameid/730",
        "counter strike 2": "steam://rungameid/730",
    },
    "music": {
        "provider": "spotify",
        "open_mode": "web",
        "songs": {
            "malu malu": "Malu Malu Dia Indahkus",
        },
    },
    "search": {
        "default_provider": "google",
        # "answer": plain "cari X" is answered by voice (search + LLM); "browser": old behaviour, open Google.
        "plain_search_mode": "answer",
        "providers": {
            "google": "https://www.google.com/search?q={query}",
            "youtube": "https://www.youtube.com/results?search_query={query}",
            "youtube_first": "https://www.google.com/search?btnI=1&q=site%3Ayoutube.com%2Fwatch+{query}",
        },
    },
    "files": {
        "contoh dokumen": f"{_HOME}/Documents",
        "downloads": f"{_HOME}/Downloads",
    },
    "search_folders": [
        f"{_HOME}/Desktop",
        f"{_HOME}/Documents",
        f"{_HOME}/Downloads",
    ],
    "file_search": {
        "max_seconds": 5,
    },
    "llm": {
        "enabled": True,
        # Order is the fallback chain. Local first: free, private, and works without internet.
        "providers": ["ollama", "openai"],
        "temperature": 0.6,
        "max_output_tokens": 400,
        # After a provider fails, skip it for a while instead of paying its timeout on every turn.
        "failure_cooldown_seconds": 120,
        "warmup": True,
        "ollama": {
            # 127.0.0.1, not "localhost": on Windows "localhost" may try IPv6 first and add latency.
            "base_url": "http://127.0.0.1:11434",
            "model": "qwen3:4b",
            "think": False,
            "keep_alive": "30m",
            "num_ctx": 4096,
            "connect_timeout_seconds": 1.5,
            "read_timeout_seconds": 60,
        },
        "openai": {
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-5-mini",
            "api_key_env": "OPENAI_API_KEY",
            "base_url_env": "OPENAI_BASE_URL",
            "reasoning_effort": "minimal",
            "send_temperature": False,
            "max_tokens_param": "max_completion_tokens",
            "connect_timeout_seconds": 3,
            "read_timeout_seconds": 60,
        },
    },
    "agent": {
        "max_tool_steps": 4,
        "history_turns": 6,
        "session_idle_minutes": 15,
        "max_spoken_sentences": 3,
        "fast_action_replies": True,
    },
    "stt": {
        # "google": online, as before. "whisper": offline faster-whisper; no audio leaves the laptop.
        "engine": "google",
        "language": "id",
        "whisper": {
            "model": "small",
            "device": "auto",  # auto: GPU only if the local LLM still fits next to it, else CPU int8
            "compute_type": "auto",
            "beam_size": 1,
            "cpu_threads": 0,  # 0 = up to 8 threads
            "download_root": "",
            "llm_vram_reserve_mb": 3300,  # VRAM qwen3:4b needs with a 4k context
            "disable_xet": True,  # first model download over plain HTTP (Xet transfer stalled on some networks)
            "initial_prompt": "Percakapan santai dalam bahasa Indonesia dengan asisten suara bernama Mika.",
        },
        "vad": {
            "engine": "auto",  # webrtc if installed, else energy
            "aggressiveness": 2,
            "silence_ms": 0,  # 0 = use listen.pause_threshold
            "min_speech_ms": 250,
            "preroll_ms": 300,
            "max_utterance_seconds": 12,
        },
    },
    "barge_in": {
        # "off": ignore speech while Mika talks. "keyword": stop on stop/wake words, safe with laptop speakers.
        # "voice": any speech interrupts at once; use with headphones (speakers would trigger it).
        "mode": "keyword",
        "stop_words": ["stop", "berhenti", "diam", "cukup", "udah", "sudah", "skip", "stop mika", "mika diam"],
        "echo_similarity": 0.7,
        "tail_ms": 400,
    },
    "metrics": {
        "log_file": True,  # per-turn latency in data/latency.jsonl
    },
    "vision": {
        "ollama_model": "qwen2.5vl:3b",  # local vision model (~3 GB); swaps with the text model on a 4 GB GPU
        "openai_model": "gpt-5-mini",
        "allow_cloud": False,  # screenshots never leave the laptop unless this is switched on
        "max_side": 1280,
    },
    "clipboard": {
        "max_chars": 6000,  # ~1500-2000 tokens, fits the local model's 4k context
        "copy_translation": True,
    },
    "briefing": {
        "on_good_morning": True,  # "selamat pagi" before 11:00 gives the briefing
        "spoken_headlines": 2,
        "news_timeout_seconds": 4,
        "news_feeds": [
            "https://www.antaranews.com/rss/terkini.xml",
            "https://www.cnnindonesia.com/nasional/rss",
            "https://www.republika.co.id/rss",
            "https://www.cnbcindonesia.com/news/rss",
        ],
    },
    "memory": {
        "enabled": True,  # facts in data/memory.json, injected into the AI's context
        "agent_can_remember": True,  # the AI may save facts the user states (never after reading web/screen text)
    },
    "reminders": {
        "missed_grace_hours": 12,  # reminders missed while the laptop was off are announced if not older than this
        "snooze_minutes": 5,
        "chime": True,
    },
    "weather": {
        "location": "Jakarta",  # default city when the user does not name one
        "country_code": "ID",  # preferred country for city lookups
        "timeout_seconds": 5,
    },
    "volume": {
        "step_percent": 10,
    },
    "web_search": {
        "providers": ["tavily", "brave", "duckduckgo"],
        "max_results": 5,
        "fetch_pages": 3,
        "page_chars": 1200,
        "timeout_seconds": 6,
        "page_deadline_seconds": 3.5,
        "region": "id-id",
        # No-key fallback engines, tried in order ("duckduckgo" is DNS-blocked by some Indonesian ISPs).
        "ddgs_backends": ["yahoo", "auto"],
    },
}


def load_dotenv(path: Path | None = None, *, override: bool = False) -> dict[str, str]:
    """Tiny .env reader (no extra dependency); real environment variables win unless override=True."""
    env_path = path or ENV_PATH
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        values[key] = value
        if override or key not in os.environ:
            os.environ[key] = value
    return values


def ensure_config(config_path: Path | None = None) -> dict[str, Any]:
    load_dotenv()
    path = config_path or CONFIG_PATH
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
        return apply_personality_preset(copy.deepcopy(DEFAULT_CONFIG))

    with path.open("r", encoding="utf-8") as config_file:
        loaded = json.load(config_file)

    return apply_personality_preset(deep_merge(DEFAULT_CONFIG, loaded))


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    # Deep copies: callers mutate the merged config (presets, --mute), and that must never
    # leak back into DEFAULT_CONFIG.
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def apply_personality_preset(config: dict[str, Any]) -> dict[str, Any]:
    personality = config.setdefault("personality", {})
    preset = normalize(str(personality.get("preset", "cute"))) or "cute"
    if preset == "custom":
        personality["preset"] = "custom"
        return config

    preset_config = VOICE_PERSONALITY_PRESETS.get(preset, VOICE_PERSONALITY_PRESETS["cute"])
    config.setdefault("voice", {}).update(preset_config.get("voice", {}))
    personality.update(preset_config.get("personality", {}))
    personality["preset"] = preset if preset in VOICE_PERSONALITY_PRESETS else "cute"
    return config
