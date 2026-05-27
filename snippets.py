"""
Snippet library — trigger words that expand to longer phrases.
Stored at ~/.freewispr-swedish/snippets.json as {"trigger": "expansion", ...}
"""
from pathlib import Path

from json_store import load_json, save_json_atomic

_FILE = Path.home() / ".freewispr-swedish" / "snippets.json"

# In-memory cache — avoids re-reading JSON on every transcription.
_cache: dict[str, str] | None = None
_cache_mtime: float = 0.0


def load() -> dict[str, str]:
    """Load snippets, using in-memory cache when file hasn't changed."""
    global _cache, _cache_mtime
    current_mt = _FILE.stat().st_mtime if _FILE.exists() else 0.0
    if _cache is not None and current_mt == _cache_mtime:
        return _cache
    if _FILE.exists():
        _cache = dict(load_json(_FILE, {}))
        _cache_mtime = current_mt
        return _cache
    _cache = {}
    _cache_mtime = current_mt
    return _cache


def save(snippets: dict[str, str]):
    global _cache, _cache_mtime
    save_json_atomic(_FILE, snippets)
    _cache = snippets
    try:
        _cache_mtime = _FILE.stat().st_mtime
    except OSError:
        _cache_mtime = 0.0


def expand(text: str) -> str:
    """
    If the full transcribed text (stripped, lowercase) exactly matches
    a snippet trigger, return the expansion. Otherwise return text unchanged.
    """
    snips = load()
    key = text.strip().lower()
    return snips.get(key, text)
