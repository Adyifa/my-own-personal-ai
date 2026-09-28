from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any


if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "commands.json"
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")


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
        "providers": {
            "google": "https://www.google.com/search?q={query}",
            "youtube": "https://www.youtube.com/results?search_query={query}",
            "youtube_first": "https://www.google.com/search?btnI=1&q=site%3Ayoutube.com%2Fwatch+{query}",
        },
    },
    "files": {
        "contoh dokumen": "C:/Users/YSLRS/Documents",
        "downloads": "C:/Users/YSLRS/Downloads",
    },
    "search_folders": [
        "C:/Users/YSLRS/Desktop",
        "C:/Users/YSLRS/Documents",
        "C:/Users/YSLRS/Downloads",
    ],
    "file_search": {
        "max_seconds": 5,
    },
}


CONVERSATION_REPLIES: dict[str, dict[str, list[str]]] = {
    "cute": {
        "greeting": [
            "Halo, Mika di sini. Mau minta tolong apa, atau mau ngobrol dulu?",
            "Hai. Mika denger kok. Cerita aja pelan-pelan.",
            "Halo halo. Mika siap nemenin sebentar.",
        ],
        "morning": [
            "Pagi. Semoga hari kamu mulainya enak. Mika standby kalau butuh apa-apa.",
            "Selamat pagi. Kita mulai pelan-pelan aja, mau buka apa dulu?",
        ],
        "night": [
            "Malam. Kalau udah capek, jangan lupa istirahat ya.",
            "Selamat malam. Mika bisa bantu beresin hal kecil dulu sebelum kamu tidur.",
        ],
        "how_are_you": [
            "Mika baik. Lebih seneng lagi kalau mic kamu nangkep perintah dengan bener.",
            "Aku oke. Lagi mode standby imut tapi tetap fungsional.",
            "Baik. Mika lagi nunggu kamu manggil dengan suara paling jelas.",
        ],
        "identity": [
            "Aku Mika, assistant kecil di laptop kamu. Tugasku bukain app, cari sesuatu, dan nemenin ngobrol ringan.",
            "Namaku Mika. Belum bisa mikir sebebas manusia, tapi bisa bantu hal-hal laptop dan ngobrol singkat.",
        ],
        "thanks": [
            "Sama-sama. Mika senang kalau kepake.",
            "Hehe, sama-sama. Ada yang mau Mika bantu lagi?",
            "Siap. Mika standby lagi.",
        ],
        "praise": [
            "Mika jadi semangat. Makasih.",
            "Hehe, noted. Mika akan berusaha tetap lucu dan berguna.",
            "Wah, Mika tersipu secara software.",
        ],
        "apology": [
            "Nggak apa-apa. Kita ulang pelan-pelan aja.",
            "Santai. Mika masih di sini.",
        ],
        "bored": [
            "Kalau lagi gabut, Mika bisa cariin musik santai, buka YouTube, atau nemenin ngobrol pendek.",
            "Gabut ya. Mau Mika puterin lagu, cari video lucu, atau buka game?",
        ],
        "tired": [
            "Kalau capek, ambil jeda dulu. Mika bisa bantu buka musik santai atau sleep laptop nanti.",
            "Pelan-pelan ya. Kadang yang paling produktif itu berhenti sebentar.",
        ],
        "sad": [
            "Mika denger. Kalau mau, cerita sedikit aja. Aku akan jawab pelan-pelan.",
            "Sedih itu berat. Kamu nggak harus langsung beresin semuanya sekarang.",
        ],
        "stress": [
            "Tarik napas dulu. Sebut satu hal kecil yang mau diberesin, nanti Mika bantu mulai dari situ.",
            "Kalau pikiran lagi ramai, kita kecilkan tugasnya. Mau buka musik, catatan, atau cari sesuatu?",
        ],
        "chat_invite": [
            "Boleh. Mika aktif mode ngobrol sebentar. Cerita aja.",
            "Boleh banget. Untuk beberapa detik ke depan, kamu bisa lanjut ngomong tanpa wake word.",
            "Oke, Mika temenin. Mau bahas apa?",
        ],
        "joke": [
            "Joke lokal Mika: kenapa file suka hilang? Karena dia pindah folder tanpa pamit.",
            "Mika punya jokes tipis: komputer kalau capek bukan rebahan, dia sleep.",
        ],
        "capabilities": [
            "Mika bisa buka website, app, game, file, cari Google atau YouTube, cari lagu Spotify, kontrol sleep atau shutdown dengan konfirmasi, dan ngobrol ringan.",
            "Aku bisa bantu laptop kamu: buka app, cari file, cari video, cari lagu, buka game, plus jadi teman ngobrol kecil-kecilan.",
        ],
        "status": [
            "Mika lagi standby. Mic, wake word, dan preset suara siap dipakai.",
            "Aku aktif. Tinggal bilang perintahnya dengan jelas.",
        ],
        "conversation_stop": [
            "Oke, mode ngobrol Mika tutup dulu. Panggil lagi kalau butuh.",
            "Siap, Mika balik standby.",
        ],
        "unknown_chat": [
            "Mika belum paham maksudnya. Coba bilang dengan pola seperti buka, cari, putar, atau cerita singkat.",
            "Aku nangkep kalimatnya, tapi belum tahu harus ngapain. Mau Mika cari di Google?",
            "Hmm, itu belum masuk command Mika. Kalau mau, bilang: cari itu di Google.",
        ],
    },
    "soft": {
        "greeting": [
            "Halo. Aku dengar. Mau aku bantu apa?",
            "Hai, aku di sini. Silakan pelan-pelan saja.",
        ],
        "how_are_you": [
            "Aku baik. Semoga kamu juga cukup oke hari ini.",
            "Baik. Aku siap membantu kalau kamu butuh.",
        ],
        "chat_invite": [
            "Boleh. Aku akan mendengarkan sebentar tanpa perlu wake word.",
            "Tentu. Cerita saja, aku temani sebentar.",
        ],
        "unknown_chat": [
            "Aku belum mengerti maksudnya. Coba sebutkan dengan kata buka, cari, putar, atau ceritakan sedikit lagi.",
            "Aku belum tahu harus melakukan apa dari kalimat itu.",
        ],
    },
    "calm": {
        "greeting": [
            "Halo. Aku siap mendengarkan.",
            "Halo, aku aktif. Sebutkan perintah atau ceritakan yang kamu butuhkan.",
        ],
        "how_are_you": [
            "Aku baik dan siap membantu.",
            "Baik. Kita bisa mulai dari hal kecil dulu.",
        ],
        "chat_invite": [
            "Baik, mode ngobrol aktif sebentar. Silakan lanjutkan.",
            "Aku akan mendengarkan beberapa saat tanpa wake word.",
        ],
        "unknown_chat": [
            "Aku belum memahami maksudnya. Coba ulangi lebih spesifik.",
            "Kalimat itu belum bisa aku jalankan sebagai perintah.",
        ],
    },
    "anime": {
        "greeting": [
            "Hai hai, Mika online. Mau ngapain nih?",
            "Halo. Mika muncul. Kasih command atau cerita aja.",
        ],
        "how_are_you": [
            "Mika baik. Energi standby masih penuh.",
            "Baik dong. Mika siap bantu kamu.",
        ],
        "chat_invite": [
            "Boleh. Mika aktif mode ngobrol sebentar. Lanjut ngomong aja.",
            "Oke. Mika temenin, kamu cerita dulu.",
        ],
        "unknown_chat": [
            "Mika belum ngerti itu. Coba versi yang lebih jelas ya.",
            "Hmm, command-nya belum kebaca. Mau Mika cari di Google aja?",
        ],
    },
}


