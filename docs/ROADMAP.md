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

## Stage 3: Audio (done)

- [x] Always-open microphone (PyAudio, 16 kHz frames, resampling fallback) instead of re-opening per sentence.
- [x] WebRTC VAD (energy fallback that learns steady background noise) + endpointer with pre-roll,
      minimum speech length, pause detection, and a maximum utterance length.
- [x] Selectable STT: Google (online) or faster-whisper (offline). Device choice from free VRAM and whether
      Ollama already holds the LLM; CPU int8 fallback when CUDA libraries are missing.
- [x] Whisper hallucination filter (silence phrases, subtitle credits, repetition) and transcript cleanup.
- [x] Barge-in: "keyword" mode (stop/wake words, echo rejected by comparing with Mika's recent speech),
      "voice" mode for headsets, "off"; interrupting closes the LLM stream. Tray menu "Diam".
- [x] Shared VoiceLoop for tray and console; mic test uses the configured engine; Settings tab "Suara & AI".
- [x] Per-turn latency log (end of speech → transcript → first token → first audio) in `data/latency.jsonl`.
- [x] Verified on the target laptop with synthetic Indonesian speech: real-time pipeline (frames → WebRTC VAD →
      endpointer → Whisper) gives a transcript ~0.7 s after the end of speech; CUDA → CPU fallback works when
      `cublas64_12.dll` is missing; Google 7/7 commands routed correctly, Whisper `tiny` 4/7.
- [ ] Whisper `small` accuracy/latency: the model download ran at ~100 KB/s on the development network, so only
      `tiny` was measured; re-measure `small` (and real voices, not synthetic) in stage 5.

## Stage 4: Beyond Alexa (done)

- [x] "Lihat layarku": screenshot (primary screen or active window) kept in memory only, downscaled JPEG,
      local vision model through Ollama (`qwen2.5vl:3b`); cloud vision is opt-in (`vision.allow_cloud`).
- [x] Clipboard: summarize, translate (copied back to the clipboard), explain, or read aloud (no AI needed);
      clipboard text is sanitized and treated as data.
- [x] Morning briefing (date, weather, today's reminders, headlines) and a fast "berita hari ini" from four RSS feeds;
      "selamat pagi" before 11:00 triggers the briefing.
- [x] Long-term memory in `data/memory.json`: remember / list / forget by voice, wiping everything needs a spoken
      "iya", secrets (passwords, PINs, card and ID numbers) are refused, relevant facts go into the system prompt.
- [x] Agent: 4 new tools; tool retrieval by keyword (rarely used tools only when relevant); taint tracking blocks
      memory writes after web, screen, or clipboard text was read in the same turn.
- [x] Verified on the target laptop: briefing with live weather and news (2.2 s), headlines (0.12 s), memory flow,
      screenshot capture and the "no vision model" path. Not yet run with a real vision model (Ollama not installed).

## Stage 5: Quality and presentation

- [x] Routing evaluation: 609 unique utterances in 30 categories (standard and casual Indonesian, Sundanese, Javanese,
      speech-to-text errors, English mixing, features that do not exist yet, curhat, self-harm statements, negations),
      each with the behaviour Mika should show. Run `python -m evals.routing`. 609/609 route as intended; the safety
      categories (power, disk, safety, crisis, curhat, unbuilt) must pass 100% in the test suite.
- [x] Two or three requests in one sentence ("matikan suara terus kunci laptop"), done in stage 6A.
- [ ] Latency benchmark for STT/LLM/TTS, 60-second demo script, AI tab in the Settings GUI, verified PyInstaller build.

## Stage 6: Companion (curhat)

Mika as a friend to talk to about work, relationships, and family, who listens first, remembers what matters,
may suggest options, and always leaves the decision to the user. Built in steps, each approved before the next.

- [x] A. One persona for the whole system: the user's name, register (aku-kamu, gue-lo, saya-Anda), advice style,
      and humor, set in the Settings tab "Kepribadian"; the AI gets it as instructions and every fixed reply passes
      through one converter. Offline curhat (work, love, family, friends, feelings, asking for advice) gets listening
      replies instead of "belum masuk command". Two or three commands in one sentence run step by step, with a
      confirmation step only allowed last. Spotify searches open in the app when it is installed.
- [x] B. Curhat mode for the AI: reflect feelings, at most one question, advice as options with trade-offs, no
      decisions for the user, no tools. Curhat goes only to local models (each provider reports whether it is local)
      unless companion.allow_cloud is on, and curhat turns are private: left out of the history of any request that may
      reach a cloud model. Follow-ups stay curhat for 45 s; commands still run. Without a local model Mika says so once
      and keeps listening with templates. Verified with scripted models and the real app's failure path; the model's
      actual replies are not checked yet (Ollama is not installed on the development laptop).
- [ ] C. Memory of past conversations: short local summaries (topics, feelings, open threads) recalled when the topic
      returns; people's names only after the user agrees; listable and deletable by voice; shared with other features.
- [ ] D. Learning from feedback ("aku cuma mau didengerin" becomes a style rule), optional check-ins, a weekly
      "what Mika learned" summary the user can edit.
- [ ] E. 50 to 100 multi-turn conversation tests run against the real model.
