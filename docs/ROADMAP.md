# Mika 2.0 roadmap

Goal: turn Mika from a rule-based launcher into a personal, Alexa-style AI assistant that
runs on a Windows laptop (RTX 3050, 4 GB VRAM), while keeping the old fast, offline commands.

## Stage 1: LLM agent core (done)

- [x] Split `assistant.py` into the `mika/` package (audio, brain, skills, ui, config); keep
      `assistant.py`, `tray_assistant.py`, `settings_gui.py` as entry points.
- [x] LLM providers: Ollama native API (`think: false`, keep-alive, warm-up) and any
      OpenAI-compatible endpoint, with automatic fallback and a failure cooldown.
- [x] Pure rule router (fast path, offline) → LLM agent with tool calling for everything else.
- [x] Tools: open app/game, website, file; web search + read pages + cite source; open a
      result in the browser; Spotify; power actions behind voice confirmation.
- [x] Streaming speech: speak sentence by sentence, at most 3 sentences; `[DETAIL]` goes to screen.
- [x] Short-term conversation context.
- [x] pytest suite with mocked STT/TTS/LLM.

## Stage 2: Alexa-style skills (done)

- [x] Indonesian time parser: relative ("30 menit lagi"), clock ("jam setengah 8 malam", "19.30",
      "jam 10 kurang seperempat"), day words ("besok", "lusa", "hari Senin"), spelled-out numbers.
- [x] Timers, reminders, alarms: saved to `data/reminders.json`, 1-second scheduler thread, chime + voice +
      notification, missed reminders announced late after a restart, snooze, list and cancel by name.
- [x] Follow-up questions without the wake phrase ("Mau diingatkan kapan?" → "jam 9 malam").
- [x] Weather from Open-Meteo (no key), default city in config, details on screen.
- [x] Date and time (offline), media keys, exact volume via Core Audio (key-press fallback), battery and
      CPU/RAM/disk via psutil, quick notes in `data/notes.md`.
- [x] Same skills exposed to the agent as 5 grouped tools; the LLM extracts the time phrase, the parser computes it.
- [x] Verified live on the target laptop (read-only checks; volume set to its own value).

## Stage 3: Audio

Selectable STT (Google or faster-whisper + VAD; Whisper on CPU int8 when the LLM holds the GPU),
barge-in (stop speaking when the user talks), per-stage latency tracking.

## Stage 4: Beyond Alexa

"Lihat layarku" (screenshot → vision model), summarize/translate the clipboard,
morning briefing, long-term memory about the user that can be listed and deleted by voice.

## Stage 5: Quality and presentation

Eval set of ~50 Indonesian utterances → expected route/tool (routing accuracy) and a latency
benchmark for STT/LLM/TTS; English README with architecture diagram, setup, 60-second demo script;
AI tab in the Settings GUI; verified PyInstaller build.