VOICE_PERSONALITY_PRESETS: dict[str, dict[str, dict[str, Any]]] = {
    "custom": {
        "voice": {},
        "personality": {},
    },
    "cute": {
        "voice": {
            "edge_voice": "id-ID-GadisNeural",
            "edge_rate": "+12%",
            "edge_pitch": "+10Hz",
            "rate": 185,
        },
        "personality": {
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
            "open_reply": [
                "Oke, Mika bukain {target} ya.",
                "Siap, {target} aku buka.",
                "Bentar, Mika buka {target}.",
            ],
            "open_website_reply": [
                "Oke, Mika bukain website {target} ya.",
                "Siap, aku buka website {target}.",
                "Bentar, Mika arahin ke {target}.",
            ],
            "search_reply": [
                "Sebentar, Mika cari {query} di {provider}.",
                "Oke, Mika cariin {query} di {provider}.",
                "Siap, aku telusuri {query} di {provider}.",
            ],
            "youtube_first_reply": [
                "Mika bukain hasil YouTube paling cocok untuk {query}.",
                "Oke, aku buka video yang paling cocok untuk {query}.",
            ],
            "music_reply": [
                "Sebentar, Mika cariin {query} di Spotify.",
                "Oke, Mika buka pencarian {query} di Spotify.",
                "Siap, aku cariin lagunya di Spotify.",
            ],
            "startup_reply": "Halo, aku {name}. Panggil aku dengan Halo Mika, lalu sebutin yang kamu mau.",
            "text_startup_reply": "Halo, aku {name}. Mode ketik aktif. Ketik bantuan kalau mau contoh perintah.",
        },
    },
    "soft": {
        "voice": {
            "edge_voice": "id-ID-GadisNeural",
            "edge_rate": "+4%",
            "edge_pitch": "+4Hz",
            "rate": 172,
        },
        "personality": {
            "confirm_prefix": "Oke",
            "not_found": "Aku belum nemu",
            "listening_reply": "Iya, Mika dengerin.",
            "empty_command": "Aku belum menangkap perintahnya.",
            "stop_reply": "Baik, aku berhenti dulu.",
            "ask_target": "Mau aku bukakan apa?",
            "file_not_found": "Aku belum menemukan file atau folder itu.",
            "confirm_question": "Yakin? Bilang iya untuk lanjut, atau batal kalau tidak.",
            "confirm_expired": "Konfirmasinya sudah lewat. Aku batalin dulu, ya.",
            "confirm_cancelled": "Oke, aku batalin.",
            "confirm_waiting": "Aku masih menunggu konfirmasi. Bilang iya atau batal.",
            "open_reply": [
                "Oke, aku bukakan {target}.",
                "Baik, {target} aku buka.",
            ],
            "open_website_reply": [
                "Oke, aku bukakan website {target}.",
                "Baik, aku buka website {target}.",
            ],
            "search_reply": [
                "Sebentar, aku cari {query} di {provider}.",
                "Oke, aku telusuri {query} di {provider}.",
            ],
            "youtube_first_reply": [
                "Aku bukakan hasil YouTube paling cocok untuk {query}.",
                "Oke, aku buka video yang paling cocok untuk {query}.",
            ],
            "music_reply": [
                "Sebentar, aku cari {query} di Spotify.",
                "Oke, aku buka pencarian {query} di Spotify.",
            ],
            "startup_reply": "Halo, aku {name}. Panggil aku dengan Halo Mika, lalu sebutkan perintahnya.",
            "text_startup_reply": "Halo, aku {name}. Mode ketik aktif. Ketik bantuan untuk contoh perintah.",
        },
    },
    "calm": {
        "voice": {
            "edge_voice": "id-ID-GadisNeural",
            "edge_rate": "-4%",
            "edge_pitch": "-2Hz",
            "rate": 158,
        },
        "personality": {
            "confirm_prefix": "Baik",
            "not_found": "Aku belum menemukan",
            "listening_reply": "Iya, aku mendengarkan.",
            "empty_command": "Aku belum menangkap perintahnya.",
            "stop_reply": "Baik, mode dengar aku hentikan.",
            "ask_target": "Apa yang ingin aku buka?",
            "file_not_found": "Aku belum menemukan file atau folder itu di lokasi pencarian.",
            "confirm_question": "Aku perlu konfirmasi. Bilang iya untuk lanjut, atau batal untuk membatalkan.",
            "confirm_expired": "Waktu konfirmasi sudah lewat. Aku batalkan.",
            "confirm_cancelled": "Baik, aku batalkan.",
            "confirm_waiting": "Aku masih menunggu konfirmasi iya atau batal.",
            "open_reply": [
                "Baik, aku membuka {target}.",
                "{target} sedang aku buka.",
            ],
            "open_website_reply": [
                "Baik, aku membuka website {target}.",
                "Website {target} aku buka.",
            ],
            "search_reply": [
                "Baik, aku mencari {query} di {provider}.",
                "Aku telusuri {query} di {provider}.",
            ],
            "youtube_first_reply": [
                "Aku membuka hasil YouTube paling cocok untuk {query}.",
                "Aku buka video yang paling sesuai untuk {query}.",
            ],
            "music_reply": [
                "Baik, aku mencari {query} di Spotify.",
                "Aku buka pencarian {query} di Spotify.",
            ],
            "startup_reply": "Halo, aku {name}. Ucapkan Halo Mika, lalu sebutkan perintahnya.",
            "text_startup_reply": "Halo, aku {name}. Mode ketik aktif. Ketik bantuan untuk contoh perintah.",
        },
    },
    "anime": {
        "voice": {
            "edge_voice": "id-ID-GadisNeural",
            "edge_rate": "+14%",
            "edge_pitch": "+14Hz",
            "rate": 190,
        },
        "personality": {
            "confirm_prefix": "Siap",
            "not_found": "Mika belum ketemu",
            "listening_reply": "Hai, Mika denger kok.",
            "empty_command": "Eh, Mika belum nangkep. Ulangin pelan-pelan ya.",
            "stop_reply": "Oke, Mika standby dulu.",
            "ask_target": "Mau Mika bukain apa nih?",
            "file_not_found": "Mika belum nemu file atau folder itu.",
            "confirm_question": "Yakin? Bilang iya buat lanjut, atau batal kalau berubah pikiran.",
            "confirm_expired": "Konfirmasinya kelamaan. Mika batalin dulu, ya.",
            "confirm_cancelled": "Oke, Mika batalin.",
            "confirm_waiting": "Mika masih nunggu. Iya atau batal?",
            "open_reply": [
                "Siap, Mika bukain {target} ya.",
                "Oke, {target} meluncur.",
                "Bentar, Mika buka {target}.",
            ],
            "open_website_reply": [
                "Siap, Mika bukain website {target} ya.",
                "Oke, Mika buka web {target}.",
            ],
            "search_reply": [
                "Oke, Mika cariin {query} di {provider}.",
                "Siap, Mika gas cari {query} di {provider}.",
            ],
            "youtube_first_reply": [
                "Mika bukain hasil YouTube paling cocok untuk {query}.",
                "Oke, Mika buka video yang paling cocok untuk {query}.",
            ],
            "music_reply": [
                "Oke, Mika cariin {query} di Spotify.",
                "Siap, Mika buka Spotify buat {query}.",
            ],
            "startup_reply": "Halo, aku {name}. Panggil Halo Mika, terus bilang maunya apa.",
            "text_startup_reply": "Halo, aku {name}. Mode ketik aktif. Ketik bantuan kalau mau contoh.",
        },
    },
}


