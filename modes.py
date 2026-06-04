"""
Användardefinierade lägen (KP2) — Superwhisper-stil "modes".

Konkurrenterna låter användaren definiera namngivna lägen, var och en med en egen
ton/formateringsinstruktion (och om polish/versalisering ska köras), och binda
dem till appar. Vi har redan inbyggda profiler (``context_win.PROFILES``:
casual/email/code/default) som *är* lägen i allt utom namn — ett läge är
``(beskrivning, polish, capitalize)``. Det här modulen låter användaren lägga
till egna och binda dem till appar via den befintliga ``app_profiles``-mappningen
(process → läge-/profilnyckel).

Lagras i ``~/.freewispr-swedish/modes.json`` atomärt via ``json_store``. Helt
lokalt; ingen nätverkstrafik. Ett användarläge med samma namn som ett inbyggt
skuggar det inbyggda, så användaren kan justera t.ex. "email"-tonen.

Designval: vi återanvänder ``context_win.Profile`` som resultattyp så att
polish-pipelinen (som redan läser ``description``/``polish``/``capitalize``)
inte behöver ändras alls.
"""
from __future__ import annotations

import threading
from pathlib import Path

from json_store import JsonCache

_PATH = Path.home() / ".freewispr-swedish" / "modes.json"
_store = JsonCache(_PATH, default={})
# Serialise add()/remove() read-modify-write against concurrent edits.
_lock = threading.Lock()


def _coerce(raw: dict) -> dict | None:
    """Validate one stored mode record → ``{description, polish, capitalize}``.

    Returns ``None`` for anything malformed so a corrupt file can never crash
    resolution (it just falls back to built-ins).
    """
    if not isinstance(raw, dict):
        return None
    desc = raw.get("description", "")
    if not isinstance(desc, str):
        return None
    return {
        "description": desc.strip(),
        "polish": bool(raw.get("polish", True)),
        "capitalize": bool(raw.get("capitalize", True)),
    }


def load() -> dict[str, dict]:
    """Return ``{name: {description, polish, capitalize}}`` (validated copy)."""
    data = _store.load()
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict] = {}
    for name, raw in data.items():
        if isinstance(name, str) and name.strip():
            rec = _coerce(raw)
            if rec is not None:
                out[name.strip()] = rec
    return out


def save(modes: dict[str, dict]) -> None:
    """Persist user modes atomically (malformed records dropped)."""
    clean: dict[str, dict] = {}
    for name, raw in (modes or {}).items():
        key = str(name).strip()
        rec = _coerce(raw if isinstance(raw, dict) else {})
        if key and rec is not None:
            clean[key] = rec
    _store.save(clean)


def add(name: str, description: str, polish: bool = True,
        capitalize: bool = True) -> None:
    with _lock:
        data = dict(load())
        key = (name or "").strip()
        if key:
            data[key] = {
                "description": (description or "").strip(),
                "polish": bool(polish),
                "capitalize": bool(capitalize),
            }
            save(data)


def remove(name: str) -> None:
    with _lock:
        data = dict(load())
        if data.pop(name, None) is not None or data.pop((name or "").strip(), None) is not None:
            save(data)


def all_mode_keys(user_modes: dict[str, dict] | None = None) -> list[str]:
    """Built-in profile names + user mode names (for settings dropdowns)."""
    from context_win import PROFILES
    keys = list(PROFILES.keys())
    for k in (user_modes if user_modes is not None else load()):
        if k not in keys:
            keys.append(k)
    return keys


def get_profile(key: str, user_modes: dict[str, dict] | None = None):
    """Resolve a mode/profile key to a ``context_win.Profile``.

    User modes shadow built-ins of the same name. Unknown keys fall back to the
    built-in ``default`` profile, so a stale ``app_profiles`` binding can never
    break dictation.
    """
    from context_win import PROFILES, Profile
    modes = user_modes if user_modes is not None else load()
    rec = modes.get(key) or (modes.get(key.strip()) if isinstance(key, str) else None)
    if rec is not None:
        return Profile(
            description=rec["description"],
            polish=rec["polish"],
            capitalize=rec["capitalize"],
        )
    if key in PROFILES:
        return PROFILES[key]
    return PROFILES["default"]
