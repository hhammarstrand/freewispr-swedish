"""
Snippets / textexpansion (AP7.6) — återinför trigger→expansion.

En ledande fras (t.ex. "min signatur") expanderas till en längre text (t.ex. en
mejlfot) vid diktering. Matchningen är exakt-/normaliserad på den *ledande*
frasen, precis som kommandoläget — förutsägbart och utan fuzzy gissning.

Hålls åtskilt från:
- inlärningsloopen (`learning.py`, rättelser `fel → rätt`), och
- `personal_context.py` (fri referenstext till LLM).

Lagras i ``~/.freewispr-swedish/snippets.json`` (``{trigger: expansion}``) atomärt
via ``json_store``. Allt lokalt; ingen nätverkstrafik.
"""
from __future__ import annotations

from pathlib import Path

from json_store import JsonCache

_PATH = Path.home() / ".freewispr-swedish" / "snippets.json"
_store = JsonCache(_PATH, default={})

_PUNCT = ".,;:!?\"'()[]{}…"


def _normalize(s: str) -> str:
    return (s or "").strip().lower().strip(_PUNCT)


def load() -> dict[str, str]:
    """Return the ``{trigger: expansion}`` mapping (copy)."""
    data = _store.load()
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()
            if isinstance(k, str) and isinstance(v, str) and k.strip()}


def save(mapping: dict[str, str]) -> None:
    """Persist the snippet mapping atomically."""
    clean = {str(k).strip(): str(v) for k, v in (mapping or {}).items()
             if str(k).strip() and str(v)}
    _store.save(clean)


def add(trigger: str, expansion: str) -> None:
    data = dict(load())
    if trigger.strip() and expansion:
        data[trigger.strip()] = expansion
        save(data)


def remove(trigger: str) -> None:
    data = dict(load())
    if data.pop(trigger, None) is not None or data.pop(trigger.strip(), None) is not None:
        save(data)


def expand(text: str, snippets: dict[str, str] | None = None) -> str:
    """Expand a leading trigger phrase; return text unchanged when none matches.

    Pure function (pass ``snippets`` to avoid disk I/O in tests). Longest
    trigger wins. Exact match → expansion; leading-phrase match → expansion +
    the remaining words.
    """
    snips = snippets if snippets is not None else load()
    if not snips or not text or not text.strip():
        return text
    words = text.strip().split()
    norm_words = [_normalize(w) for w in words]
    for trigger in sorted(snips, key=len, reverse=True):
        trig_words = _normalize(trigger).split()
        n = len(trig_words)
        if n and norm_words[:n] == trig_words:
            rest = words[n:]
            expansion = snips[trigger]
            if rest:
                return f"{expansion} {' '.join(rest)}".strip()
            return expansion
    return text
