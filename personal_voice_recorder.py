from __future__ import annotations

import argparse
import json
import math
import struct
import time
import wave
import zipfile
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_PROMPTS = PROJECT_DIR / "personal_voice_prompts_id.txt"
DEFAULT_ROOT = PROJECT_DIR / "voice_models"


def require_own_voice(args: argparse.Namespace) -> None:
    if not getattr(args, "i_own_this_voice", False):
        raise SystemExit(
            "Tambahkan --i-own-this-voice untuk konfirmasi bahwa ini suara kamu sendiri "
            "dan kamu setuju dipakai untuk voice model personal."
        )


def profile_dir(name: str) -> Path:
    return DEFAULT_ROOT / safe_name(name)


def safe_name(name: str) -> str:
    safe = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in name.strip())
    return safe or "my_voice"


def load_prompts(path: Path, limit: int | None = None) -> list[str]:
    prompts = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            prompts.append(line)
    if limit:
        prompts = prompts[:limit]
    if not prompts:
        raise ValueError(f"Tidak ada prompt di {path}")
    return prompts


def list_devices() -> None:
    import pyaudio

    audio = pyaudio.PyAudio()
    try:
        for index in range(audio.get_device_count()):
            info = audio.get_device_info_by_index(index)
            if int(info.get("maxInputChannels", 0)) > 0:
                print(f"{index}: {info.get('name')} | input channels: {info.get('maxInputChannels')}")
    finally:
        audio.terminate()


def write_consent(target_dir: Path, name: str) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    consent = {
        "profile": safe_name(name),
        "statement": "I confirm this is my own voice and I consent to use it for my personal voice model.",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "training_scope": "personal local assistant voice only",
    }
    (target_dir / "CONSENT.json").write_text(json.dumps(consent, indent=2), encoding="utf-8")


def record_wav(path: Path, seconds: float, device_index: int | None, sample_rate: int) -> None:
    import pyaudio

    path.parent.mkdir(parents=True, exist_ok=True)
    audio = pyaudio.PyAudio()
    stream = audio.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=sample_rate,
        input=True,
        input_device_index=device_index,
        frames_per_buffer=1024,
    )
    frames: list[bytes] = []
    started = time.time()
    while time.time() - started < seconds:
        frames.append(stream.read(1024, exception_on_overflow=False))
    stream.stop_stream()
    stream.close()
    audio.terminate()

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"".join(frames))


