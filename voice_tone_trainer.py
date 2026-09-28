from __future__ import annotations

import argparse
import json
import math
import statistics
import struct
import time
import wave
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PROJECT_DIR / "commands.json"
DEFAULT_PROFILE_DIR = PROJECT_DIR / "voice_profiles"


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(clamp(round((len(ordered) - 1) * ratio), 0, len(ordered) - 1))
    return ordered[index]


def format_percent(value: int) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value}%"


def format_hz(value: int) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value}Hz"


def require_rights(args: argparse.Namespace) -> None:
    if not getattr(args, "i_have_rights", False):
        raise SystemExit(
            "Tambahkan --i-have-rights untuk konfirmasi bahwa semua rekaman adalah suara kamu sendiri "
            "atau suara yang kamu punya izin tertulis untuk dianalisis."
        )


def read_wav_mono(path: Path) -> tuple[list[float], int]:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frames = wav_file.readframes(wav_file.getnframes())

    if sample_width not in (1, 2):
        raise ValueError(f"{path.name}: hanya WAV PCM 8-bit atau 16-bit yang didukung.")

    if sample_width == 1:
        raw = [sample - 128 for sample in frames]
        scale = 128.0
    else:
        count = len(frames) // 2
        raw = list(struct.unpack("<" + "h" * count, frames))
        scale = 32768.0

    if channels > 1:
        mono: list[float] = []
        for index in range(0, len(raw), channels):
            mono.append(sum(raw[index : index + channels]) / (channels * scale))
        return mono, sample_rate

    return [sample / scale for sample in raw], sample_rate


def frame_signal(samples: list[float], sample_rate: int, frame_ms: int = 40, hop_ms: int = 20) -> list[list[float]]:
    frame_size = max(1, int(sample_rate * frame_ms / 1000))
    hop_size = max(1, int(sample_rate * hop_ms / 1000))
    frames: list[list[float]] = []
    for start in range(0, max(0, len(samples) - frame_size + 1), hop_size):
        frames.append(samples[start : start + frame_size])
    return frames


def rms(frame: list[float]) -> float:
    if not frame:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in frame) / len(frame))


def estimate_pitch(frame: list[float], sample_rate: int, fmin: int = 75, fmax: int = 360) -> float | None:
    if not frame:
        return None

    mean = sum(frame) / len(frame)
    centered = [sample - mean for sample in frame]
    energy = sum(sample * sample for sample in centered)
    if energy < 0.001:
        return None

    min_lag = max(1, int(sample_rate / fmax))
    max_lag = min(len(centered) - 2, int(sample_rate / fmin))
    if max_lag <= min_lag:
        return None

    best_lag = 0
    best_score = 0.0
    for lag in range(min_lag, max_lag + 1):
        score = 0.0
        for index in range(0, len(centered) - lag):
            score += centered[index] * centered[index + lag]
        if score > best_score:
            best_score = score
            best_lag = lag

    confidence = best_score / energy
    if best_lag <= 0 or confidence < 0.32:
        return None

    return sample_rate / best_lag


def collect_wav_files(samples_path: Path) -> list[Path]:
    if samples_path.is_file() and samples_path.suffix.lower() == ".wav":
        return [samples_path]
    if not samples_path.exists():
        raise FileNotFoundError(f"Folder sample tidak ditemukan: {samples_path}")
    files = sorted(path for path in samples_path.rglob("*.wav") if path.is_file())
    if not files:
        raise FileNotFoundError(f"Tidak ada file .wav di: {samples_path}")
    return files


def analyze_samples(samples_path: Path) -> dict[str, Any]:
    wav_files = collect_wav_files(samples_path)
    all_rms: list[float] = []
    all_pitch: list[float] = []
    total_frames = 0
    active_frames = 0
    total_duration = 0.0

    for wav_path in wav_files:
        samples, sample_rate = read_wav_mono(wav_path)
        frames = frame_signal(samples, sample_rate)
        frame_rms = [rms(frame) for frame in frames]
        low_energy = percentile(frame_rms, 0.20)
        high_energy = percentile(frame_rms, 0.75)
        threshold = max(low_energy + ((high_energy - low_energy) * 0.35), high_energy * 0.12, 0.006)

        for frame, energy in zip(frames, frame_rms):
            total_frames += 1
            all_rms.append(energy)
            if energy >= threshold:
                active_frames += 1
                pitch = estimate_pitch(frame, sample_rate)
                if pitch is not None:
                    all_pitch.append(pitch)

        total_duration += len(samples) / sample_rate

    median_pitch = statistics.median(all_pitch) if all_pitch else 205.0
    median_rms = statistics.median(all_rms) if all_rms else 0.0
    active_ratio = active_frames / total_frames if total_frames else 0.0
    pause_ratio = 1.0 - active_ratio

    edge_pitch_hz = int(clamp(round((median_pitch - 205.0) * 0.16), -18, 18))
    if pause_ratio < 0.18:
        edge_rate_percent = 10
    elif pause_ratio < 0.28:
        edge_rate_percent = 6
    elif pause_ratio < 0.38:
        edge_rate_percent = 2
    elif pause_ratio < 0.50:
        edge_rate_percent = -2
    else:
        edge_rate_percent = -6

    sapi_rate = int(clamp(175 + (edge_rate_percent * 2.2), 135, 210))

    if median_pitch >= 235 and edge_rate_percent >= 6:
        tone_label = "bright"
    elif pause_ratio >= 0.45:
        tone_label = "calm"
    elif median_pitch <= 175:
        tone_label = "warm_low"
    else:
        tone_label = "balanced"

    return {
        "source": {
            "path": str(samples_path),
            "file_count": len(wav_files),
            "duration_seconds": round(total_duration, 2),
        },
        "metrics": {
            "median_pitch_hz": round(median_pitch, 2),
            "median_rms": round(median_rms, 5),
            "active_ratio": round(active_ratio, 3),
            "pause_ratio": round(pause_ratio, 3),
            "pitch_sample_count": len(all_pitch),
            "tone_label": tone_label,
        },
        "recommended_voice": {
            "provider": "edge",
            "edge_voice": "id-ID-GadisNeural",
            "edge_rate": format_percent(edge_rate_percent),
            "edge_pitch": format_hz(edge_pitch_hz),
            "edge_volume": "+0%",
            "rate": sapi_rate,
        },
        "note": (
            "Ini tone/prosody matching, bukan voice cloning. Gunakan hanya dengan rekaman yang legal "
            "dan jangan pakai untuk meniru identitas suara orang/karakter tanpa izin."
        ),
    }


