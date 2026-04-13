"""
Snippet library — trigger words that expand to longer phrases.
Stored at ~/.freewispr-swedish/snippets.json as {"trigger": "expansion", ...}
"""
import json
from pathlib import Path

_FILE = Path.home() / ".freewispr-swedish" / "snippets.json"


def load() -> dict[str, str]:
    if _FILE.exists():
        try:
            with open(_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save(snippets: dict[str, str]):
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_FILE, "w", encoding="utf-8") as f:
        json.dump(snippets, f, indent=2, ensure_ascii=False)


def expand(text: str) -> str:
    """
    If the full transcribed text (stripped, lowercase) exactly matches
    a snippet trigger, return the expansion. Otherwise return text unchanged.
    """
    snips = load()
    key = text.strip().lower()
    return snips.get(key, text)
