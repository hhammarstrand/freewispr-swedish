"""Download KBLab Whisper models for freewispr-swedish.

Usage:
    python convert_model.py small
    python convert_model.py tiny base small medium large

Downloads only the files faster-whisper actually needs:
- model.bin (CTranslate2 weights — KBLab publishes pre-converted)
- config.json, tokenizer.json, vocabulary.json, preprocessor_config.json

This avoids the heavy ctranslate2 + transformers conversion step that the
older version of this script required, which kept dependencies small enough
to fit in the bundled PyInstaller exe.

Models are saved to:
    ~/.freewispr-swedish/models/kb-whisper-{size}-ct2/
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

# Pin specific HuggingFace revisions for reproducible & integrity-checkable
# downloads. The KBLab repos are public and unsigned, so the best we can do
# without shipping a CA-bundle is to lock to a known commit SHA. If KBLab
# rotates a model we'll bump these manually after reviewing the diff.
#
# Last verified: 2026-05-28 against https://huggingface.co/KBLab/kb-whisper-*
# To refresh:
#   curl -s https://huggingface.co/api/models/KBLab/kb-whisper-<size> | jq .sha
KBLAB_REVISIONS: dict[str, str | None] = {
    "tiny":   "76d796af43a50fa34321efa562c9b9887a187463",
    "base":   "1499d2d2f0c7ed545bd6f2eec85287cf8d8c8b38",
    "small":  "3564d61a42fc210ceaa55a22a96dd64478959c78",
    "medium": "0abe10b9d7f75d0902656e5c06c5c4d549604dc5",
    "large":  "d5d5984b4d8f7c4847a8ea203f1976285fb28300",
}

# Files we actually need to run inference. KBLab publishes pre-converted
# ct2 model.bin alongside the safetensors/onnx files; we only fetch what
# faster-whisper expects.
_REQUIRED_FILES = [
    "model.bin",
    "config.json",
    "tokenizer.json",
    "vocabulary.json",
    "preprocessor_config.json",
]


def convert(size: str) -> None:
    """Download the model files for *size* into MODEL_DIR/kb-whisper-{size}-ct2/."""
    repo = KBLAB_MODELS.get(size)
    if not repo:
        log.error("Okänd modellstorlek: %s (välj: %s)", size, ", ".join(KBLAB_MODELS))
        return

    output_dir = MODEL_DIR / f"kb-whisper-{size}-ct2"
    if output_dir.exists() and (output_dir / "model.bin").exists():
        log.info("Redan nedladdad: %s", output_dir)
        return

    log.info("Laddar ned %s (%s) → %s ...", size, repo, output_dir)

    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        log.error(
            "Saknar huggingface_hub. Den ingår i faster-whisper-paketet — "
            "kör 'pip install -r requirements.txt'."
        )
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    revision = KBLAB_REVISIONS.get(size)
    if revision is not None:
        log.info("Använder pinnad revision: %s", revision)

    for filename in _REQUIRED_FILES:
        log.info("  - %s", filename)
        hf_hub_download(
            repo_id=repo,
            filename=filename,
            revision=revision,
            local_dir=str(output_dir),
        )

    log.info("Klar! Modell sparad i: %s", output_dir)


def main():
    parser = argparse.ArgumentParser(
        description="Download KBLab Whisper models for freewispr-swedish.",
        epilog="Example: python convert_model.py small",
    )
    parser.add_argument(
        "sizes",
        nargs="+",
        choices=sorted(KBLAB_MODELS.keys()),
        metavar="SIZE",
        help="One or more model sizes to download "
             f"({', '.join(sorted(KBLAB_MODELS.keys()))})",
    )
    args = parser.parse_args()

    for size in args.sizes:
        convert(size)


if __name__ == "__main__":
    main()
