"""
One-shot migration: snippets.json + corrections.json -> personal_context.json.

Runs at app start. Idempotent — once personal_context.json exists, the
migration is a no-op forever. Original snippets.json / corrections.json
are left untouched on disk so the user has a safety net.

Builds a human-editable Swedish text that lists the previous data in
the same format we encourage users to write in:

    Vanliga fraser jag dikterar:
    - "mvb" betyder "Med vänliga hälsningar"
    - "vh" betyder "Vänliga hälsningar"

    Korrekt stavning av ord jag ofta säger:
    - kammar -> Kalmar
    - tjabbis -> Joakim

Empty/missing source files produce no migration (no file is written) so
fresh installs don't end up with a context file containing only headers.
"""
from __future__ import annotations

import logging
from pathlib import Path

from json_store import load_json
import personal_context

log = logging.getLogger("freewispr")

_DIR = Path.home() / ".freewispr-swedish"
_SNIPPETS_PATH = _DIR / "snippets.json"
_CORRECTIONS_PATH = _DIR / "corrections.json"


def _load_pairs(path: Path) -> dict[str, str]:
    """Read a {key: value} JSON file, returning {} on missing or malformed."""
    if not path.exists():
        return {}
    data = load_json(path, default={})
    if not isinstance(data, dict):
        return {}
    # Filter out non-string entries defensively — the old files were free-form.
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str) and k}


def _format_snippets(snippets: dict[str, str]) -> str:
    if not snippets:
        return ""
    lines = ["Vanliga fraser jag dikterar:"]
    for trigger, expansion in sorted(snippets.items()):
        lines.append(f'- "{trigger}" betyder "{expansion}"')
    return "\n".join(lines)


def _format_corrections(corrections: dict[str, str]) -> str:
    if not corrections:
        return ""
    lines = ["Korrekt stavning av ord jag ofta säger:"]
    for wrong, right in sorted(corrections.items()):
        lines.append(f"- {wrong} -> {right}")
    return "\n".join(lines)


def build_context_text(snippets: dict[str, str],
                       corrections: dict[str, str]) -> str:
    """Compose the kontext text from raw snippets + corrections dicts."""
    blocks = [b for b in (_format_snippets(snippets),
                          _format_corrections(corrections)) if b]
    return "\n\n".join(blocks)


def migrate_if_needed() -> bool:
    """Run the migration once. Returns True if a file was written.

    No-op when personal_context.json already exists (user has either run
    the migration before or has manually authored a context). Also a
    no-op when neither snippets.json nor corrections.json has any data
    — we don't want a fresh install to end up with a non-empty default.
    """
    if personal_context._PATH.exists():
        return False
    snippets = _load_pairs(_SNIPPETS_PATH)
    corrections = _load_pairs(_CORRECTIONS_PATH)
    text = build_context_text(snippets, corrections)
    if not text:
        return False
    try:
        personal_context.save(text)
        log.info("Migrerade %d snippet(ar) och %d ordlistepost(er) "
                 "till personal_context.json",
                 len(snippets), len(corrections))
        return True
    except Exception as e:
        log.warning("Kunde inte migrera till personal_context.json: %s", e)
        return False
