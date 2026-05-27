"""
Snippet library — trigger words that expand to longer phrases.
Stored at ~/.freewispr-swedish/snippets.json as {"trigger": "expansion", ...}
"""
from pathlib import Path

from json_store import JsonCache

_store = JsonCache(Path.home() / ".freewispr-swedish" / "snippets.json", default={})


def load() -> dict[str, str]:
    """Load snippets, using in-memory cache when file hasn't changed."""
    return _store.load()


def save(snippets: dict[str, str]):
    _store.save(snippets)


def expand(text: str) -> str:
    """
    If the full transcribed text (stripped, lowercase) exactly matches
    a snippet trigger, return the expansion. Otherwise return text unchanged.
    """
    snips = load()
    key = text.strip().lower()
    return snips.get(key, text)
