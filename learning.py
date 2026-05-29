"""
Inlärningsloop (AP2) — dynamisk auto-ordlista + rättelser.

När användaren rättar inklistrad text (t.ex. byter ``kammar`` mot ``Kalmar`` i
Anteckningar) lär sig systemet term-paret till nästa gång:

- ``~/.freewispr-swedish/corrections.json`` — strukturerade ``fel → rätt``-par,
  injiceras i LLM-polishens referensblock (fungerar för alla backends).
- ``~/.freewispr-swedish/hotwords.txt`` — de *rätta* termerna, biasar lokal
  faster-whisper (fungerar även med LLM av).

Detta ersätter INTE den fria ``personal_context`` — det är en separat, dynamisk
loop bredvid den (de gamla snippets/corrections/auto_learn-modulerna återinförs
inte).

All lagring är lokal och atomär via ``json_store``. Ingen PII loggas — endast
antal inlärda par.
"""
from __future__ import annotations

import logging
import threading
from difflib import SequenceMatcher
from pathlib import Path

from json_store import JsonCache, save_json_atomic

log = logging.getLogger("freewispr")

CONFIG_DIR = Path.home() / ".freewispr-swedish"
CORRECTIONS_PATH = CONFIG_DIR / "corrections.json"
HOTWORDS_PATH = CONFIG_DIR / "hotwords.txt"

# Keep the dictionary bounded so a noisy session can't grow it without limit.
MAX_CORRECTIONS = 500
# Minimum string similarity (0-1) between the wrong and right word for a swap to
# count as a *correction* rather than the user rewriting to a different word.
# "kammar"→"kalmar" ≈ 0.83, "johan"→"johan" (case fix) = 1.0; unrelated swaps
# like "bra"→"dålig" fall well below this and are ignored.
SIMILARITY_THRESHOLD = 0.6
# Ignore observations where more than this many single-word swaps happened — a
# wholesale rewrite is not a dictation correction we should learn from.
MAX_PAIRS_PER_OBSERVATION = 5
# Skip absurdly long fields (likely a whole document, not our dictation).
MAX_TOKENS = 400

_PUNCT = ".,;:!?\"'()[]{}…-–—"

_store = JsonCache(CORRECTIONS_PATH, default={})
_lock = threading.Lock()


def _clean(token: str) -> str:
    """Strip surrounding punctuation from a whitespace token."""
    return token.strip(_PUNCT)


def _is_wordlike(s: str) -> bool:
    return bool(s) and len(s) <= 40 and any(c.isalpha() for c in s)


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def diff_pairs(pasted: str, observed: str) -> list[tuple[str, str]]:
    """Return learned ``(wrong, right)`` pairs from a paste→edit observation.

    Aligns the two token streams and keeps isolated single-word substitutions
    where the words are similar enough to be a correction (not a rewrite).
    Pure function — no disk I/O — so it is trivially testable.
    """
    p = (pasted or "").strip()
    o = (observed or "").strip()
    if not p or not o or p == o:
        return []

    p_tokens = p.split()
    o_tokens = o.split()
    if len(p_tokens) > MAX_TOKENS or len(o_tokens) > MAX_TOKENS:
        return []

    matcher = SequenceMatcher(None, p_tokens, o_tokens, autojunk=False)
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace":
            continue
        # Only learn from clean one-for-one swaps.
        if (i2 - i1) != 1 or (j2 - j1) != 1:
            continue
        wrong = _clean(p_tokens[i1])
        right = _clean(o_tokens[j1])
        if not _is_wordlike(wrong) or not _is_wordlike(right):
            continue
        if wrong == right:
            continue
        if _similar(wrong, right) < SIMILARITY_THRESHOLD:
            continue
        if wrong in seen:
            continue
        seen.add(wrong)
        pairs.append((wrong, right))

    if len(pairs) > MAX_PAIRS_PER_OBSERVATION:
        return []
    return pairs


def load_corrections() -> dict[str, str]:
    """Return the learned ``fel → rätt`` dictionary (copy)."""
    data = _store.load()
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()
            if isinstance(k, str) and isinstance(v, str)}


def add_hotwords(words: list[str]) -> None:
    """Append unique, word-like terms to hotwords.txt (deduplicated)."""
    new = [w.strip() for w in words if _is_wordlike(w.strip())]
    if not new:
        return
    existing: set[str] = set()
    lines: list[str] = []
    if HOTWORDS_PATH.exists():
        try:
            for line in HOTWORDS_PATH.read_text(encoding="utf-8").splitlines():
                lines.append(line)
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    existing.add(stripped)
        except Exception as e:
            log.warning("Kunde inte läsa hotwords.txt: %s", e)
            return
    added = [w for w in new if w not in existing]
    if not added:
        return
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    out = lines + added
    try:
        HOTWORDS_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
        log.info("Lade till %d nya hotwords", len(added))
    except Exception as e:
        log.warning("Kunde inte skriva hotwords.txt: %s", e)


def record_corrections(pairs: list[tuple[str, str]]) -> None:
    """Persist ``(wrong, right)`` pairs to corrections.json and hotwords.txt."""
    if not pairs:
        return
    with _lock:
        data = dict(_store.load())
        for wrong, right in pairs:
            data[wrong] = right
        # Bound the dictionary: drop oldest insertion-order entries.
        if len(data) > MAX_CORRECTIONS:
            for key in list(data)[: len(data) - MAX_CORRECTIONS]:
                del data[key]
        _store.save(data)
    add_hotwords([right for _, right in pairs])


def learn_from_observation(pasted: str, observed: str) -> list[tuple[str, str]]:
    """Diff a paste→edit observation, persist any corrections, return them."""
    pairs = diff_pairs(pasted, observed)
    if pairs:
        log.info("Inlärt %d rättelse(r) från manuell redigering", len(pairs))
        record_corrections(pairs)
    return pairs


def set_corrections(mapping: dict[str, str]) -> None:
    """Overwrite the learned corrections (AP7.7 settings editor).

    Cleans empty/identity pairs. Used by the corrections UI to apply edits and
    deletions; existing terms not in *mapping* are removed.
    """
    clean = {str(k).strip(): str(v).strip()
             for k, v in (mapping or {}).items()
             if str(k).strip() and str(v).strip()}
    with _lock:
        _store.save(clean)
    log.info("Rättelser uppdaterade (%d par)", len(clean))


def clear_learned() -> None:
    """Empty the learned corrections dictionary ("rensa inlärt").

    hotwords.txt is left untouched — the user may have curated entries there by
    hand and we can't tell those apart from learned ones.
    """
    with _lock:
        save_json_atomic(CORRECTIONS_PATH, {})
        _store.save({})
    log.info("Inlärda rättelser rensade")