def save_profile(name: str, analysis: dict[str, Any], profile_dir: Path = DEFAULT_PROFILE_DIR) -> Path:
    profile_path = profile_dir / name / "profile.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8")
    return profile_path


def apply_profile(profile_path: Path, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    voice = profile.get("recommended_voice", {})
    config.setdefault("voice", {}).update(voice)
    config.setdefault("personality", {})["preset"] = "custom"
    config.setdefault("voice_profile", {})
    config["voice_profile"].update(
        {
            "source_profile": str(profile_path),
            "tone_label": profile.get("metrics", {}).get("tone_label", "custom"),
            "median_pitch_hz": profile.get("metrics", {}).get("median_pitch_hz"),
            "training_type": "tone_matching_not_voice_cloning",
        }
    )
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def record_wav(path: Path, seconds: float, device_index: int | None = None, sample_rate: int = 16000) -> None:
    try:
        import pyaudio
    except ImportError as exc:
        raise SystemExit("PyAudio belum terpasang. Jalankan: python -m pip install -r requirements.txt") from exc

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
    print(f"Mulai rekam {seconds:.1f} detik. Baca teks natural, jangan dibuat-buat.")
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
    print(f"Sample tersimpan: {path}")


def command_record(args: argparse.Namespace) -> None:
    require_rights(args)
    sample_dir = DEFAULT_PROFILE_DIR / args.name / "samples"
    sample_path = sample_dir / f"sample_{int(time.time())}.wav"
    record_wav(sample_path, args.seconds, args.device_index, args.sample_rate)


def command_analyze(args: argparse.Namespace) -> None:
    require_rights(args)
    samples_path = Path(args.samples) if args.samples else DEFAULT_PROFILE_DIR / args.name / "samples"
    analysis = analyze_samples(samples_path)
    profile_path = save_profile(args.name, analysis)
    print(json.dumps(analysis, indent=2, ensure_ascii=False))
    print(f"\nProfile tersimpan: {profile_path}")
    if args.apply:
        apply_profile(profile_path, Path(args.config))
        print(f"Applied ke config: {args.config}")


def command_apply(args: argparse.Namespace) -> None:
    require_rights(args)
    apply_profile(Path(args.profile), Path(args.config))
    print(f"Applied ke config: {args.config}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Tone trainer legal untuk Mika. Ini bukan voice cloning dan tidak meniru identitas suara."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    record_parser = subparsers.add_parser("record", help="Rekam sample WAV dari suara yang kamu punya izin.")
    record_parser.add_argument("--name", required=True, help="Nama profile, contoh: my_voice")
    record_parser.add_argument("--seconds", type=float, default=45.0)
    record_parser.add_argument("--device-index", type=int, default=None)
    record_parser.add_argument("--sample-rate", type=int, default=16000)
    record_parser.add_argument("--i-have-rights", action="store_true")
    record_parser.set_defaults(func=command_record)

    analyze_parser = subparsers.add_parser("analyze", help="Analisis sample WAV dan buat rekomendasi tone.")
    analyze_parser.add_argument("--name", required=True, help="Nama profile output.")
    analyze_parser.add_argument("--samples", default="", help="File/folder WAV. Default: voice_profiles/<name>/samples")
    analyze_parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    analyze_parser.add_argument("--apply", action="store_true", help="Langsung apply ke commands.json.")
    analyze_parser.add_argument("--i-have-rights", action="store_true")
    analyze_parser.set_defaults(func=command_analyze)

    apply_parser = subparsers.add_parser("apply", help="Apply profile.json ke commands.json.")
    apply_parser.add_argument("--profile", required=True)
    apply_parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    apply_parser.add_argument("--i-have-rights", action="store_true")
    apply_parser.set_defaults(func=command_apply)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
