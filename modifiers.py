"""Canonical modifier-key naming used across dictation and paste layers.

The ``keyboard`` library accepts many aliases for the same physical key
(``win``/``windows``/``cmd``/``super`` all refer to the Windows key).
Different parts of the app historically used different alias sets, which
created a latent bug: a hotkey using ``cmd`` would parse correctly in
``dictation.py`` but ``paste.py`` would never release it after Ctrl+V,
leaving the Win key stuck and potentially opening the Start menu.

This module centralises the alias mapping so both layers agree.
"""

# Canonical names the rest of the app uses internally.
CANONICAL_MODIFIERS = ("ctrl", "shift", "alt", "windows")

# Map from alias -> canonical name. Lower-case input only.
_ALIASES = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "altgr": "alt",
    "win": "windows",
    "windows": "windows",
    "cmd": "windows",
    "command": "windows",
    "super": "windows",
    "meta": "windows",
}


def normalize(name: str) -> str | None:
    """Return canonical modifier name, or ``None`` if not a known modifier."""
    if not name:
        return None
    return _ALIASES.get(name.strip().lower())


def is_modifier(name: str) -> bool:
    """True if ``name`` (any alias) refers to a modifier key."""
    return normalize(name) is not None


def normalize_all(names) -> tuple[str, ...]:
    """Normalise an iterable of names, dropping unknowns; preserve order, dedupe."""
    out: list[str] = []
    seen: set[str] = set()
    for n in names:
        c = normalize(n)
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return tuple(out)
