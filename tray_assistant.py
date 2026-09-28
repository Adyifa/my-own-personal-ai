from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from assistant import Assistant, CONFIG_PATH, Speaker, ensure_config, listen_once, safe_print


if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent


class TrayVoiceAssistant:
    def __init__(self) -> None:
        self.config = ensure_config()
        self.speaker = Speaker.from_config(self.config)
        self.assistant = Assistant(self.config, self.speaker)
        self.listening = threading.Event()
        self.shutdown = threading.Event()
        self.awaiting_command_until = 0.0
        self.worker = threading.Thread(target=self.listen_loop, daemon=True)
        self.icon = pystray.Icon(
            "mika_voice_assistant",
            self.make_icon(active=False),
            f"{self.assistant.name} Voice Assistant",
            menu=pystray.Menu(
                pystray.MenuItem("Mulai dengar", self.start_listening),
                pystray.MenuItem("Stop dengar", self.stop_listening),
                pystray.MenuItem("Tes mikrofon", self.test_microphone),
                pystray.MenuItem("Settings", self.open_settings),
                pystray.MenuItem("Buka commands.json", self.open_config),
                pystray.MenuItem("Reload config", self.reload_config),
                pystray.MenuItem("Keluar", self.quit_app),
            ),
        )

    def run(self) -> None:
        self.worker.start()
        self.start_listening()
        self.icon.run()

    def listen_loop(self) -> None:
        while not self.shutdown.is_set():
            if not self.listening.is_set():
                time.sleep(0.25)
                continue

            command = self.listen_live_chunk()
            if not command:
                continue

            safe_print(f"Kamu: {command}")
            command = self.prepare_voice_command(command)
            if command is None:
                continue

            keep_running = self.assistant.handle(command)
            if not keep_running:
                self.stop_listening()

    def listen_live_chunk(self) -> str | None:
        listen_config = self.config.get("listen", {})
        now = time.time()
        waiting_for_command = now <= self.awaiting_command_until or bool(self.assistant.pending_action)
        if waiting_for_command:
            timeout = int(listen_config.get("command_timeout_seconds", 6))
            phrase_time_limit = int(listen_config.get("command_phrase_time_limit_seconds", 8))
        else:
            timeout = int(listen_config.get("wake_timeout_seconds", 2))
            phrase_time_limit = int(listen_config.get("wake_phrase_time_limit_seconds", 4))

        return listen_once(
            self.config,
            self.speaker,
            quiet=True,
            timeout_override=timeout,
            phrase_time_limit_override=phrase_time_limit,
        )

    def start_listening(self, icon=None, item=None) -> None:
        self.listening.set()
        self.icon.icon = self.make_icon(active=True)
        self.speaker.say(f"{self.assistant.name} aktif. Awali perintah dengan Halo Mika.")

    def stop_listening(self, icon=None, item=None) -> None:
        self.listening.clear()
        self.icon.icon = self.make_icon(active=False)
        self.speaker.say("Mode dengar dihentikan.")

    def reload_config(self, icon=None, item=None) -> None:
        self.config = ensure_config()
        self.speaker = Speaker.from_config(self.config)
        self.assistant = Assistant(self.config, self.speaker)
        self.icon.title = f"{self.assistant.name} Voice Assistant"
        self.speaker.say("Konfigurasi sudah dimuat ulang.")

    def prepare_voice_command(self, command: str) -> str | None:
        wake_config = self.config.get("wake", {})
        if self.assistant.pending_action:
            return command

        if not wake_config.get("enabled", False):
            return command

        matched, stripped_command = self.assistant.strip_wake_prefix(command)
        now = time.time()
        if matched and not stripped_command:
            seconds = float(wake_config.get("next_command_seconds", 8))
            self.awaiting_command_until = now + seconds
            reply = self.config.get("personality", {}).get("listening_reply", "Iya, mau aku bantu apa?")
            self.speaker.say(str(reply))
            return None

        if matched:
            self.awaiting_command_until = 0.0
            safe_print(f"[wake] Wake phrase cocok. Command: {stripped_command}")
            return stripped_command

        if self.assistant.conversation_is_active():
            return command

        if now <= self.awaiting_command_until:
            self.awaiting_command_until = 0.0
            return command

        safe_print("[wake] Diabaikan karena tidak diawali wake phrase.")
        return None

    def test_microphone(self, icon=None, item=None) -> None:
        threading.Thread(target=self._test_microphone_worker, daemon=True).start()

    def _test_microphone_worker(self) -> None:
        was_listening = self.listening.is_set()
        self.listening.clear()
        self.icon.icon = self.make_icon(active=False)
        self.speaker.say("Tes mikrofon. Setelah bunyi ini, ucapkan Halo Mika buka YouTube.")
        command = listen_once(self.config, self.speaker, quiet=False)
        if command:
            self.speaker.say(f"Aku mendengar: {command}")
            self.notify("Tes mikrofon berhasil", f"Aku mendengar: {command}")
        else:
            self.speaker.say("Aku belum bisa menangkap suara. Cek izin mikrofon dan input device.")
            self.notify("Tes mikrofon gagal", "Cek izin mikrofon dan input device.")

        if was_listening and not self.shutdown.is_set():
            self.listening.set()
            self.icon.icon = self.make_icon(active=True)

    def notify(self, title: str, message: str) -> None:
        try:
            self.icon.notify(message, title)
        except Exception:
            pass

    def open_settings(self, icon=None, item=None) -> None:
        threading.Thread(target=self._open_settings_worker, daemon=True).start()

    def _open_settings_worker(self) -> None:
        from settings_gui import open_settings_window

        open_settings_window(CONFIG_PATH)

    def open_config(self, icon=None, item=None) -> None:
        os.startfile(CONFIG_PATH)  # type: ignore[attr-defined]

    def quit_app(self, icon=None, item=None) -> None:
        self.shutdown.set()
        self.listening.clear()
        self.icon.stop()

    @staticmethod
    def make_icon(active: bool) -> Image.Image:
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        bg = (28, 120, 92, 255) if active else (78, 86, 102, 255)
        accent = (255, 255, 255, 255)
        draw.rounded_rectangle((8, 8, 56, 56), radius=14, fill=bg)
        draw.ellipse((24, 14, 40, 36), fill=accent)
        draw.rounded_rectangle((22, 32, 42, 44), radius=8, fill=accent)
        draw.line((32, 44, 32, 52), fill=accent, width=4)
        draw.line((24, 52, 40, 52), fill=accent, width=4)
        return image


def main() -> int:
    app = TrayVoiceAssistant()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
