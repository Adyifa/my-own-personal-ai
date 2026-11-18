"""Main flow for one utterance: wake phrase → confirmation? → router → rule path or LLM agent (offline fallback)."""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .audio.wake import strip_wake_prefix
from .brain.router import Route, Router
from .persona import CONVERSATION_REPLIES, VOICE_PERSONALITY_PRESETS
from .skills.browser import search_url, spotify_url
from .skills.launcher import Launcher
from .skills.power import execute_power_action
from .text import clean_conversational_command, normalize, safe_print


@dataclass
class PendingAction:
    """A risky action waiting for the user's spoken "iya" before it expires."""

    action: str
    label: str
    created_at: float
    expires_at: float
    execute: Callable[[], Any] | None = None


class Assistant:
    """Ties router, local skills, LLM agent, speaker, and display together."""

    def __init__(
        self,
        config: dict[str, Any],
        speaker: Any,
        *,
        launcher: Launcher | None = None,
        agent: Any = None,
        display: Any = None,
        power_runner: Callable[[str], Any] = execute_power_action,
    ):
        self.config = config
        self.speaker = speaker
        self.name = config.get("assistant_name", "Assistant")
        self.launcher = launcher or Launcher(config)
        self.router = Router(config, self.launcher)
        self.agent = agent
        self.display = display
        self.power_runner = power_runner
        self.pending_action: PendingAction | None = None
        self.conversation_until = 0.0
        self.last_route: Route | None = None
        self.last_reply: Any = None

    # Entry point ------------------------------------------------------------------------

    def handle(self, raw_command: str) -> bool:
        """Handle one utterance. Returns False when the user asked Mika to stop."""
        started = time.perf_counter()
        mark_turn = getattr(self.speaker, "mark_turn", None)
        if callable(mark_turn):
            mark_turn()

        wake_matched, command = self.strip_wake_prefix(normalize(raw_command))
        # The LLM gets the user's own wording; the router gets the cleaned command.
        llm_text = command if wake_matched else raw_command.strip()
        command = clean_conversational_command(command)
        if not command:
            self.speaker.say(self.message("empty_command", "Aku belum menangkap perintahnya."))
            return True

        if self.handle_pending_confirmation(command):
            return True

        route = self.router.route(command)
        self.last_route = route
        safe_print(f"[route] {route.path}:{route.intent}")
        if route.path == "rule":
            keep_running = self.run_rule(route, command)
        else:
            keep_running = self.run_agent(route, llm_text or command, command)

        first_audio = getattr(self.speaker, "first_audio_at", None)
        if first_audio is not None:
            safe_print(f"[latency] {route.path}:{route.intent} first_audio={first_audio - started:.2f}s")
        return keep_running

    def warm_up(self) -> None:
        """Pre-scan apps and load the LLM in the background so the first command is fast."""

        def warm_disk_and_voice() -> None:
            for name, step in (("Scan aplikasi", self.launcher.warm_up), ("TTS", getattr(self.speaker, "warm_up", None))):
                if not callable(step):
                    continue
                try:
                    step()
                except Exception as exc:
                    safe_print(f"[warmup] {name} gagal: {exc}")

        def warm_llm() -> None:
            try:
                self.agent.warm_up()
            except Exception as exc:
                safe_print(f"[warmup] LLM belum siap: {exc}")

        threading.Thread(target=warm_disk_and_voice, name="mika-warmup", daemon=True).start()
        if self.agent is not None and self.config.get("llm", {}).get("warmup", True):
            # Separate thread: loading a model into VRAM can take several seconds.
            threading.Thread(target=warm_llm, name="mika-warmup-llm", daemon=True).start()

    # Rule path --------------------------------------------------------------------------

    def run_rule(self, route: Route, command: str) -> bool:
        """Execute a rule-path intent locally with a template reply (no LLM involved)."""
        intent, args = route.intent, route.args
        if intent == "stop":
            self.speaker.say(self.message("stop_reply", "Baik, aku berhenti dulu."))
            return False
        if intent == "empty":
            self.speaker.say(self.message("empty_command", "Aku belum menangkap perintahnya."))
        elif intent == "help":
            self.say_help()
        elif intent == "conversation_stop":
            self.stop_conversation()
            self.speaker.say(self.chat_reply("conversation_stop", "Oke, mode ngobrol aku tutup dulu."))
        elif intent == "ask_target":
            self.speaker.say(self.message("ask_target", "Mau buka apa?"))
        elif intent == "ask_search_query":
            self.speaker.say("Mau cari apa?")
        elif intent == "ask_music":
            self.speaker.say("Mau putar lagu apa?")
        elif intent == "power":
            question = self.request_confirmation(
                args["action"], args["label"], lambda: self.power_runner(args["action"])
            )
            self.speaker.say(question)
        elif intent == "music":
            self.launcher.open_url(spotify_url(self.config, args["query"]))
            self.speaker.say(self.message("music_reply", "Mencari {query} di Spotify.", query=args["query"]))
        elif intent == "browser_search":
            self.open_browser_search(args["provider"], args["query"])
        elif intent == "open_file":
            path = self.launcher.resolve_file(args["query"], args.get("command"))
            if path is not None and self.launcher.open_path(path):
                self.say_opened(Path(path).name or args["query"])
            else:
                self.speaker.say(self.message("file_not_found", "Aku belum nemu file atau folder itu."))
        elif intent == "open_file_alias":
            if self.launcher.open_path(Path(args["path"])):
                self.say_opened(args["name"])
            else:
                self.speaker.say(f"Path untuk {args['name']} belum ditemukan: {args['path']}")
        elif intent == "open_website":
            self.launcher.open_url(args["url"])
            if args.get("kind") == "url":
                self.speaker.say(self.message("open_website_reply", "Membuka website {target}.", target=args["name"]))
            else:
                self.say_opened(args["name"])
        elif intent in ("open_app", "open_game"):
            try:
                self.launcher.launch(args["target"])
                self.say_opened(args["name"])
            except Exception as exc:
                safe_print(f"[launch] {args['target']}: {exc}")
                self.speaker.say(f"Maaf, {args['name']} gagal dibuka.")
        else:
            safe_print(f"[route] Intent aturan tidak dikenal: {intent}")
        return True

    def open_browser_search(self, provider: str, query: str) -> None:
        """Open a Google/YouTube results page and say so."""
        url = search_url(self.config, provider, query)
        if url is None:
            self.speaker.say(f"Aku belum punya pengaturan pencarian untuk {provider}.")
            return
        self.launcher.open_url(url)
        if provider == "youtube_first":
            self.speaker.say(
                self.message("youtube_first_reply", "Aku buka hasil YouTube paling cocok untuk {query}.", query=query)
            )
        else:
            self.speaker.say(self.message("search_reply", "Mencari {query} di {provider}.", query=query, provider=provider))

    # Agent path -------------------------------------------------------------------------

    def run_agent(self, route: Route, text: str, command: str) -> bool:
        """Let the LLM answer; if no model is reachable, behave like the pre-AI Mika."""
        if self.agent is None:
            return self.offline_fallback(route, command)

        from .brain.llm.base import LLMError

        try:
            reply = self.agent.respond(text)
        except LLMError as exc:
            safe_print(f"[llm] {exc}")
            return self.offline_fallback(route, command)

        self.last_reply = reply
        wait = getattr(self.speaker, "wait", None)
        if callable(wait):
            wait()
        if not reply.pending_confirmation:
            # Follow-up mode: the next sentence within a few seconds needs no wake phrase.
            self.keep_conversation_alive()
        if reply.needs_display and self.display is not None:
            self.display.show(f"{self.name}", _display_body(reply))
        safe_print(
            f"[agent] provider={reply.provider or '-'} llm_calls={reply.llm_calls} "
            f"tools={reply.tools_used or '-'} first_token={_fmt_seconds(reply.first_token_seconds)}"
        )
        return True

    def offline_fallback(self, route: Route, command: str) -> bool:
        """What Mika did before the LLM existed, used when no model is reachable."""
        if route.intent == "chat":
            self.keep_conversation_alive()
            self.speaker.say(self.chat_reply(route.args.get("category", "greeting"), "Aku denger."))
        elif route.intent == "web_answer":
            provider = normalize(str(self.config.get("search", {}).get("default_provider", "google"))) or "google"
            self.speaker.say("Otak online Mika lagi nggak nyambung, jadi Mika bukain hasil pencariannya di browser ya.")
            self.open_browser_search(provider, route.args.get("query", command))
        elif route.intent == "open_unknown":
            self.speaker.say(
                self.message(
                    "unknown_reply",
                    "{not_found} '{target}'. Coba bilang buka, cari, putar, atau ngobrol.",
                    not_found=self.personality("not_found", "Aku belum nemu"),
                    target=route.args.get("target", command),
                )
            )
        else:
            self.speaker.say(self.chat_reply("unknown_chat", "Aku denger, tapi belum paham harus jawab apa."))
        return True

    # Confirmation -----------------------------------------------------------------------

    def request_confirmation(self, action: str, label: str, run: Callable[[], Any]) -> str:
        """Register a risky action; it only runs after the user says yes. Returns the question."""
        seconds = float(self.config.get("safety", {}).get("confirmation_seconds", 12))
        now = time.time()
        self.pending_action = PendingAction(action=action, label=label, created_at=now, expires_at=now + seconds, execute=run)
        return self.message("confirm_question", "Yakin? Bilang iya untuk lanjut. Kalau tidak, bilang batal.")

    def handle_pending_confirmation(self, command: str) -> bool:
        """While an action waits: "iya" runs it, "batal" cancels, anything else repeats the question."""
        if not self.pending_action:
            return False

        safety = self.config.get("safety", {})
        yes_words = {normalize(word) for word in safety.get("yes_words", [])}
        no_words = {normalize(word) for word in safety.get("no_words", [])}
        pending = self.pending_action

        if time.time() > pending.expires_at:
            self.pending_action = None
            self.speaker.say(self.message("confirm_expired", "Konfirmasinya sudah lewat. Aku batalin dulu, ya."))
            return True
        if command in yes_words:
            self.pending_action = None
            try:
                if pending.execute is not None:
                    pending.execute()
                else:
                    self.power_runner(pending.action)
            except Exception as exc:
                safe_print(f"[confirm] {pending.action} gagal: {exc}")
                self.speaker.say(f"Maaf, {pending.label} gagal dijalankan.")
                return True
            self.speaker.say(f"{self.personality('confirm_prefix', 'Oke')}, {pending.label}.")
            return True
        if command in no_words:
            self.pending_action = None
            self.speaker.say(self.message("confirm_cancelled", "Oke, aku batalin."))
            return True

        self.speaker.say(self.message("confirm_waiting", "Aku masih nunggu konfirmasi. Bilang iya atau batal."))
        return True

    # Persona and conversation state -----------------------------------------------------

    def strip_wake_prefix(self, command: str) -> tuple[bool, str]:
        return strip_wake_prefix(command, self.config.get("wake", {}))

    def personality(self, key: str, fallback: str) -> str:
        value = self.config.get("personality", {}).get(key, fallback)
        if isinstance(value, list):
            return str(random.choice(value)) if value else fallback
        return str(value)

    def message(self, key: str, fallback: str, **values: Any) -> str:
        template = self.personality(key, fallback)
        try:
            return template.format(**values)
        except (KeyError, ValueError, IndexError):
            return fallback.format(**values)

    def say_opened(self, target: str) -> None:
        self.speaker.say(self.message("open_reply", "Membuka {target}.", target=target))

    def preset_name(self) -> str:
        preset = normalize(str(self.config.get("personality", {}).get("preset", "cute"))) or "cute"
        return preset if preset in VOICE_PERSONALITY_PRESETS else "cute"

    def chat_reply(self, category: str, fallback: str, **values: Any) -> str:
        default_bank = CONVERSATION_REPLIES.get("cute", {})
        preset_bank = CONVERSATION_REPLIES.get(self.preset_name(), {})
        choices = preset_bank.get(category) or default_bank.get(category) or [fallback]
        template = random.choice(choices)
        try:
            return template.format(name=self.name, **values)
        except (KeyError, ValueError, IndexError):
            return fallback.format(name=self.name, **values)

    def say_help(self) -> None:
        websites = ", ".join(sorted(self.config.get("websites", {}).keys()))
        apps = ", ".join(sorted(self.config.get("apps", {}).keys()))
        ai_hint = (
            " Kamu juga bisa tanya apa saja, misalnya: halo mika, berita teknologi hari ini apa?"
            if self.agent is not None
            else ""
        )
        self.speaker.say(
            "Contoh perintah: halo mika buka youtube, halo mika cari tutorial python di youtube, "
            "halo mika aku mau main cs2 dong, halo mika sleep laptop, atau halo mika buka notepad. "
            f"Website tersedia: {websites or '-'}, aplikasi: {apps or '-'}.{ai_hint}"
        )

    def keep_conversation_alive(self) -> None:
        """Follow-up mode: for a few seconds the user can reply without saying "Halo Mika"."""
        conversation = self.config.get("conversation", {})
        if not conversation.get("enabled", True):
            return
        self.conversation_until = time.time() + float(conversation.get("continue_seconds", 18))

    def stop_conversation(self) -> None:
        """End follow-up mode and wipe the agent's short-term memory."""
        self.conversation_until = 0.0
        session = getattr(self.agent, "session", None)
        if session is not None:
            session.clear()

    def conversation_is_active(self) -> bool:
        return time.time() <= self.conversation_until


def _display_body(reply: Any) -> str:
    """Screen text: the full answer plus numbered sources with links."""
    body = reply.full_text or " ".join(reply.spoken)
    if reply.sources:
        lines = [f"{index}. {source.source} - {source.title}\n   {source.url}" for index, source in enumerate(reply.sources[:5], 1)]
        body += "\n\nSumber:\n" + "\n".join(lines)
    return body.strip()


def _fmt_seconds(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}s"
