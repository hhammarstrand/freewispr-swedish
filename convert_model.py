"""Convert KBLab Whisper models to CTranslate2 format.

Usage:
    python convert_model.py medium
    python convert_model.py large
    python convert_model.py tiny base small medium large

Requires: pip install transformers ctranslate2

The converted models are saved to:
    ~/.freewispr-swedish/models/kb-whisper-{size}-ct2/

This fixes the vocabulary mismatch crash that affects some KBLab models
when loaded directly by faster_whisper / CTranslate2.
"""
import argparse
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("convert")

MODEL_DIR = Path.home() / ".freewispr-swedish" / "models"

KBLAB_MODELS = {
    "tiny": "KBLab/kb-whisper-tiny",
    "base": "KBLab/kb-whisper-base",
    "small": "KBLab/kb-whisper-small",
    "medium": "KBLab/kb-whisper-medium",
    "large": "KBLab/kb-whisper-large",
}

# Pin specific HuggingFace revisions for reproducible downloads.
# Set to a commit SHA from the model's HF page to lock to that version.
# None = use latest (current behavior).
KBLAB_REVISIONS: dict[str, str | None] = {
    "tiny": None,
    "base": None,
    "small": None,
    "medium": None,
    "large": None,
}


def convert(size: str) -> None:
    repo = KBLAB_MODELS.get(size)
    if not repo:
        log.error("Okänd modellstorlek: %s (välj: %s)", size, ", ".join(KBLAB_MODELS))
        return

    output_dir = MODEL_DIR / f"kb-whisper-{size}-ct2"
    if output_dir.exists() and (output_dir / "model.bin").exists():
        log.info("Redan konverterad: %s", output_dir)
        return

    log.info("Konverterar %s (%s) -> %s ...", size, repo, output_dir)

    try:
        from ctranslate2.converters import TransformersConverter
    except ImportError:
        log.error("Saknar ctranslate2. Kör: pip install ctranslate2")
        return

    try:
        import transformers  # noqa: F401
    except ImportError:
        log.error("Saknar transformers. Kör: pip install transformers")
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    revision = KBLAB_REVISIONS.get(size)
    converter_kwargs: dict = dict(
        copy_files=["tokenizer.json", "preprocessor_config.json"],
    )
    if revision is not None:
        converter_kwargs["revision"] = revision
        log.info("Använder pinnad revision: %s", revision)

    converter = TransformersConverter(repo, **converter_kwargs)
    converter.convert(
        output_dir=str(output_dir),
        quantization="float16",
        force=True,
    )
    log.info("Klar! Modell sparad i: %s", output_dir)


def main():
    parser = argparse.ArgumentParser(
        description="Convert KBLab Whisper models to CTranslate2 format.",
        epilog="Example: python convert_model.py medium large",
    )
    parser.add_argument(
        "sizes",
        nargs="+",
        choices=sorted(KBLAB_MODELS.keys()),
        metavar="SIZE",
        help="One or more model sizes to convert "
             f"({', '.join(sorted(KBLAB_MODELS.keys()))})",
    )
    args = parser.parse_args()

    for size in args.sizes:
        convert(size)


if __name__ == "__main__":
    main()
