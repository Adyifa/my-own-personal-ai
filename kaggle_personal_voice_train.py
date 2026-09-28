from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path


WORKING_DIR = Path("/kaggle/working") if Path("/kaggle").exists() else Path.cwd()


def require_own_voice(args: argparse.Namespace) -> None:
    if not getattr(args, "i_own_this_voice", False):
        raise SystemExit(
            "Tambahkan --i-own-this-voice untuk konfirmasi dataset ini suara kamu sendiri "
            "dan kamu setuju dipakai untuk model personal."
        )


def ensure_training_deps() -> None:
    try:
        import TTS  # noqa: F401
        import trainer  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "Dependency belum ada. Di Kaggle, jalankan dulu:\n"
            "!pip install -q TTS>=0.22.0 torch torchaudio"
        ) from exc


def resolve_dataset(input_path: Path, unpack_dir: Path) -> Path:
    input_path = input_path.resolve()
    if input_path.is_file() and input_path.suffix.lower() == ".zip":
        unpack_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(input_path, "r") as archive:
            archive.extractall(unpack_dir)
        return find_dataset_dir(unpack_dir)
    if input_path.is_dir():
        return find_dataset_dir(input_path)
    raise FileNotFoundError(f"Dataset tidak ditemukan: {input_path}")


def find_dataset_dir(path: Path) -> Path:
    if (path / "metadata.csv").exists() and (path / "wavs").exists():
        return path
    matches = [item.parent for item in path.rglob("metadata.csv") if (item.parent / "wavs").exists()]
    if not matches:
        raise FileNotFoundError(f"Tidak menemukan metadata.csv + folder wavs di: {path}")
    return matches[0]


