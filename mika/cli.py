"""Console entry point: `python assistant.py [--text] [--mute] [--no-llm]`."""

from __future__ import annotations

import argparse
from typing import Any

from .app import build_assistant
from .assistant import Assistant
from .audio.stt import listen_once
from .config import ensure_config
from .text import safe_print
from .ui.display import ConsoleDisplay


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
        try:
            command = input("Kamu: ").strip()
        except EOFError:
            break
        if not assistant.handle(command):
            break


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mika, asisten suara AI bahasa Indonesia untuk Windows.")
    parser.add_argument("--text", action="store_true", help="Pakai input ketik, cocok untuk tes tanpa mikrofon.")
    parser.add_argument("--mute", action="store_true", help="Jangan bersuara, cukup tampilkan teks.")
    parser.add_argument("--no-llm", action="store_true", help="Matikan otak LLM; hanya jalur aturan dan template.")
    args = parser.parse_args(argv)

    config = ensure_config()
    if args.mute:
        config["voice"]["enabled"] = False
    if args.no_llm:
        config["llm"]["enabled"] = False

    assistant = build_assistant(config, display=ConsoleDisplay())
    assistant.warm_up()

    if args.text:
        run_text_loop(assistant)
    else:
        run_voice_loop(assistant, config)
    return 0
