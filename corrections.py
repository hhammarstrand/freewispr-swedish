"""
Personal dictionary — word corrections applied after transcription.
Stored at ~/.freewispr-swedish/corrections.json as {"wrong": "right", ...}
"""
import re
from pathlib import Path

from json_store import JsonCache

_store = JsonCache(Path.home() / ".freewispr-swedish" / "corrections.json", default={})


def mtime() -> float:
    """Return mtime of the corrections file (0.0 if missing).

    Exposed so callers (e.g. hotwords cache in transcriber) can detect
    changes without poking the private `_store` instance.
    """
    return _store.mtime()


def load() -> dict[str, str]:
    """Load corrections, using in-memory cache when file hasn't changed."""
    return _store.load()


def save(corrections: dict[str, str]):
    _store.save(corrections)


# Compiled-pattern cache for apply(). A *single* alternation regex with a
# dispatch dict — one linear scan over the text replaces all corrections,
# instead of N sequential substring scans (one per pair). For dictionaries
# with 50+ entries this is the difference between O(N*M) and O(M) per call.
_apply_master: re.Pattern[str] | None = None
_apply_lookup: dict[str, str] = {}
_apply_cache_mtime: float = -1.0


def _build_apply_cache(corr: dict[str, str]) -> tuple[re.Pattern[str] | None, dict[str, str]]:
    if not corr:
        return None, {}
    # Sort longest first so multi-word keys match before their prefixes.
    keys = sorted(corr.keys(), key=len, reverse=True)
    alternation = "|".join(re.escape(k) for k in keys)
    pattern = re.compile(r"\b(?:" + alternation + r")\b", re.IGNORECASE | re.UNICODE)
    lookup = {k.lower(): v for k, v in corr.items()}
    return pattern, lookup


def apply(text: str) -> str:
    """Replace all correction pairs (case-insensitive match, exact replacement)."""
    global _apply_master, _apply_lookup, _apply_cache_mtime
    corr = load()
    current_mt = _store.mtime()
    if current_mt != _apply_cache_mtime:
        _apply_master, _apply_lookup = _build_apply_cache(corr)
        _apply_cache_mtime = current_mt
    if _apply_master is None:
        return text
    return _apply_master.sub(lambda m: _apply_lookup[m.group(0).lower()], text)
