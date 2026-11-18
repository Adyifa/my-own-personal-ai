"""Entry point kept for run_text.bat / run_voice.bat and older imports.

The code now lives in the `mika` package:
  mika/audio   wake phrase, speech-to-text, text-to-speech
  mika/brain   rule router, LLM agent, tools, providers
  mika/skills  launcher, browser, power, web search
  mika/ui      tray, settings, on-screen details
"""

from __future__ import annotations

from mika.assistant import Assistant, PendingAction
from mika.audio.speech import Speaker
from mika.audio.stt import listen_once
from mika.cli import main, run_text_loop, run_voice_loop
from mika.config import APP_DIR, CONFIG_PATH, DEFAULT_CONFIG, apply_personality_preset, deep_merge, ensure_config
from mika.persona import CONVERSATION_REPLIES, VOICE_PERSONALITY_PRESETS
from mika.text import normalize, safe_print, strip_command_words

__all__ = [
    "APP_DIR",
    "Assistant",
    "CONFIG_PATH",
    "CONVERSATION_REPLIES",
    "DEFAULT_CONFIG",
    "PendingAction",
    "Speaker",
    "VOICE_PERSONALITY_PRESETS",
    "apply_personality_preset",
    "deep_merge",
    "ensure_config",
    "listen_once",
    "main",
    "normalize",
    "run_text_loop",
    "run_voice_loop",
    "safe_print",
    "strip_command_words",
]


if __name__ == "__main__":
    raise SystemExit(main())
