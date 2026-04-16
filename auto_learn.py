"""
Auto-learning — track LLM corrections and promote frequent ones
to the personal corrections dictionary.

How it works:
  1. Each time the LLM changes a word, record_correction() is called
     with the before/after text.
  2. Word-level diffs are extracted (single word changes only — safe).
  3. Each diff is tallied in a frequency file (~/.freewispr-swedish/learned.json).
  4. When a correction reaches PROMOTE_THRESHOLD occurrences, it is
     automatically added to corrections.json AND as a hotword.
  5. This means Whisper itself gets better (hotword) AND the local
     post-processing catches the error (correction) — without needing
     the LLM next time.

The learned.json format:
  {
    "motte": {"correct": "möte", "count": 5, "promoted": true},
    "pratchar": {"correct": "Prakhar", "count": 2, "promoted": false},
    ...
  }
"""
import json
import logging
from pathlib import Path

import corrections as corr_module

log = logging.getLogger("freewispr")

LEARNED_FILE = Path.home() / ".freewispr-swedish" / "learned.json"

# How many times the same correction must occur before auto-promoting
PROMOTE_THRESHOLD = 3


def _load_learned() -> dict:
    """Load the learned corrections tally."""
    if LEARNED_FILE.exists():
        try:
            with open(LEARNED_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.debug("Kunde inte ladda learned.json: %s", e)
    return {}


def _save_learned(data: dict) -> None:
    """Save the learned corrections tally."""
    LEARNED_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(LEARNED_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log.warning("Kunde inte spara learned.json: %s", e)


def _extract_word_diffs(before: str, after: str) -> list[tuple[str, str]]:
    """Extract single-word replacements between before and after text.

    Only returns diffs where exactly one word changed in a position —
    this avoids learning phrase-level rewrites which are less reliable.

    Returns list of (wrong_word, correct_word) tuples.
    """
    before_words = before.split()
    after_words = after.split()

    # Only handle same-length sequences (word-for-word replacement)
    if len(before_words) != len(after_words):
        return []

    diffs = []
    for bw, aw in zip(before_words, after_words):
        # Strip punctuation for comparison but keep original for the mapping
        bw_clean = bw.strip(".,;:!?\"'()[]")
        aw_clean = aw.strip(".,;:!?\"'()[]")

        if bw_clean.lower() != aw_clean.lower() and bw_clean and aw_clean:
            # Only learn single-word changes, not very short words (risk of noise)
            if len(bw_clean) >= 2 and len(aw_clean) >= 2:
                diffs.append((bw_clean.lower(), aw_clean))

    return diffs


def record_correction(before: str, after: str) -> None:
    """Record a LLM correction and auto-promote if threshold reached.

    Called by transcriber.py each time the LLM changes the text.
    """
    diffs = _extract_word_diffs(before, after)
    if not diffs:
        return

    learned = _load_learned()
    promoted_any = False

    for wrong, correct in diffs:
        entry = learned.get(wrong)
        if entry and entry.get("promoted"):
            # Already promoted — skip
            continue

        if entry:
            entry["count"] = entry.get("count", 0) + 1
            # Update correct form (use latest — LLM may improve capitalization)
            entry["correct"] = correct
        else:
            entry = {"correct": correct, "count": 1, "promoted": False}
            learned[wrong] = entry

        log.info("Auto-lärning: '%s' -> '%s' (antal: %d/%d)",
                 wrong, correct, entry["count"], PROMOTE_THRESHOLD)

        # Promote if threshold reached
        if entry["count"] >= PROMOTE_THRESHOLD and not entry["promoted"]:
            _promote(wrong, correct)
            entry["promoted"] = True
            promoted_any = True

    _save_learned(learned)

    if promoted_any:
        log.info("Auto-lärning befordrade nya korrigeringar till ordlistan")


def _promote(wrong: str, correct: str) -> None:
    """Add a learned correction to the personal dictionary.

    This has two effects:
      1. corrections.json — future Whisper output is corrected locally
      2. hotwords — the correct word becomes a hotword for Whisper's decoder
         (via _load_hotwords() in transcriber.py which reads corrections)
    """
    corrs = corr_module.load()
    if wrong not in corrs:
        corrs[wrong] = correct
        corr_module.save(corrs)
        log.info("Befordrad till ordlistan: '%s' -> '%s'", wrong, correct)
    else:
        log.debug("Redan i ordlistan: '%s' -> '%s'", wrong, corrs[wrong])


def get_stats() -> dict:
    """Return learning statistics for UI display."""
    learned = _load_learned()
    total = len(learned)
    promoted = sum(1 for e in learned.values() if e.get("promoted"))
    pending = total - promoted
    return {
        "total": total,
        "promoted": promoted,
        "pending": pending,
        "entries": learned,
    }
