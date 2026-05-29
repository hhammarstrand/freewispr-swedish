"""
Kontextmedvetenhet (AP3) — aktiv app + text nära markör.

Ger LLM-polishen och lokal transkribering bättre signal:
- vilken app som är i förgrunden → en *app-profil* (ton/format),
- egennamn nära markören → rätt stavning/versalisering.

**Best-effort:** allt här får misslyckas tyst. De native beroendena
(``win32gui``/``win32process``/``psutil``/``uiautomation``) importeras lokalt och
inom ``try`` så att modulen importeras rent även på icke-Windows och i CI.
Returnerar tomma värden i stället för att krascha.

**Integritet:** skärmtext samlas in lokalt. Namn nära markören skickas till LLM
endast via ``polish`` (som bara körs när LLM är på) — anroparen ansvarar för att
inte skicka kontext när LLM/remote är av.
"""
from __future__ import annotations

import logging
import re
from typing import NamedTuple

log = logging.getLogger("freewispr")


class Profile(NamedTuple):
    description: str   # svensk beskrivning som skickas som app-profil till polish
    polish: bool       # ska LLM-polish köras i denna app?
    capitalize: bool   # ska första bokstaven versaliseras i transkriberingen?


# Profil-definitioner. "code" stänger av polish och versalisering så att
# terminal/editor får råtext utan oönskad formatering.
PROFILES: dict[str, Profile] = {
    "casual": Profile("ledig, vardaglig ton", polish=True, capitalize=True),
    "email": Profile("formell e-post", polish=True, capitalize=True),
    "code": Profile(
        "kod/terminal: ingen versalisering, ingen extra interpunktion, "
        "behåll exakt ordalydelse",
        polish=False, capitalize=False,
    ),
    "default": Profile("", polish=True, capitalize=True),
}

# Processnamn (gemener, utan .exe) → profilnyckel. Användarens app_profiles i
# config slås ihop ovanpå dessa.
DEFAULT_APP_PROFILES: dict[str, str] = {
    "teams": "casual", "ms-teams": "casual", "slack": "casual",
    "discord": "casual",
    "outlook": "email", "hxoutlook": "email", "thunderbird": "email",
    "code": "code", "cursor": "code", "windowsterminal": "code", "wt": "code",
    "cmd": "code", "powershell": "code", "pwsh": "code", "conhost": "code",
    "alacritty": "code", "wezterm": "code",
}

# Egennamn: ord som börjar med versal (inkl. å/ä/ö), minst 2 tecken.
_NAME_RE = re.compile(r"\b[A-ZÅÄÖ][\wÅÄÖåäö'-]{1,}\b")
_MAX_NAMES = 20


class ContextInfo(NamedTuple):
    app: str
    title: str
    profile_key: str
    profile_description: str
    polish: bool
    capitalize: bool
    onscreen_names: str


def get_active_app() -> tuple[str, str]:
    """Return ``(process_name_lower_without_exe, window_title)`` — best-effort."""
    try:
        import psutil
        import win32gui
        import win32process
    except Exception:
        return "", ""
    try:
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd) or ""
        _thread, pid = win32process.GetWindowThreadProcessId(hwnd)
        name = (psutil.Process(pid).name() or "").lower()
        if name.endswith(".exe"):
            name = name[:-4]
        return name, title
    except Exception as e:
        log.debug("get_active_app misslyckades: %s", e)
        return "", ""


def get_focused_text() -> str:
    """Return the focused UI element's value/name via UIA — best-effort, "" on fail."""
    try:
        import uiautomation as auto
    except Exception:
        return ""
    try:
        ctrl = auto.GetFocusedControl()
        if ctrl is None:
            return ""
        # Prefer the editable value (text fields) over the accessible name.
        try:
            value = ctrl.GetValuePattern().Value
            if value:
                return str(value)
        except Exception:
            pass
        name = getattr(ctrl, "Name", "") or ""
        return str(name)
    except Exception as e:
        log.debug("get_focused_text misslyckades: %s", e)
        return ""


def extract_names(text: str, limit: int = _MAX_NAMES) -> str:
    """Collect unique capitalized tokens (proper nouns) as a comma list."""
    if not text:
        return ""
    seen: list[str] = []
    for cand in _NAME_RE.findall(text):
        if cand not in seen:
            seen.append(cand)
        if len(seen) >= limit:
            break
    return ", ".join(seen)


def resolve_profile_key(app: str, app_profiles: dict[str, str] | None = None) -> str:
    """Map a process name to a profile key (exact, then substring, else default)."""
    mapping = dict(DEFAULT_APP_PROFILES)
    if app_profiles:
        mapping.update({str(k).lower(): str(v) for k, v in app_profiles.items()})
    if not app:
        return "default"
    if app in mapping:
        return mapping[app]
    for name, key in mapping.items():
        if name and name in app:
            return key
    return "default"


def get_context(app_profiles: dict[str, str] | None = None,
                read_text: bool = True) -> ContextInfo:
    """Resolve the active app, its profile, and on-screen names — best-effort.

    ``read_text=False`` skips the UIA text read (used when no names are needed,
    e.g. the profile disables polish anyway).
    """
    app, title = get_active_app()
    profile_key = resolve_profile_key(app, app_profiles)
    profile = PROFILES.get(profile_key, PROFILES["default"])

    names = ""
    if read_text:
        focused = get_focused_text()
        names = extract_names(" ".join(x for x in (title, focused) if x))

    return ContextInfo(
        app=app, title=title, profile_key=profile_key,
        profile_description=profile.description,
        polish=profile.polish, capitalize=profile.capitalize,
        onscreen_names=names,
    )
