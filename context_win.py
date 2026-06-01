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
import threading
import time
from typing import NamedTuple

log = logging.getLogger("freewispr")

# Hard cap on a single UIA read (L1). Electron/Chromium apps can make
# GetValuePattern() take 100-500 ms or hang; we never block the hot path
# longer than this and fall back to empty context.
UIA_TIMEOUT_S = 0.15
_uia_inited = False


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
    # L0/L1: the raw focused-field text (reused by the AP2 learning loop so it
    # doesn't issue a second UIA read) and the measured UIA read time.
    focused_text: str = ""
    read_ms: float = 0.0


def _ensure_uia_timeout() -> None:
    """Lower uiautomation's global search timeout once (best-effort)."""
    global _uia_inited
    if _uia_inited:
        return
    _uia_inited = True
    try:
        import uiautomation as auto
        auto.SetGlobalSearchTimeout(UIA_TIMEOUT_S + 0.05)
    except Exception:
        pass


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


def _focused_text_with_timeout(timeout: float = UIA_TIMEOUT_S) -> str:
    """Run get_focused_text on a daemon thread, give up after ``timeout`` (L1)."""
    result = {"text": ""}

    def _run():
        result["text"] = get_focused_text()

    t = threading.Thread(target=_run, daemon=True, name="uia-read")
    t.start()
    t.join(timeout)
    if t.is_alive():
        log.debug("UIA-läsning överskred %.0f ms — tom kontext", timeout * 1000)
        return ""
    return result["text"]


def get_focused_text() -> str:
    """Return the focused UI element's value/name via UIA — best-effort, "" on fail."""
    _ensure_uia_timeout()
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
                read_text: bool = True,
                timeout: float = UIA_TIMEOUT_S) -> ContextInfo:
    """Resolve the active app, its profile, and on-screen names — best-effort.

    ``read_text=False`` skips the UIA text read (used when no names are needed,
    e.g. the profile disables polish anyway). The UIA read is hard-bounded by
    ``timeout`` (L1) and its duration is reported as ``read_ms``. The raw
    focused text is returned as ``focused_text`` so the AP2 learning loop can
    reuse this single read instead of issuing its own.
    """
    app, title = get_active_app()
    profile_key = resolve_profile_key(app, app_profiles)
    # KP2: a binding may point at a user-defined mode, not just a built-in
    # profile. modes.get_profile() resolves user modes first, then built-in
    # PROFILES, then "default" — so existing built-in keys behave identically.
    # Lazy import keeps context_win free of a load-time dependency on modes.
    try:
        from modes import get_profile as _get_profile
        profile = _get_profile(profile_key)
    except Exception:
        profile = PROFILES.get(profile_key, PROFILES["default"])

    focused = ""
    read_ms = 0.0
    names = ""
    if read_text:
        t0 = time.monotonic()
        focused = _focused_text_with_timeout(timeout)
        read_ms = (time.monotonic() - t0) * 1000
        names = extract_names(" ".join(x for x in (title, focused) if x))

    return ContextInfo(
        app=app, title=title, profile_key=profile_key,
        profile_description=profile.description,
        polish=profile.polish, capitalize=profile.capitalize,
        onscreen_names=names, focused_text=focused, read_ms=read_ms,
    )
