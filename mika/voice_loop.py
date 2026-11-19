"""The listening loop shared by the tray app and the console: heard text → wake-phrase gate → Assistant.handle."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from .audio.voice import Heard
from .text import safe_print


class VoiceLoop:
    """Gates transcripts by the wake phrase ("halo mika ..."), with exceptions for follow-ups,
    pending confirmations, and barge-in; then hands the command to the assistant."""

    def __init__(
        self,
        assistant: Any,
        voice: Any,
        *,
        wake_required: bool = True,
        clock: Callable[[], float] = time.time,
    ):
        self.assistant = assistant
        self.voice = voice
        self.wake_required = wake_required
        self._clock = clock
        self.awaiting_command_until = 0.0
        self.stop_event = threading.Event()
        self._probe: list[Heard] | None = None  # set by capture_test()
        self._probe_ready = threading.Event()

    @property
    def config(self) -> dict[str, Any]:
        """The assistant's live config (reloads are picked up)."""
        return self.assistant.config

    def prepare(self, heard: Heard) -> str | None:
        """The command to run, or None when the utterance was not meant for Mika."""
        text = heard.text
        assistant = self.assistant
        wake_config = self.config.get("wake", {})
        now = self._clock()
        if assistant.pending_action:
            return text  # "iya" / "batal" need no wake phrase
        matched, stripped = assistant.strip_wake_prefix(text)
        if matched and wake_config.get("enabled", True):
            if not stripped:
                self.awaiting_command_until = now + float(wake_config.get("next_command_seconds", 8))
                assistant.speaker.say(str(self.config.get("personality", {}).get("listening_reply", "Iya, mau aku bantu apa?")))
                return None
            self.awaiting_command_until = 0.0
            return stripped
        if heard.barge_in or not self.wake_required or not wake_config.get("enabled", True):
            return text
        if assistant.conversation_is_active():
            return text  # follow-up mode right after Mika answered
        if now <= self.awaiting_command_until:
            self.awaiting_command_until = 0.0
            return text
        safe_print("[wake] Diabaikan karena tidak diawali wake phrase.")
        return None

    def step(self, timeout: float = 0.5) -> bool:
        """Process at most one utterance; returns False once the user told Mika to stop."""
        heard = self.voice.next(timeout)
        if heard is None:
            return True
        if self._probe is not None:
            self._probe.append(heard)
            self._probe_ready.set()
            return True
        safe_print(f"Kamu: {heard.text}  [{heard.engine} {heard.stt_seconds:.2f}s]")
        command = self.prepare(heard)
        if command is None:
            return True
        try:
            return bool(self.assistant.handle(command, heard=heard))
        except Exception as exc:  # one bad turn must not kill the listening thread
            safe_print(f"[error] {exc}")
            return True

    def run(self) -> None:
        """Loop until stop() or a "keluar" command."""
        while not self.stop_event.is_set():
            if not self.step():
                break

    def stop(self) -> None:
        """Ask run() to return after the current step."""
        self.stop_event.set()

    def capture_test(self, timeout: float = 8.0) -> Heard | None:
        """Mic test: return the next utterance instead of handling it (used by the tray menu)."""
        self._probe = []
        self._probe_ready.clear()
        try:
            self._probe_ready.wait(timeout)
            return self._probe[0] if self._probe else None
        finally:
            self._probe = None
