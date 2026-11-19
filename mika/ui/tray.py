"""System tray app: always-on listening with the wake phrase, barge-in, and a menu."""

from __future__ import annotations

import os
import threading
import time

import pystray
from PIL import Image, ImageDraw

from ..app import build_assistant
from ..audio.stt import build_stt
from ..audio.voice import VoiceInput
from ..config import CONFIG_PATH, ensure_config
from ..text import safe_print
from ..voice_loop import VoiceLoop
from .display import TrayDisplay


class TrayVoiceAssistant:
    """Tray icon + a worker thread that runs the VoiceLoop while listening is on."""

    def __init__(self) -> None:
        self.listening = threading.Event()
        self.shutdown = threading.Event()
        self.icon = pystray.Icon(
            "mika_voice_assistant",
            self.make_icon(active=False),
            "Mika Voice Assistant",
            menu=pystray.Menu(
                pystray.MenuItem("Mulai dengar", self.start_listening),
                pystray.MenuItem("Stop dengar", self.stop_listening),
                pystray.MenuItem("Diam (hentikan suara)", self.hush),
                pystray.MenuItem("Tes mikrofon", self.test_microphone),
                pystray.MenuItem("Settings", self.open_settings),
                pystray.MenuItem("Buka commands.json", self.open_config),
                pystray.MenuItem("Reload config", self.reload_config),
                pystray.MenuItem("Keluar", self.quit_app),
            ),
        )
        self._build()
        self.worker = threading.Thread(target=self.listen_loop, name="mika-listen", daemon=True)

    def _build(self) -> None:
        """(Re)create assistant, voice input, and loop from commands.json."""
        self.config = ensure_config()
        self.assistant = build_assistant(self.config, display=TrayDisplay(self.icon))
        self.speaker = self.assistant.speaker
        self.voice = VoiceInput(self.config, self.speaker, build_stt(self.config), interrupt=self.assistant.interrupt)
        self.loop = VoiceLoop(self.assistant, self.voice, wake_required=True)
        self.icon.title = f"{self.assistant.name} Voice Assistant"
        self.assistant.warm_up()

    def run(self) -> None:
        self.worker.start()
        self.start_listening()
        self.icon.run()

    def listen_loop(self) -> None:
        """Worker thread: one VoiceLoop step at a time while listening is on."""
        while not self.shutdown.is_set():
            if not self.listening.is_set() or not self.voice.is_running:
                time.sleep(0.25)
                continue
            if not self.loop.step(timeout=0.5):
                self.stop_listening()

    def start_listening(self, icon=None, item=None) -> None:
        try:
            self.voice.start()
        except Exception as exc:
            safe_print(f"[mic] {exc}")
            self.notify("Mikrofon tidak bisa dibuka", str(exc))
            self.speaker.say("Mikrofon belum bisa dipakai. Cek izin mikrofon dan pilihan device di Settings.")
            return
        self.listening.set()
        self.icon.icon = self.make_icon(active=True)
        self.speaker.say(f"{self.assistant.name} aktif. Awali perintah dengan Halo Mika.")

    def stop_listening(self, icon=None, item=None) -> None:
        self.listening.clear()
        self.voice.stop()
        self.icon.icon = self.make_icon(active=False)
        self.speaker.say("Mode dengar dihentikan.")

    def hush(self, icon=None, item=None) -> None:
        """Menu version of barge-in: stop talking right now."""
        self.assistant.interrupt()

    def reload_config(self, icon=None, item=None) -> None:
        was_listening = self.listening.is_set()
        self.listening.clear()
        self.voice.stop()
        self.speaker.stop()
        self._build()
        if was_listening:
            self.start_listening()
        self.speaker.say("Konfigurasi sudah dimuat ulang.")

    def test_microphone(self, icon=None, item=None) -> None:
        threading.Thread(target=self._test_microphone_worker, daemon=True).start()

    def _test_microphone_worker(self) -> None:
        """Say a prompt, take the next utterance with the configured engine, and report what was heard."""
        started_here = False
        if not self.voice.is_running:
            try:
                self.voice.start()
                started_here = True
            except Exception as exc:
                self.notify("Tes mikrofon gagal", str(exc))
                return
        self.speaker.say("Tes mikrofon. Setelah ini, ucapkan Halo Mika buka YouTube.")
        heard = self.loop.capture_test(timeout=8) if self.listening.is_set() else self.voice.next(timeout=8)
        if heard:
            message = f"Aku mendengar: {heard.text}"
            self.speaker.say(message)
            self.notify("Tes mikrofon berhasil", f"{message} ({heard.engine}, {heard.stt_seconds:.1f} detik)")
        else:
            self.speaker.say("Aku belum bisa menangkap suara. Cek izin mikrofon dan input device.")
            self.notify("Tes mikrofon gagal", "Cek izin mikrofon dan input device.")
        if started_here and not self.listening.is_set():
            self.voice.stop()

    def notify(self, title: str, message: str) -> None:
        try:
            self.icon.notify(message, title)
        except Exception:
            pass

    def open_settings(self, icon=None, item=None) -> None:
        threading.Thread(target=self._open_settings_worker, daemon=True).start()

    def _open_settings_worker(self) -> None:
        from .settings import open_settings_window

        open_settings_window(CONFIG_PATH)

    def open_config(self, icon=None, item=None) -> None:
        os.startfile(CONFIG_PATH)  # type: ignore[attr-defined]

    def quit_app(self, icon=None, item=None) -> None:
        self.shutdown.set()
        self.listening.clear()
        self.voice.stop()
        self.speaker.stop()
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
    TrayVoiceAssistant().run()
    return 0