def safe_print(message: str) -> None:
    if sys.stdout:
        print(message)


def ensure_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(
            json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return apply_personality_preset(copy.deepcopy(DEFAULT_CONFIG))

    with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        loaded = json.load(config_file)

    return apply_personality_preset(deep_merge(DEFAULT_CONFIG, loaded))


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
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


def normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s./:-]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def strip_command_words(text: str) -> str:
    patterns = [
        r"^(tolong\s+)?buka\s+(website|web|situs|file|folder|aplikasi|app|program)?\s*",
        r"^(tolong\s+)?cari\s+(file|folder|dokumen)?\s*",
        r"^(tolong\s+)?jalankan\s+(aplikasi|app|program)?\s*",
        r"^(tolong\s+)?open\s+",
    ]
    result = normalize(text)
    for pattern in patterns:
        result = re.sub(pattern, "", result).strip()
    return result


@dataclass
class PendingAction:
    action: str
    label: str
    created_at: float
    expires_at: float


@dataclass
class Speaker:
    enabled: bool
    provider: str = "sapi"
    engine: Any = None
    config: dict[str, Any] | None = None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "Speaker":
        voice_config = config.get("voice", {})
        if not voice_config.get("enabled", True):
            return cls(enabled=False)

        provider = str(voice_config.get("provider", "sapi")).lower()
        if provider == "edge":
            return cls(enabled=True, provider="edge", config=voice_config)
        if provider in {"coqui", "coqui_tts", "coqui_xtts", "xtts"}:
            return cls(enabled=True, provider="coqui", config=voice_config)

        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", int(voice_config.get("rate", 175)))
            engine.setProperty("volume", float(voice_config.get("volume", 1.0)))

            requested_voice = normalize(str(voice_config.get("name_contains", "")))
            if requested_voice:
                for voice in engine.getProperty("voices"):
                    haystack = normalize(f"{voice.name} {voice.id}")
                    if requested_voice in haystack:
                        engine.setProperty("voice", voice.id)
                        break

            return cls(enabled=True, provider="sapi", engine=engine, config=voice_config)
        except Exception as exc:
            safe_print(f"[voice] Text-to-speech tidak aktif: {exc}")
            return cls(enabled=False)

    def say(self, message: str) -> None:
        safe_print(f"Assistant: {message}")
        if not self.enabled:
            return

        if self.provider == "edge":
            if self.say_with_edge(message):
                return
            self.say_with_sapi_fallback(message)
            return

        if self.provider == "coqui":
            if self.say_with_coqui(message):
                return
            self.say_with_sapi_fallback(message)
            return

        if self.engine:
            self.engine.say(message)
            self.engine.runAndWait()

    def say_with_edge(self, message: str) -> bool:
        try:
            asyncio.run(self.create_edge_audio(message))
            return True
        except Exception as exc:
            safe_print(f"[edge-tts] Gagal memakai suara neural: {exc}")
            return False

    async def create_edge_audio(self, message: str) -> None:
        import edge_tts
        import pygame

        voice_config = self.config or {}
        voice = str(voice_config.get("edge_voice", "id-ID-GadisNeural"))
        rate = str(voice_config.get("edge_rate", "+0%"))
        volume = str(voice_config.get("edge_volume", "+0%"))
        pitch = str(voice_config.get("edge_pitch", "+0Hz"))

        communicate = edge_tts.Communicate(
            text=message,
            voice=voice,
            rate=rate,
            volume=volume,
            pitch=pitch,
        )
        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as audio_file:
                temp_path = audio_file.name

            await communicate.save(temp_path)
            pygame.mixer.init()
            pygame.mixer.music.load(temp_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
            pygame.mixer.music.unload()
        finally:
            if temp_path:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def say_with_coqui(self, message: str) -> bool:
        try:
            self.create_coqui_audio(message)
            return True
        except Exception as exc:
            safe_print(f"[coqui-tts] Gagal memakai personal voice: {exc}")
            return False

    def create_coqui_audio(self, message: str) -> None:
        import pygame
        from TTS.api import TTS

        voice_config = self.config or {}
        model_path = str(voice_config.get("coqui_model_path", "")).strip()
        config_path = str(voice_config.get("coqui_config_path", "")).strip()
        model_name = str(
            voice_config.get("coqui_model", "tts_models/multilingual/multi-dataset/xtts_v2")
        )
        speaker_wav = str(voice_config.get("coqui_speaker_wav", "")).strip()
        language = str(voice_config.get("coqui_language", "id")).strip() or "id"
        use_gpu = bool(voice_config.get("coqui_gpu", False))

        if model_path and config_path:
            tts = TTS(model_path=model_path, config_path=config_path, progress_bar=False, gpu=use_gpu)
        else:
            tts = TTS(model_name=model_name, progress_bar=False, gpu=use_gpu)

        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as audio_file:
                temp_path = audio_file.name

            tts_args: dict[str, Any] = {
                "text": message,
                "file_path": temp_path,
            }
            if speaker_wav:
                tts_args["speaker_wav"] = speaker_wav
            if language:
                tts_args["language"] = language

            tts.tts_to_file(**tts_args)
            pygame.mixer.init()
            pygame.mixer.music.load(temp_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
            pygame.mixer.music.unload()
        finally:
            if temp_path:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def say_with_sapi_fallback(self, message: str) -> None:
        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.say(message)
            engine.runAndWait()
        except Exception as exc:
            safe_print(f"[voice] Fallback TTS gagal: {exc}")


class Assistant:
    def __init__(self, config: dict[str, Any], speaker: Speaker):
        self.config = config
        self.speaker = speaker
        self.name = config.get("assistant_name", "Assistant")
        self.pending_action: PendingAction | None = None
        self.discovered_apps: dict[str, str] | None = None
        self.discovered_games: dict[str, str] | None = None
        self.conversation_until = 0.0

    def handle(self, raw_command: str) -> bool:
        command = normalize(raw_command)
        _, command = self.strip_wake_prefix(command)
        command = self.clean_conversational_command(command)
        if not command:
            self.speaker.say(self.message("empty_command", "Aku belum menangkap perintahnya."))
            return True

        if self.handle_pending_confirmation(command):
            return True

        if command in {"keluar", "selesai", "berhenti", "stop", "exit", "quit"}:
            self.speaker.say(self.message("stop_reply", "Baik, aku berhenti dulu."))
            return False

        if any(phrase in command for phrase in ["daftar perintah", "bantuan", "apa saja"]):
            self.say_help()
            return True

        if self.try_conversation(command):
            return True

        target = strip_command_words(command)
        if not target:
            self.speaker.say(self.message("ask_target", "Mau buka apa?"))
            return True

        if self.try_power_command(command):
            return True

        if self.try_play_music(command, target):
            return True

        if any(word in command.split() for word in ["file", "folder", "dokumen"]):
            if self.try_open_file(command, target):
                return True
            self.speaker.say(
                self.message("file_not_found", "Aku belum nemu file atau folder itu di lokasi pencarian.")
            )
            return True

        if self.try_search(command, target):
            return True

        if self.try_open_website(command, target):
            return True

        if self.try_open_game(command, target):
            return True

        if self.try_open_app(command, target):
            return True

        if self.try_open_file(command, target):
            return True

        self.speaker.say(
            self.message(
                "unknown_reply",
                "{not_found} '{target}'. Coba bilang buka, cari, putar, atau ngobrol.",
                not_found=self.personality("not_found", "Aku belum nemu"),
                target=target,
            )
        )
        return True

    def say_help(self) -> None:
        websites = ", ".join(sorted(self.config.get("websites", {}).keys()))
        apps = ", ".join(sorted(self.config.get("apps", {}).keys()))
        files = ", ".join(sorted(self.config.get("files", {}).keys()))
        self.speaker.say(
            "Contoh perintah: halo mika buka youtube, halo mika cari tutorial python di youtube, "
            "halo mika cari cuaca jakarta di google, halo mika aku mau main cs2 dong, "
            "halo mika sleep laptop, atau halo mika buka notepad. "
            f"Website tersedia: {websites or '-'}, aplikasi: {apps or '-'}, file: {files or '-'}."
        )

    def personality(self, key: str, fallback: str) -> str:
        value = self.config.get("personality", {}).get(key, fallback)
        if isinstance(value, list):
            return str(random.choice(value)) if value else fallback
        return str(value)

    def message(self, key: str, fallback: str, **values: Any) -> str:
        template = self.personality(key, fallback)
        try:
            return template.format(**values)
        except (KeyError, ValueError):
            return fallback.format(**values)

    def say_opened(self, target: str) -> None:
        self.speaker.say(self.message("open_reply", "Membuka {target}.", target=target))

    def preset_name(self) -> str:
        preset = normalize(str(self.config.get("personality", {}).get("preset", "cute"))) or "cute"
        return preset if preset in VOICE_PERSONALITY_PRESETS else "cute"

    def chat_reply(self, category: str, fallback: str, **values: Any) -> str:
        preset = self.preset_name()
        default_bank = CONVERSATION_REPLIES.get("cute", {})
        preset_bank = CONVERSATION_REPLIES.get(preset, {})
        choices = preset_bank.get(category) or default_bank.get(category) or [fallback]
        template = random.choice(choices)
        try:
            return template.format(name=self.name, **values)
        except (KeyError, ValueError):
            return fallback.format(name=self.name, **values)

    def keep_conversation_alive(self) -> None:
        conversation_config = self.config.get("conversation", {})
        if not conversation_config.get("enabled", True):
            return
        seconds = float(conversation_config.get("continue_seconds", 18))
        self.conversation_until = time.time() + seconds

    def stop_conversation(self) -> None:
        self.conversation_until = 0.0

    def conversation_is_active(self) -> bool:
        return time.time() <= self.conversation_until

    def try_conversation(self, command: str) -> bool:
        if not self.config.get("conversation", {}).get("enabled", True):
            return False

        tokens = set(command.split())

        def has_any(phrases: list[str]) -> bool:
            return any(phrase in command for phrase in phrases)

        if has_any(["selesai ngobrol", "stop ngobrol", "udah dulu", "sudah dulu", "cukup ngobrol"]):
            self.stop_conversation()
            self.speaker.say(self.chat_reply("conversation_stop", "Oke, mode ngobrol aku tutup dulu."))
            return True

        if has_any(["selamat pagi"]) or command in {"pagi", "pagi mika"}:
            self.keep_conversation_alive()
            self.speaker.say(self.chat_reply("morning", "Selamat pagi. Aku siap bantu."))
            return True

        if has_any(["selamat malam", "mau tidur", "good night"]) or command in {"malam", "malam mika"}:
            self.keep_conversation_alive()
            self.speaker.say(self.chat_reply("night", "Selamat malam. Aku siap bantu."))
            return True

        if command in {"halo", "hai", "hey", "hello", "helo", "halo mika", "hai mika"}:
            self.keep_conversation_alive()
            self.speaker.say(self.chat_reply("greeting", "Halo. Aku dengar."))
            return True

        if has_any(["apa kabar", "kabar kamu", "gimana kabar", "lagi sehat"]):
            self.keep_conversation_alive()
            self.speaker.say(self.chat_reply("how_are_you", "Aku baik."))
            return True

        if has_any(["siapa kamu", "kamu siapa", "nama kamu", "kenalin diri"]):
            self.keep_conversation_alive()
            self.speaker.say(self.chat_reply("identity", "Aku {name}, assistant di laptop kamu."))
            return True

        if command in {"makasih", "terima kasih", "thanks", "thank you"} or has_any(["makasih ya", "terima kasih ya"]):
            self.keep_conversation_alive()
            self.speaker.say(self.chat_reply("thanks", "Sama-sama."))
            return True

        if has_any(["kamu keren", "kamu pintar", "kamu pinter", "kamu lucu", "kamu imut", "mantap", "good job"]):
            self.keep_conversation_alive()
            self.speaker.say(self.chat_reply("praise", "Makasih."))
            return True

        if command in {"maaf", "sorry"} or has_any(["maaf ya", "sorry ya"]):
            self.keep_conversation_alive()
            self.speaker.say(self.chat_reply("apology", "Nggak apa-apa."))
            return True

        if has_any(["aku bosan", "aku bosen", "lagi bosan", "lagi bosen", "gabut"]):
            self.keep_conversation_alive()
            self.speaker.say(self.chat_reply("bored", "Mau aku carikan hiburan?"))
            return True

        if has_any(["aku capek", "aku cape", "aku lelah", "lagi capek", "ngantuk"]):
            self.keep_conversation_alive()
            self.speaker.say(self.chat_reply("tired", "Istirahat sebentar ya."))
            return True

        if has_any(["aku sedih", "lagi sedih", "aku galau", "kesepian", "sendirian"]):
            self.keep_conversation_alive()
            self.speaker.say(self.chat_reply("sad", "Aku denger."))
            return True

        if has_any(["aku stres", "aku stress", "lagi stres", "lagi stress", "overthinking", "cemas", "panik"]):
            self.keep_conversation_alive()
            self.speaker.say(self.chat_reply("stress", "Tarik napas dulu."))
            return True

        if command == "curhat" or has_any(
            ["ngobrol yuk", "temenin aku", "mika temenin", "aku mau curhat", "mau curhat", "curhat dong"]
        ):
            self.keep_conversation_alive()
            self.speaker.say(self.chat_reply("chat_invite", "Boleh. Cerita aja."))
            return True

        if has_any(["cerita lucu", "joke", "lawak", "candaan"]):
            self.keep_conversation_alive()
            self.speaker.say(self.chat_reply("joke", "Aku belum punya jokes bagus, tapi aku coba."))
            return True

        if has_any(["kamu bisa apa", "bisa apa", "fitur kamu", "apa yang bisa kamu lakukan"]):
            self.keep_conversation_alive()
            self.speaker.say(self.chat_reply("capabilities", "Aku bisa bantu buka app, website, file, dan cari sesuatu."))
            return True

        if has_any(["lagi ngapain", "kamu lagi apa", "status kamu", "aktif nggak", "aktif gak"]):
            self.keep_conversation_alive()
            self.speaker.say(self.chat_reply("status", "Aku lagi standby."))
            return True

        if self.conversation_is_active() and not (tokens & {"buka", "cari", "putar", "main", "mainkan", "jalankan"}):
            self.keep_conversation_alive()
            self.speaker.say(self.chat_reply("unknown_chat", "Aku denger, tapi belum paham harus jawab apa."))
            return True

        return False

    def clean_conversational_command(self, command: str) -> str:
        command = normalize(command)
        replacements = {
            "bukain": "buka",
            "carikan": "cari",
            "puterin": "putar",
            "putarkan": "putar",
            "nyalain": "buka",
            "matikanin": "matikan",
        }
        for source, replacement in replacements.items():
            command = re.sub(rf"\b{re.escape(source)}\b", replacement, command)

        patterns = [
            r"^((zeta|mika)\s+)?(tolong|coba|please)\s+",
            r"^(aku\s+)?(mau|pengen|ingin)\s+",
            r"^(bisa\s+)?(tolong\s+)?",
            r"\s+(dong|ya|please)$",
        ]
        previous = None
        while previous != command:
            previous = command
            for pattern in patterns:
                command = re.sub(pattern, "", command).strip()
        return normalize(command)

    def handle_pending_confirmation(self, command: str) -> bool:
        if not self.pending_action:
            return False

        safety_config = self.config.get("safety", {})
        yes_words = {normalize(word) for word in safety_config.get("yes_words", [])}
        no_words = {normalize(word) for word in safety_config.get("no_words", [])}
        now = time.time()
        pending = self.pending_action

        if now > pending.expires_at:
            self.pending_action = None
            self.speaker.say(self.message("confirm_expired", "Konfirmasinya sudah lewat. Aku batalin dulu, ya."))
            return True

        if command in yes_words:
            self.pending_action = None
            self.execute_power_action(pending.action)
            self.speaker.say(f"{self.personality('confirm_prefix', 'Oke')}, {pending.label}.")
            return True

        if command in no_words:
            self.pending_action = None
            self.speaker.say(self.message("confirm_cancelled", "Oke, aku batalin."))
            return True

        self.speaker.say(self.message("confirm_waiting", "Aku masih nunggu konfirmasi. Bilang iya atau batal."))
        return True

    def try_power_command(self, command: str) -> bool:
        action: str | None = None
        label = ""
        if any(phrase in command for phrase in ["matikan laptop", "matikan komputer", "shutdown", "shut down"]):
            action = "shutdown"
            label = "laptop akan dimatikan"
        elif any(phrase in command for phrase in ["restart laptop", "restart komputer", "mulai ulang"]):
            action = "restart"
            label = "laptop akan direstart"
        elif any(phrase in command for phrase in ["sleep laptop", "tidurkan laptop", "mode sleep", "sleep komputer"]):
            action = "sleep"
            label = "laptop masuk mode sleep"
        elif any(phrase in command for phrase in ["kunci laptop", "lock laptop", "lock komputer"]):
            action = "lock"
            label = "laptop akan dikunci"
        elif any(phrase in command for phrase in ["logout", "log out", "keluar windows"]):
            action = "logout"
            label = "akun Windows akan logout"

        if not action:
            return False

        seconds = float(self.config.get("safety", {}).get("confirmation_seconds", 12))
        self.pending_action = PendingAction(
            action=action,
            label=label,
            created_at=time.time(),
            expires_at=time.time() + seconds,
        )
        self.speaker.say(
            self.message("confirm_question", "Yakin? Bilang iya untuk lanjut. Kalau tidak, bilang batal.")
        )
        return True

    @staticmethod
    def execute_power_action(action: str) -> None:
        if action == "shutdown":
            subprocess.Popen(["shutdown", "/s", "/t", "0"])
        elif action == "restart":
            subprocess.Popen(["shutdown", "/r", "/t", "0"])
        elif action == "logout":
            subprocess.Popen(["shutdown", "/l"])
        elif action == "lock":
            subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
        elif action == "sleep":
            subprocess.Popen(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Add-Type -AssemblyName System.Windows.Forms; "
                    "[System.Windows.Forms.Application]::SetSuspendState('Suspend',$false,$false)",
                ]
            )

    def strip_wake_prefix(self, command: str) -> tuple[bool, str]:
        wake_config: dict[str, Any] = self.config.get("wake", {})
        phrases = wake_config.get("phrases", [])
        normalized_command = normalize(command)
        normalized_phrases = sorted(
            {normalize(str(phrase)) for phrase in phrases if normalize(str(phrase))},
            key=len,
            reverse=True,
        )
        for normalized_phrase in normalized_phrases:
            if normalized_command == normalized_phrase:
                return True, ""
            if normalized_command.startswith(f"{normalized_phrase} "):
                return True, normalized_command[len(normalized_phrase) :].strip()

            if wake_config.get("match_anywhere", True):
                marker = f" {normalized_phrase} "
                padded_command = f" {normalized_command} "
                index = padded_command.find(marker)
                if index >= 0:
                    start = index + len(marker)
                    return True, padded_command[start:].strip()

        fuzzy_match = self.strip_fuzzy_wake(normalized_command)
        if fuzzy_match is not None:
            return True, fuzzy_match

        return False, normalized_command

    @staticmethod
    def strip_fuzzy_wake(command: str) -> str | None:
        tokens = command.split()
        zeta_like = {"mika", "mica", "mikha", "nika", "zeta", "zetta", "seta", "jeta", "zita", "ceta"}
        hello_like = {"halo", "hai", "hey", "helo", "hello"}
        for index, token in enumerate(tokens):
            if token not in hello_like:
                continue
            if index + 1 < len(tokens) and tokens[index + 1] in zeta_like:
                return " ".join(tokens[index + 2 :]).strip()
        return None

    def try_open_website(self, command: str, target: str) -> bool:
        websites: dict[str, str] = self.config.get("websites", {})
        for alias, url in websites.items():
            if normalize(alias) == target or normalize(alias) in command:
                webbrowser.open(url)
                self.say_opened(alias)
                return True

        if "website" in command or "web" in command or looks_like_url(target):
            url = target if looks_like_url(target) else f"https://{target}"
            webbrowser.open(url)
            self.speaker.say(
                self.message("open_website_reply", "Membuka website {target}.", target=target)
            )
            return True

        return False

    def try_open_app(self, command: str, target: str) -> bool:
        apps: dict[str, str] = {}
        apps.update(self.get_discovered_apps())
        apps.update(self.config.get("apps", {}))
        for alias, executable in sorted(apps.items(), key=lambda item: len(normalize(item[0])), reverse=True):
            if normalize(alias) == target or normalize(alias) in command:
                self.launch_target(executable)
                self.say_opened(alias)
                return True
        return False

    def try_open_game(self, command: str, target: str) -> bool:
        game_words = ["game", "main", "mainkan", "launch", "jalankan", "buka"]
        if not any(word in command.split() for word in game_words):
            return False

        games: dict[str, str] = {}
        games.update(self.get_discovered_games())
        games.update(self.config.get("games", {}))
        for alias, launcher in sorted(games.items(), key=lambda item: len(normalize(item[0])), reverse=True):
            normalized_alias = normalize(alias)
            if normalized_alias == target or normalized_alias in command:
                self.launch_target(launcher)
                self.say_opened(alias)
                return True

        return False

    @staticmethod
    def launch_target(target: str) -> None:
        expanded = os.path.expandvars(target)
        if re.match(r"^[a-z][a-z0-9+.-]*://", expanded, flags=re.IGNORECASE):
            webbrowser.open(expanded)
            return

        path = Path(expanded).expanduser()
        if path.exists():
            os.startfile(path)  # type: ignore[attr-defined]
            return

        subprocess.Popen(expanded, shell=True)

    def get_discovered_apps(self) -> dict[str, str]:
        if self.discovered_apps is not None:
            return self.discovered_apps

        discovery_config = self.config.get("auto_discovery", {})
        if not discovery_config.get("enabled", True):
            self.discovered_apps = {}
            return self.discovered_apps

        apps: dict[str, str] = {}
        if discovery_config.get("scan_start_menu", True):
            apps.update(scan_shortcuts(start_menu_paths()))
        if discovery_config.get("scan_desktop", True):
            apps.update(scan_shortcuts(desktop_paths()))

        self.discovered_apps = apps
        return apps

    def get_discovered_games(self) -> dict[str, str]:
        if self.discovered_games is not None:
            return self.discovered_games

        discovery_config = self.config.get("auto_discovery", {})
        if not discovery_config.get("enabled", True) or not discovery_config.get("scan_steam", True):
            self.discovered_games = {}
            return self.discovered_games

        self.discovered_games = scan_steam_games()
        return self.discovered_games

    def try_search(self, command: str, target: str) -> bool:
        original_command = command
        command = self.rewrite_natural_search(command)
        target = strip_command_words(command)
        search_words = ["cari", "search", "telusuri", "googling"]
        provider = self.detect_search_provider(command)
        starts_as_search = any(command.startswith(f"{word} ") for word in search_words)
        starts_with_provider = command.startswith("google ") or command.startswith("youtube ")
        if not starts_as_search and not starts_with_provider:
            return False

        query = self.clean_search_query(target if starts_as_search else command)
        if not query:
            self.speaker.say("Mau cari apa?")
            return True

        search_config: dict[str, Any] = self.config.get("search", {})
        provider = provider or normalize(str(search_config.get("default_provider", "google")))
        if provider == "youtube" and self.should_open_first_youtube_result(original_command):
            provider = "youtube_first"
        providers: dict[str, str] = search_config.get("providers", {})
        template = providers.get(provider)
        if not template:
            self.speaker.say(f"Aku belum punya pengaturan pencarian untuk {provider}.")
            return True

        encoded_query = urllib.parse.quote_plus(query)
        webbrowser.open(template.format(query=encoded_query))
        if provider == "youtube_first":
            self.speaker.say(
                self.message(
                    "youtube_first_reply",
                    "Aku buka hasil YouTube paling cocok untuk {query}.",
                    query=query,
                )
            )
        else:
            self.speaker.say(
                self.message("search_reply", "Mencari {query} di {provider}.", query=query, provider=provider)
            )
        return True

    @staticmethod
    def rewrite_natural_search(command: str) -> str:
        patterns = [
            (r"^(nonton|tonton)\s+(youtube\s+)?(tentang\s+)?(.+)$", r"cari \4 di youtube"),
            (r"^lihat\s+(video\s+)?(.+)\s+di\s+youtube$", r"cari \2 di youtube"),
            (r"^youtube\s+(.+)$", r"cari \1 di youtube"),
            (r"^google\s+(.+)$", r"cari \1 di google"),
        ]
        for pattern, replacement in patterns:
            rewritten = re.sub(pattern, replacement, command).strip()
            if rewritten != command:
                return normalize(rewritten)
        return command

    @staticmethod
    def detect_search_provider(command: str) -> str | None:
        if "youtube" in command or command.startswith("yt "):
            return "youtube"
        if "google" in command or command.startswith("googling "):
            return "google"
        return None

    @staticmethod
    def should_open_first_youtube_result(command: str) -> bool:
        return any(
            phrase in command
            for phrase in [
                "nonton",
                "tonton",
                "buka video",
                "putar video",
                "hasil pertama",
            ]
        )

    def try_play_music(self, command: str, target: str) -> bool:
        command = self.rewrite_natural_music(command)
        target = strip_command_words(command)
        music_words = ["putar", "mainkan", "play", "dengerin", "dengarkan", "setel"]
        if "spotify" not in command and "lagu" not in command and not any(command.startswith(word) for word in music_words):
            return False

        music_config: dict[str, Any] = self.config.get("music", {})
        songs: dict[str, str] = music_config.get("songs", {})
        query = target

        for alias, song_query in songs.items():
            normalized_alias = normalize(alias)
            if normalized_alias == target or normalized_alias in command:
                query = song_query
                break

        query = self.clean_music_query(query)
        if not query:
            self.speaker.say("Mau putar lagu apa?")
            return True

        provider = normalize(str(music_config.get("provider", "spotify")))
        if provider != "spotify":
            self.speaker.say("Untuk sekarang aku baru disetel untuk Spotify.")
            return True

        encoded_query = urllib.parse.quote(query)
        open_mode = normalize(str(music_config.get("open_mode", "web")))
        if open_mode == "app":
            webbrowser.open(f"spotify:search:{encoded_query}")
        else:
            webbrowser.open(f"https://open.spotify.com/search/{encoded_query}")

        self.speaker.say(self.message("music_reply", "Mencari {query} di Spotify.", query=query))
        return True

    @staticmethod
    def rewrite_natural_music(command: str) -> str:
        patterns = [
            (r"^lagu\s+(.+)$", r"putar lagu \1 di spotify"),
            (r"^putar\s+yang\s+(.+)$", r"putar lagu \1 di spotify"),
            (r"^putar\s+lagu\s+yang\s+(.+)$", r"putar lagu \1 di spotify"),
            (r"^musik\s+(.+)$", r"putar musik \1 di spotify"),
        ]
        for pattern, replacement in patterns:
            rewritten = re.sub(pattern, replacement, command).strip()
            if rewritten != command:
                return normalize(rewritten)
        return command

    def try_open_file(self, command: str, target: str) -> bool:
        files: dict[str, str] = self.config.get("files", {})
        for alias, file_path in files.items():
            if normalize(alias) == target or normalize(alias) in command:
                return self.open_path(Path(os.path.expandvars(file_path)), alias)

        if "file" in command or "folder" in command or "dokumen" in command:
            found = self.find_file(target)
            if found:
                return self.open_path(found, found.name)

            found = self.find_file(command)
            if found:
                return self.open_path(found, found.name)

        return False

    def open_path(self, path: Path, label: str) -> bool:
        path = path.expanduser()
        if not path.exists():
            self.speaker.say(f"Path untuk {label} belum ditemukan: {path}")
            return True

        os.startfile(path)  # type: ignore[attr-defined]
        self.say_opened(label)
        return True

    def find_file(self, target: str) -> Path | None:
        search_name = strip_command_words(target)
        if not search_name:
            return None

        started_at = time.time()
        max_seconds = float(self.config.get("file_search", {}).get("max_seconds", 5))
        for folder in self.config.get("search_folders", []):
            root = Path(os.path.expandvars(folder)).expanduser()
            if not root.exists():
                continue

            direct_match = root / search_name
            if direct_match.exists():
                return direct_match

            normalized_search = normalize(search_name)
            try:
                for path in root.rglob("*"):
                    if time.time() - started_at > max_seconds:
                        return None
                    if normalized_search in normalize(path.stem) or normalized_search in normalize(path.name):
                        return path
            except PermissionError:
                continue

        return None

    @staticmethod
    def clean_music_query(query: str) -> str:
        query = normalize(query)
        patterns = [
            r"^(tolong\s+)?(putar|mainkan|play|dengerin|dengarkan|setel)\s+",
            r"^lagu\s+",
            r"\s+(di|ke|pake|pakai)\s+spotify$",
            r"\s+spotify$",
        ]
        for pattern in patterns:
            query = re.sub(pattern, "", query).strip()
        query = query.replace(" dari ", " ")
        query = query.replace(" oleh ", " ")
        return re.sub(r"\s+", " ", query).strip()

    @staticmethod
    def clean_search_query(query: str) -> str:
        query = normalize(query)
        patterns = [
            r"^(tolong\s+)?(cari|search|telusuri|googling)\s+",
            r"^(di\s+)?(google|youtube|yt)\s+",
            r"\s+(di|ke|pake|pakai)\s+(google|youtube|yt)$",
            r"\s+(google|youtube|yt)$",
        ]
        for pattern in patterns:
            query = re.sub(pattern, "", query).strip()
        return re.sub(r"\s+", " ", query).strip()


def start_menu_paths() -> list[Path]:
    paths = [
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    ]
    return [path for path in paths if path.exists()]


def desktop_paths() -> list[Path]:
    paths = [
        Path.home() / "Desktop",
        Path(os.environ.get("PUBLIC", "C:/Users/Public")) / "Desktop",
    ]
    return [path for path in paths if path.exists()]


def scan_shortcuts(roots: list[Path]) -> dict[str, str]:
    shortcuts: dict[str, str] = {}
    for root in roots:
        for pattern in ("*.lnk", "*.url", "*.exe"):
            try:
                paths = root.rglob(pattern)
                for path in paths:
                    alias = normalize(path.stem)
                    if alias and alias not in shortcuts:
                        shortcuts[alias] = str(path)
            except OSError:
                continue
    return shortcuts


def scan_steam_games() -> dict[str, str]:
    steam_roots = possible_steam_roots()
    library_paths: list[Path] = []
    for root in steam_roots:
        steamapps = root / "steamapps"
        if steamapps.exists():
            library_paths.append(steamapps)
        library_paths.extend(parse_steam_libraries(root / "steamapps" / "libraryfolders.vdf"))

    games: dict[str, str] = {}
    for steamapps in dedupe_paths(library_paths):
        try:
            manifests = steamapps.glob("appmanifest_*.acf")
            for manifest in manifests:
                appid, name = parse_steam_manifest(manifest)
                if appid and name:
                    games[normalize(name)] = f"steam://rungameid/{appid}"
        except OSError:
            continue
    return games


def possible_steam_roots() -> list[Path]:
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Steam",
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Steam",
    ]
    return [path for path in candidates if path.exists()]