def validate_dataset(dataset_dir: Path) -> None:
    metadata_path = dataset_dir / "metadata.csv"
    wav_dir = dataset_dir / "wavs"
    if not metadata_path.exists():
        raise FileNotFoundError(f"metadata.csv tidak ada: {metadata_path}")
    if not wav_dir.exists():
        raise FileNotFoundError(f"folder wavs tidak ada: {wav_dir}")

    lines = [line.strip() for line in metadata_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise ValueError("metadata.csv kosong.")
    missing = []
    for line in lines:
        wav_rel = line.split("|", 1)[0]
        if not (dataset_dir / wav_rel).exists():
            missing.append(wav_rel)
    if missing:
        preview = ", ".join(missing[:5])
        raise FileNotFoundError(f"Ada WAV yang hilang di metadata: {preview}")
    print(f"Dataset OK: {dataset_dir}")
    print(f"Jumlah sample: {len(lines)}")


def train_vits(args: argparse.Namespace) -> Path:
    require_own_voice(args)
    ensure_training_deps()

    from trainer import Trainer, TrainerArgs
    from TTS.config.shared_configs import BaseDatasetConfig
    from TTS.tts.configs.vits_config import VitsConfig
    from TTS.tts.datasets import load_tts_samples
    from TTS.tts.models.vits import Vits
    from TTS.tts.utils.text.tokenizer import TTSTokenizer
    from TTS.utils.audio import AudioProcessor

    dataset_dir = resolve_dataset(Path(args.dataset), Path(args.unpack_dir))
    validate_dataset(dataset_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    dataset = BaseDatasetConfig(
        formatter="ljspeech",
        meta_file_train="metadata.csv",
        path=str(dataset_dir),
        language=args.language,
    )
    config = VitsConfig(
        batch_size=args.batch_size,
        eval_batch_size=max(1, min(args.batch_size, 4)),
        num_loader_workers=args.num_workers,
        num_eval_loader_workers=args.num_workers,
        run_eval=True,
        test_delay_epochs=-1,
        epochs=args.epochs,
        text_cleaner="basic_cleaners",
        use_phonemes=False,
        print_step=25,
        print_eval=False,
        mixed_precision=args.mixed_precision,
        output_path=str(output_dir),
        datasets=[dataset],
        cudnn_benchmark=False,
    )

    audio_processor = AudioProcessor.init_from_config(config)
    tokenizer, config = TTSTokenizer.init_from_config(config)
    train_samples, eval_samples = load_tts_samples(
        dataset,
        eval_split=True,
        eval_split_max_size=args.eval_max_size,
        eval_split_size=args.eval_split_size,
    )
    model = Vits(config, audio_processor, tokenizer, speaker_manager=None)
    trainer = Trainer(
        TrainerArgs(restore_path=args.restore_path or None),
        config,
        str(output_dir),
        model=model,
        train_samples=train_samples,
        eval_samples=eval_samples,
    )
    trainer.fit()
    return output_dir


def newest(paths: list[Path]) -> Path | None:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def find_artifacts(output_dir: Path) -> tuple[Path | None, Path | None]:
    model_candidates = list(output_dir.rglob("best_model*.pth")) + list(output_dir.rglob("checkpoint*.pth"))
    config_candidates = list(output_dir.rglob("config.json"))
    return newest(model_candidates), newest(config_candidates)


def export_artifacts(output_dir: Path, export_dir: Path) -> Path:
    export_dir.mkdir(parents=True, exist_ok=True)
    model_path, config_path = find_artifacts(output_dir)
    if model_path and config_path:
        shutil.copy2(model_path, export_dir / model_path.name)
        shutil.copy2(config_path, export_dir / "config.json")
        manifest = {
            "model_file": model_path.name,
            "config_file": "config.json",
            "training_type": "personal_vits",
            "note": "Download folder/zip ini ke laptop, lalu apply ke Mika dengan personal_voice_train_vits.py apply-model.",
        }
        (export_dir / "mika_voice_artifacts.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    else:
        print("Best model/config belum ditemukan. Semua output training akan dizip.")

    zip_path = export_dir.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if any(export_dir.iterdir()):
            for path in export_dir.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(export_dir))
        else:
            for path in output_dir.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(output_dir))
    print(f"Export zip: {zip_path}")
    return zip_path


def synthesize(args: argparse.Namespace) -> None:
    require_own_voice(args)
    ensure_training_deps()
    from TTS.api import TTS

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tts = TTS(
        model_path=args.model_path,
        config_path=args.config_path,
        progress_bar=True,
        gpu=args.gpu,
    )
    tts.tts_to_file(text=args.text, file_path=str(out_path))
    print(f"Audio test tersimpan: {out_path}")


def command_train(args: argparse.Namespace) -> None:
    output_dir = train_vits(args)
    if args.export:
        export_artifacts(output_dir, Path(args.export_dir))


def command_validate(args: argparse.Namespace) -> None:
    require_own_voice(args)
    dataset_dir = resolve_dataset(Path(args.dataset), Path(args.unpack_dir))
    validate_dataset(dataset_dir)


def command_export(args: argparse.Namespace) -> None:
    export_artifacts(Path(args.output_dir), Path(args.export_dir))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kaggle trainer untuk voice model personal Mika.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    train = subparsers.add_parser("train", help="Train VITS di Kaggle.")
    train.add_argument("--dataset", required=True, help="Folder/zip dataset berisi metadata.csv dan wavs.")
    train.add_argument("--unpack-dir", default=str(WORKING_DIR / "mika_voice_dataset"))
    train.add_argument("--output-dir", default=str(WORKING_DIR / "mika_voice_training"))
    train.add_argument("--export-dir", default=str(WORKING_DIR / "mika_voice_export"))
    train.add_argument("--language", default="id")
    train.add_argument("--epochs", type=int, default=1000)
    train.add_argument("--batch-size", type=int, default=8)
    train.add_argument("--eval-split-size", type=float, default=0.08)
    train.add_argument("--eval-max-size", type=int, default=20)
    train.add_argument("--num-workers", type=int, default=2)
    train.add_argument("--restore-path", default="")
    train.add_argument("--mixed-precision", action="store_true")
    train.add_argument("--export", action="store_true")
    train.add_argument("--i-own-this-voice", action="store_true")
    train.set_defaults(func=command_train)

    validate = subparsers.add_parser("validate", help="Cek zip/folder dataset tanpa training.")
    validate.add_argument("--dataset", required=True)
    validate.add_argument("--unpack-dir", default=str(WORKING_DIR / "mika_voice_dataset_validate"))
    validate.add_argument("--i-own-this-voice", action="store_true")
    validate.set_defaults(func=command_validate)

    synth = subparsers.add_parser("synthesize", help="Tes model di Kaggle.")
    synth.add_argument("--model-path", required=True)
    synth.add_argument("--config-path", required=True)
    synth.add_argument("--text", default="Halo, aku Mika dengan suara personal.")
    synth.add_argument("--out", default=str(WORKING_DIR / "mika_voice_test.wav"))
    synth.add_argument("--gpu", action="store_true")
    synth.add_argument("--i-own-this-voice", action="store_true")
    synth.set_defaults(func=synthesize)

    export = subparsers.add_parser("export", help="Zip artifact model dari output training.")
    export.add_argument("--output-dir", default=str(WORKING_DIR / "mika_voice_training"))
    export.add_argument("--export-dir", default=str(WORKING_DIR / "mika_voice_export"))
    export.set_defaults(func=command_export)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
