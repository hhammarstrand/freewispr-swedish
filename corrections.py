"""
Personal dictionary — word corrections applied after transcription.
Stored at ~/.freewispr-swedish/corrections.json as {"wrong": "right", ...}
"""
import json
import re
from pathlib import Path

_FILE = Path.home() / ".freewispr-swedish" / "corrections.json"

# In-memory cache — avoids re-reading JSON on every transcription.
_cache: dict[str, str] | None = None
_cache_mtime: float = 0.0


def load() -> dict[str, str]:
    """Load corrections, using in-memory cache when file hasn't changed."""
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


def save(corrections: dict[str, str]):
    global _cache, _cache_mtime
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_FILE, "w", encoding="utf-8") as f:
        json.dump(corrections, f, indent=2, ensure_ascii=False)
    # Invalidate cache so next load() picks up the new data
    _cache = corrections
    _cache_mtime = _FILE.stat().st_mtime


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