def parse_steam_libraries(vdf_path: Path) -> list[Path]:
    if not vdf_path.exists():
        return []

    libraries: list[Path] = []
    try:
        text = vdf_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    for match in re.finditer(r'"path"\s+"([^"]+)"', text):
        path = Path(match.group(1).replace("\\\\", "\\"))
        steamapps = path / "steamapps"
        if steamapps.exists():
            libraries.append(steamapps)
    return libraries


def parse_steam_manifest(manifest_path: Path) -> tuple[str | None, str | None]:
    try:
        text = manifest_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None, None

    appid_match = re.search(r'"appid"\s+"([^"]+)"', text)
    name_match = re.search(r'"name"\s+"([^"]+)"', text)
    appid = appid_match.group(1) if appid_match else None
    name = name_match.group(1) if name_match else None
    return appid, name


def dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def looks_like_url(text: str) -> bool:
    return "." in text and " " not in text


def listen_once(
    config: dict[str, Any],
    speaker: Speaker,
    quiet: bool = False,
    timeout_override: int | None = None,
    phrase_time_limit_override: int | None = None,
) -> str | None:
    try:
        import speech_recognition as sr
    except ImportError:
        speaker.say(
            "Library speech recognition belum terpasang. Jalankan mode ketik dulu, "
            "atau install requirements."
        )
        return None

    recognizer = sr.Recognizer()
    listen_config = config.get("listen", {})
    language = listen_config.get("language", "id-ID")
    device_index = listen_config.get("device_index")
    timeout = int(listen_config.get("timeout_seconds", 6))
    phrase_time_limit = int(listen_config.get("phrase_time_limit_seconds", 8))
    adjust_duration = float(listen_config.get("ambient_adjust_seconds", 0.5))
    recognizer.pause_threshold = float(listen_config.get("pause_threshold", recognizer.pause_threshold))
    recognizer.non_speaking_duration = float(
        listen_config.get("non_speaking_duration", recognizer.non_speaking_duration)
    )
    recognizer.dynamic_energy_threshold = bool(
        listen_config.get("dynamic_energy_threshold", recognizer.dynamic_energy_threshold)
    )
    energy_threshold = listen_config.get("energy_threshold")
    if energy_threshold not in (None, ""):
        recognizer.energy_threshold = int(energy_threshold)
    if timeout_override is not None:
        timeout = timeout_override
    if phrase_time_limit_override is not None:
        phrase_time_limit = phrase_time_limit_override
    if device_index == "":
        device_index = None

    try:
        with sr.Microphone(device_index=device_index) as source:
            safe_print("Mendengarkan...")
            recognizer.adjust_for_ambient_noise(source, duration=adjust_duration)
            audio = recognizer.listen(
                source,
                timeout=timeout,
                phrase_time_limit=phrase_time_limit,
            )
    except sr.WaitTimeoutError:
        if not quiet:
            speaker.say("Aku belum mendengar perintah.")
        return None
    except Exception as exc:
        if quiet:
            safe_print(f"[mic] Mikrofon belum bisa dipakai: {exc}")
        else:
            speaker.say(f"Mikrofon belum bisa dipakai: {exc}")
        return None

    try:
        return recognizer.recognize_google(audio, language=language)
    except sr.UnknownValueError:
        if not quiet:
            speaker.say("Maaf, aku belum menangkap suaramu.")
    except sr.RequestError as exc:
        if quiet:
            safe_print(f"[speech] Layanan pengenal suara sedang bermasalah: {exc}")
        else:
            speaker.say(f"Layanan pengenal suara sedang bermasalah: {exc}")

    return None


