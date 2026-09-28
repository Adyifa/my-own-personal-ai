from __future__ import annotations

import json

import speech_recognition as sr

from assistant import CONFIG_PATH, Speaker, ensure_config, listen_once


def main() -> int:
    config = ensure_config()
    speaker = Speaker.from_config(config)

    print("Daftar microphone yang terbaca:")
    for index, name in enumerate(sr.Microphone.list_microphone_names()):
        print(f"{index}: {name}")

    print()
    current_device = config.get("listen", {}).get("device_index")
    print(f"device_index di commands.json sekarang: {current_device}")
    print("Kalau default mic salah, isi listen.device_index dengan angka mic yang benar.")
    print()
    input("Tekan Enter, lalu ucapkan: buka youtube ...")

    command = listen_once(config, speaker, quiet=False)
    print()
    if command:
        print(f"Berhasil dengar: {command}")
    else:
        print("Belum berhasil menangkap suara.")
        print("Coba cek Settings > Privacy & security > Microphone, lalu pastikan izin mic aktif.")

    print()
    print(f"File config: {CONFIG_PATH}")
    print("Contoh setting device_index:")
    print(json.dumps({"listen": {"device_index": 1}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
