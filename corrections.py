"""
Personal dictionary — word corrections applied after transcription.
Stored at ~/.freewispr/corrections.json as {"wrong": "right", ...}
"""
import json
import re
from pathlib import Path

_FILE = Path.home() / ".freewispr" / "corrections.json"


def load() -> dict[str, str]:
    if _FILE.exists():
        try:
            with open(_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save(corrections: dict[str, str]):
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_FILE, "w", encoding="utf-8") as f:
        json.dump(corrections, f, indent=2, ensure_ascii=False)


def apply(text: str) -> str:
    """Replace all correction pairs (case-insensitive match, exact replacement)."""
    corr = load()
    for wrong, right in corr.items():
        text = re.sub(
            r'\b' + re.escape(wrong) + r'\b',
            right,
            text,
            flags=re.IGNORECASE,
        )
    return text