def run_voice_loop(assistant: Assistant, config: dict[str, Any]) -> None:
    assistant.speaker.say(
        assistant.message(
            "startup_reply",
            "Halo, aku {name}. Katakan perintah seperti Halo Mika buka YouTube.",
            name=assistant.name,
        )
    )
    while True:
        command = listen_once(config, assistant.speaker)
        if command is None:
            fallback = input("Ketik perintah, atau Enter untuk coba dengar lagi: ").strip()
            if not fallback:
                continue
            command = fallback

        safe_print(f"Kamu: {command}")
        if not assistant.handle(command):
            break


def run_text_loop(assistant: Assistant) -> None:
    assistant.speaker.say(
        assistant.message(
            "text_startup_reply",
            "Halo, aku {name}. Mode ketik aktif. Ketik bantuan untuk contoh perintah.",
            name=assistant.name,
        )
    )
    while True:
        command = input("Kamu: ").strip()
        if not assistant.handle(command):
            break


def main() -> int:
    parser = argparse.ArgumentParser(description="AI voice assistant bahasa Indonesia untuk Windows.")
    parser.add_argument(
        "--text",
        action="store_true",
        help="Pakai input ketik, cocok untuk tes awal tanpa mikrofon.",
    )
    args = parser.parse_args()

    config = ensure_config()
    speaker = Speaker.from_config(config)
    assistant = Assistant(config, speaker)

    if args.text:
        run_text_loop(assistant)
    else:
        run_voice_loop(assistant, config)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
