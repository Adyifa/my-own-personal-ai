"""Microphone test (run_mic_test.bat): lists input devices, shows the live level, and transcribes one utterance
with the speech-to-text engine chosen in commands.json (Google or offline Whisper)."""

from __future__ import annotations

import json
import sys
import time

from mika.audio.capture import list_input_devices
from mika.audio.speech import Speaker
from mika.audio.stt import build_stt
from mika.audio.voice import VoiceInput
from mika.config import CONFIG_PATH, ensure_config


def main() -> int:
    config = ensure_config()
    config["barge_in"]["mode"] = "off"
    print("Microphone yang terbaca:")
    try:
        for device in list_input_devices():
            print(f"  {device['index']}: {device['name']} ({device['rate']} Hz)")
    except Exception as exc:
        print(f"  Gagal membaca daftar mic: {exc}")
    current = config.get("listen", {}).get("device_index")
    print(f"\nlisten.device_index sekarang: {current}  (kosong = mic default Windows)")

    stt = build_stt(config)
    print(f"Mesin speech-to-text: {stt.name}")
    if stt.name == "whisper":
        print("Memuat model Whisper (pertama kali akan mengunduh model)...")
        stt.warm_up()
        print(f"Whisper siap di {stt.device} ({stt.compute_type}) dalam {stt.load_seconds:.1f} detik: {stt.device_reason}")

    voice = VoiceInput(config, Speaker(enabled=False), stt)
    try:
        voice.start()
    except Exception as exc:
        print(f"\nMikrofon tidak bisa dibuka: {exc}")
        print("Cek Settings > Privacy & security > Microphone, lalu isi listen.device_index yang benar.")
        return 1

    print("\nUcapkan: halo mika buka youtube  (10 detik)")
    deadline = time.time() + 10
    heard = None
    try:
        while time.time() < deadline and heard is None:
            heard = voice.next(timeout=0.2)
            bar = "#" * min(40, int(voice.level / 150))
            sys.stdout.write(f"\r  level {bar:<40}")
            sys.stdout.flush()
    finally:
        voice.stop()
    print()
    if heard:
        print(f"Terdengar: {heard.text!r}  ({heard.engine}, {heard.stt_seconds:.2f} detik)")
    else:
        print("Belum ada ucapan yang tertangkap. Kalau level tidak bergerak saat bicara, mic yang dipilih salah.")

    print(f"\nFile config: {CONFIG_PATH}")
    print("Contoh pengaturan:")
    print(json.dumps({"listen": {"device_index": 1}, "stt": {"engine": "whisper"}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
