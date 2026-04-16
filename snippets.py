"""
Snippet library — trigger words that expand to longer phrases.
Stored at ~/.freewispr-swedish/snippets.json as {"trigger": "expansion", ...}
"""
import json
from pathlib import Path

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
        try:
            with open(_FILE, encoding="utf-8") as f:
                _cache = json.load(f)
                _cache_mtime = current_mt
                return _cache
        except Exception:
            pass
    _cache = {}
    _cache_mtime = current_mt
    return _cache


def save(snippets: dict[str, str]):
    global _cache, _cache_mtime
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_FILE, "w", encoding="utf-8") as f:
        json.dump(snippets, f, indent=2, ensure_ascii=False)
    _cache = snippets
    _cache_mtime = _FILE.stat().st_mtime


def expand(text: str) -> str:
    """
    If the full transcribed text (stripped, lowercase) exactly matches
    a snippet trigger, return the expansion. Otherwise return text unchanged.
    """
    snips = load()
    key = text.strip().lower()
    return snips.get(key, text)