def read_wav_int16(path: Path) -> tuple[list[int], int]:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        width = wav_file.getsampwidth()
        rate = wav_file.getframerate()
        frames = wav_file.readframes(wav_file.getnframes())
    if width != 2:
        raise ValueError(f"{path.name}: hanya WAV PCM 16-bit yang didukung.")
    values = list(struct.unpack("<" + "h" * (len(frames) // 2), frames))
    if channels > 1:
        mono = []
        for index in range(0, len(values), channels):
            mono.append(int(sum(values[index : index + channels]) / channels))
        values = mono
    return values, rate


def write_wav_int16(path: Path, samples: list[int], sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(struct.pack("<" + "h" * len(samples), *samples))


def frame_rms(samples: list[int], frame_size: int) -> list[float]:
    result = []
    for start in range(0, len(samples), frame_size):
        frame = samples[start : start + frame_size]
        if frame:
            result.append(math.sqrt(sum(sample * sample for sample in frame) / len(frame)))
    return result


def trim_and_normalize(samples: list[int], sample_rate: int) -> list[int]:
    if not samples:
        return samples
    frame_size = max(1, int(sample_rate * 0.02))
    rms_values = frame_rms(samples, frame_size)
    if not rms_values:
        return samples
    max_rms = max(rms_values)
    threshold = max(max_rms * 0.05, 200)
    active_frames = [index for index, value in enumerate(rms_values) if value >= threshold]
    if not active_frames:
        trimmed = samples
    else:
        start = max(0, active_frames[0] * frame_size - int(sample_rate * 0.15))
        end = min(len(samples), (active_frames[-1] + 1) * frame_size + int(sample_rate * 0.25))
        trimmed = samples[start:end]

    peak = max(abs(sample) for sample in trimmed) if trimmed else 0
    if peak <= 0:
        return trimmed
    gain = min(0.92 * 32767 / peak, 4.0)
    return [int(max(-32768, min(32767, sample * gain))) for sample in trimmed]


def command_record(args: argparse.Namespace) -> None:
    require_own_voice(args)
    prompts = load_prompts(Path(args.prompts), args.limit)
    root = profile_dir(args.name)
    raw_dir = root / "raw"
    write_consent(root, args.name)

    manifest: list[dict[str, Any]] = []
    print(f"Profile: {root}")
    print("Tips: pakai ruangan senyap, mic dekat, dan baca natural.")
    for index, prompt in enumerate(prompts, start=1):
        wav_path = raw_dir / f"{index:04d}.wav"
        if wav_path.exists() and not args.overwrite:
            print(f"Skip existing {wav_path.name}")
        else:
            print("\n" + "-" * 64)
            print(f"Prompt {index}/{len(prompts)}:")
            print(prompt)
            input("Tekan Enter untuk mulai rekam...")
            print("Rekam...")
            record_wav(wav_path, args.seconds_per_prompt, args.device_index, args.sample_rate)
            print(f"Tersimpan: {wav_path}")
        manifest.append({"id": f"{index:04d}", "text": prompt, "raw_wav": str(wav_path)})

    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSelesai. Lanjut prepare dataset:\npython personal_voice_recorder.py prepare --name {safe_name(args.name)} --i-own-this-voice")


def command_prepare(args: argparse.Namespace) -> None:
    require_own_voice(args)
    root = profile_dir(args.name)
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"manifest.json tidak ditemukan: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    wav_dir = root / "wavs"
    metadata_lines = []
    for item in manifest:
        raw_path = Path(item["raw_wav"])
        samples, sample_rate = read_wav_int16(raw_path)
        clean = trim_and_normalize(samples, sample_rate)
        clean_path = wav_dir / f"{item['id']}.wav"
        write_wav_int16(clean_path, clean, sample_rate)
        text = str(item["text"]).replace("|", " ")
        metadata_lines.append(f"wavs/{item['id']}.wav|{text}|{text}")

    metadata_path = root / "metadata.csv"
    metadata_path.write_text("\n".join(metadata_lines) + "\n", encoding="utf-8")
    print(f"Dataset siap: {root}")
    print(f"Metadata: {metadata_path}")


def command_package_kaggle(args: argparse.Namespace) -> None:
    require_own_voice(args)
    root = profile_dir(args.name)
    metadata_path = root / "metadata.csv"
    wav_dir = root / "wavs"
    if not metadata_path.exists() or not wav_dir.exists():
        raise SystemExit("Dataset belum siap. Jalankan command prepare dulu.")

    export_dir = DEFAULT_ROOT / "_kaggle_exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    zip_path = export_dir / f"{safe_name(args.name)}_kaggle_dataset.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(metadata_path, "metadata.csv")
        consent_path = root / "CONSENT.json"
        if consent_path.exists():
            archive.write(consent_path, "CONSENT.json")
        for wav_path in sorted(wav_dir.glob("*.wav")):
            archive.write(wav_path, f"wavs/{wav_path.name}")

    print(f"Kaggle dataset zip siap: {zip_path}")
    print("Upload zip ini ke Kaggle Dataset, lalu pakai kaggle_personal_voice_train.py di notebook/script Kaggle.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recorder dataset suara pribadi untuk Mika.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    devices = subparsers.add_parser("list-devices", help="Tampilkan microphone input.")
    devices.set_defaults(func=lambda args: list_devices())

    record = subparsers.add_parser("record", help="Rekam prompt menjadi WAV.")
    record.add_argument("--name", required=True)
    record.add_argument("--prompts", default=str(DEFAULT_PROMPTS))
    record.add_argument("--seconds-per-prompt", type=float, default=7.0)
    record.add_argument("--sample-rate", type=int, default=22050)
    record.add_argument("--device-index", type=int, default=None)
    record.add_argument("--limit", type=int, default=None)
    record.add_argument("--overwrite", action="store_true")
    record.add_argument("--i-own-this-voice", action="store_true")
    record.set_defaults(func=command_record)

    prepare = subparsers.add_parser("prepare", help="Trim, normalize, dan buat metadata.csv.")
    prepare.add_argument("--name", required=True)
    prepare.add_argument("--i-own-this-voice", action="store_true")
    prepare.set_defaults(func=command_prepare)

    package = subparsers.add_parser("package-kaggle", help="Zip dataset agar mudah diupload ke Kaggle.")
    package.add_argument("--name", required=True)
    package.add_argument("--i-own-this-voice", action="store_true")
    package.set_defaults(func=command_package_kaggle)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
