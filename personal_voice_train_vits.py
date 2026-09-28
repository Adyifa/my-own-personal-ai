from __future__ import annotations

import argparse
import json
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PROJECT_DIR / "commands.json"
DEFAULT_ROOT = PROJECT_DIR / "voice_models"


def require_own_voice(args: argparse.Namespace) -> None:
    if not getattr(args, "i_own_this_voice", False):
        raise SystemExit(
            "Tambahkan --i-own-this-voice untuk konfirmasi bahwa ini suara kamu sendiri "
            "dan kamu setuju dipakai untuk voice model personal."
        )


def profile_dir(name: str) -> Path:
    safe = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in name.strip())
    return DEFAULT_ROOT / (safe or "my_voice")


def ensure_training_deps() -> None:
    try:
        import TTS  # noqa: F401
        import trainer  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "Dependency training belum terpasang. Jalankan:\n"
            "python -m pip install -r requirements_personal_voice.txt\n\n"
            "Catatan: training neural voice biasanya butuh GPU NVIDIA/CUDA."
        ) from exc


def command_train(args: argparse.Namespace) -> None:
    require_own_voice(args)
    ensure_training_deps()

    from trainer import Trainer, TrainerArgs
    from TTS.config.shared_configs import BaseDatasetConfig
    from TTS.tts.configs.vits_config import VitsConfig
    from TTS.tts.datasets import load_tts_samples
    from TTS.tts.models.vits import Vits
    from TTS.tts.utils.text.tokenizer import TTSTokenizer
    from TTS.utils.audio import AudioProcessor

    root = profile_dir(args.name)
    metadata_path = root / "metadata.csv"
    if not metadata_path.exists():
        raise SystemExit(f"Dataset belum siap. Jalankan prepare dulu. Tidak ketemu: {metadata_path}")

    output_path = root / "training_runs"
    dataset = BaseDatasetConfig(
        formatter="ljspeech",
        meta_file_train="metadata.csv",
        path=str(root),
        language="id",
    )
    config = VitsConfig(
        batch_size=args.batch_size,
        eval_batch_size=max(1, min(args.batch_size, 4)),
        num_loader_workers=0,
        num_eval_loader_workers=0,
        run_eval=True,
        test_delay_epochs=-1,
        epochs=args.epochs,
        text_cleaner="basic_cleaners",
        use_phonemes=False,
        print_step=25,
        print_eval=False,
        mixed_precision=args.mixed_precision,
        output_path=str(output_path),
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
        str(output_path),
        model=model,
        train_samples=train_samples,
        eval_samples=eval_samples,
    )
    trainer.fit()


def command_synthesize(args: argparse.Namespace) -> None:
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
    print(f"Audio tersimpan: {out_path}")


def command_apply_model(args: argparse.Namespace) -> None:
    require_own_voice(args)
    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config.setdefault("voice", {})
    config["voice"].update(
        {
            "enabled": True,
            "provider": "coqui_tts",
            "coqui_model_path": str(Path(args.model_path).resolve()),
            "coqui_config_path": str(Path(args.config_path).resolve()),
            "coqui_speaker_wav": "",
            "coqui_language": "id",
            "coqui_gpu": bool(args.gpu),
        }
    )
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Config Mika diubah ke trained personal model: {config_path}")


def command_apply_xtts(args: argparse.Namespace) -> None:
    require_own_voice(args)
    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config.setdefault("voice", {})
    config["voice"].update(
        {
            "enabled": True,
            "provider": "coqui_xtts",
            "coqui_model": args.model_name,
            "coqui_model_path": "",
            "coqui_config_path": "",
            "coqui_speaker_wav": str(Path(args.speaker_wav).resolve()),
            "coqui_language": args.language,
            "coqui_gpu": bool(args.gpu),
        }
    )
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Config Mika diubah ke XTTS reference voice: {config_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Training dan integrasi voice model personal untuk Mika. Pakai hanya untuk suara kamu sendiri."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    train = subparsers.add_parser("train", help="Train VITS dari dataset personal.")
    train.add_argument("--name", required=True)
    train.add_argument("--epochs", type=int, default=1000)
    train.add_argument("--batch-size", type=int, default=8)
    train.add_argument("--eval-split-size", type=float, default=0.08)
    train.add_argument("--eval-max-size", type=int, default=20)
    train.add_argument("--restore-path", default="")
    train.add_argument("--mixed-precision", action="store_true")
    train.add_argument("--i-own-this-voice", action="store_true")
    train.set_defaults(func=command_train)

    synth = subparsers.add_parser("synthesize", help="Tes model hasil training.")
    synth.add_argument("--model-path", required=True)
    synth.add_argument("--config-path", required=True)
    synth.add_argument("--text", default="Halo, aku Mika dengan suara personal.")
    synth.add_argument("--out", default=str(PROJECT_DIR / "personal_voice_test.wav"))
    synth.add_argument("--gpu", action="store_true")
    synth.add_argument("--i-own-this-voice", action="store_true")
    synth.set_defaults(func=command_synthesize)

    apply_model = subparsers.add_parser("apply-model", help="Pakai checkpoint trained model di Mika.")
    apply_model.add_argument("--model-path", required=True)
    apply_model.add_argument("--config-path", required=True)
    apply_model.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    apply_model.add_argument("--gpu", action="store_true")
    apply_model.add_argument("--i-own-this-voice", action="store_true")
    apply_model.set_defaults(func=command_apply_model)

    apply_xtts = subparsers.add_parser("apply-xtts", help="Pakai XTTS zero-shot dengan reference WAV kamu.")
    apply_xtts.add_argument("--speaker-wav", required=True)
    apply_xtts.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    apply_xtts.add_argument("--model-name", default="tts_models/multilingual/multi-dataset/xtts_v2")
    apply_xtts.add_argument("--language", default="id")
    apply_xtts.add_argument("--gpu", action="store_true")
    apply_xtts.add_argument("--i-own-this-voice", action="store_true")
    apply_xtts.set_defaults(func=command_apply_xtts)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
