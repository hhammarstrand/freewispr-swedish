"""KP3 voice-edit hotkey selection-safety (modifier-only + suppress + wait).

The voice-edit hotkey is held *while text is selected*. Two long-standing
hazards made it nearly unusable:

1. A character trigger (e.g. ``ctrl+shift+e``) was registered with
   ``suppress=False``, so the trigger character reached the focused field and
   *replaced the selection* before voice-edit could read it.
2. ``read_selection`` sent a synthetic ``Ctrl+C`` while the user's real
   modifier keys were still physically held, racing the copy.

The fix: allow a *modifier-only* hotkey (keys that never type a character),
suppress a character trigger when one is used, and wait for the held keys to
be released before issuing ``Ctrl+C``.
"""
from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace


# --------------------------------------------------------------------------- #
#  _parse_hotkey: modifier-only combos yield an empty trigger.
# --------------------------------------------------------------------------- #

def test_parse_hotkey_modifier_only_has_empty_trigger():
    dictation = importlib.import_module("dictation")
    trigger, modifiers = dictation._parse_hotkey("ctrl+alt")
    assert trigger == ""
    assert set(modifiers) == {"ctrl", "alt"}


def test_parse_hotkey_single_modifier_only():
    dictation = importlib.import_module("dictation")
    trigger, modifiers = dictation._parse_hotkey("right ctrl")
    # "right ctrl" is a modifier (right-hand Control); no character trigger.
    assert trigger == ""
    assert modifiers == ("ctrl",)


def test_parse_hotkey_keeps_char_trigger_for_chord():
    # Regression guard: a normal chorded hotkey is unaffected.
    dictation = importlib.import_module("dictation")
    trigger, modifiers = dictation._parse_hotkey("ctrl+shift+space")
    assert trigger == "space"
    assert set(modifiers) == {"ctrl", "shift"}


def test_is_modifier_only_hotkey_helper():
    dictation = importlib.import_module("dictation")
    assert dictation._is_modifier_only_hotkey("ctrl+alt") is True
    assert dictation._is_modifier_only_hotkey("right ctrl") is True
    assert dictation._is_modifier_only_hotkey("ctrl+shift+space") is False
    assert dictation._is_modifier_only_hotkey("f9") is False
    assert dictation._is_modifier_only_hotkey("") is False


# --------------------------------------------------------------------------- #
#  Registration: char trigger is suppressed; modifier-only hooks a modifier.
# --------------------------------------------------------------------------- #

class _FakeKeyboard:
    """Records on_press_key/on_release_key/hook registrations."""

    def __init__(self):
        self.presses: list[tuple[str, bool]] = []
        self.releases: list[tuple[str, bool]] = []
        self.global_hooks: list = []

    def on_press_key(self, key, cb, suppress=False):
        self.presses.append((key, suppress))
        return object()

    def on_release_key(self, key, cb, suppress=False):
        self.releases.append((key, suppress))
        return object()

    def hook(self, cb, *a, **k):
        self.global_hooks.append(cb)
        return cb

    def unhook(self, handle):
        return None

    def key_to_scan_codes(self, key):
        return {"right ctrl": (57373,), "ctrl": (29, 57373),
                "alt": (56,), "left ctrl": (29,)}.get(key, ())

    # used elsewhere in start(); harmless no-ops here
    def is_pressed(self, key):
        return False

    def add_hotkey(self, *a, **k):
        return object()


def _make_mode(monkeypatch, voice_edit_hotkey):
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    dictation = importlib.reload(importlib.import_module("dictation"))
    fake_kb = _FakeKeyboard()
    monkeypatch.setattr(dictation, "keyboard", fake_kb)

    transcriber = SimpleNamespace(
        llm_enabled=True, llm_api_key="k", llm_model="m",
        llm_provider="github", llm_base_url="")
    mode = dictation.DictationMode(
        transcriber, hotkey="ctrl+space",
        voice_edit_hotkey=voice_edit_hotkey)
    return mode, fake_kb, dictation


def test_voice_edit_char_trigger_is_suppressed(monkeypatch):
    """A character voice-edit trigger must be suppressed so it never types into
    (and replaces) the selection."""
    mode, fake_kb, _ = _make_mode(monkeypatch, "ctrl+shift+e")
    try:
        mode.start()
        # The voice-edit trigger 'e' must be registered with suppress=True.
        ve = [s for (k, s) in fake_kb.presses if k == "e"]
        assert ve, "voice-edit trigger 'e' was not registered"
        assert all(ve), "voice-edit char trigger must be suppressed"
        # The dictation trigger (space) stays un-suppressed.
        assert ("space", False) in fake_kb.presses
    finally:
        mode.stop()


def test_voice_edit_modifier_only_installs_global_hook(monkeypatch):
    """A modifier-only hotkey is driven by a global keyboard hook (on_press_key
    is unreliable for modifier scan codes), not a per-key suppressed hook."""
    mode, fake_kb, _ = _make_mode(monkeypatch, "right ctrl")
    try:
        mode.start()
        # A global hook must be installed; no on_press_key for the modifier.
        assert len(fake_kb.global_hooks) == 1
        assert mode._voice_edit_required_keys == ("right ctrl",)
        # The dictation trigger (space) is still a normal per-key hook.
        assert ("space", False) in fake_kb.presses
        # No character hook registered for the modifier itself.
        assert not any(k in ("right ctrl", "ctrl") for (k, _s) in fake_kb.presses)
    finally:
        mode.stop()


def test_voice_edit_global_event_edge_triggers_press_and_release(monkeypatch):
    """The global hook starts on the required combo becoming held and stops
    when it is broken — using the current event to avoid is_pressed races."""
    mode, fake_kb, _ = _make_mode(monkeypatch, "ctrl+alt")
    mode.start()
    try:
        # Record press/release without touching real audio/UI.
        calls = []
        mode._on_voice_edit_press = lambda e: calls.append("press")
        mode._on_voice_edit_release = lambda e: calls.append("release")
        mode._voice_edit_scancodes = {"ctrl": {29, 57373}, "alt": {56}}

        held = {"ctrl": False, "alt": False}
        fake_kb.is_pressed = lambda k: held.get(k, False)

        def ev(name, scan, etype):
            held[name] = (etype == "down")
            return SimpleNamespace(name=name, scan_code=scan, event_type=etype)

        # ctrl down (alt still up) → not engaged yet.
        mode._on_voice_edit_global_event(ev("ctrl", 29, "down"))
        assert calls == []
        # alt down → both held → engage (press).
        mode._on_voice_edit_global_event(ev("alt", 56, "down"))
        assert calls == ["press"]
        # alt up → combo broken → release.
        mode._on_voice_edit_global_event(ev("alt", 56, "up"))
        assert calls == ["press", "release"]
    finally:
        mode.stop()


# --------------------------------------------------------------------------- #
#  read_selection waits for held keys to be released before Ctrl+C.
# --------------------------------------------------------------------------- #

def test_read_selection_waits_for_modifier_release(monkeypatch):
    import paste
    importlib.reload(paste)

    events: list[str] = []
    held = {"ctrl": True}

    class KB:
        def is_pressed(self, key):
            return held.get(key, False)

        def release(self, key):
            events.append(f"release:{key}")
            held[key] = False

        def send(self, combo):
            events.append(f"send:{combo}")

    monkeypatch.setattr(paste, "keyboard", KB())

    # Clipboard: the synthetic Ctrl+C is what makes the selection appear.
    clip = {"v": "prev"}

    class Clip:
        def paste(self):
            # Once Ctrl+C has been "sent", the OS would have put the selection
            # on the clipboard (overriding our sentinel).
            if any(e.startswith("send:ctrl+c") for e in events):
                return "the selection"
            return clip["v"]

        def copy(self, val):
            clip["v"] = val

    monkeypatch.setattr(paste, "pyperclip", Clip())

    # ctrl is "held" at call time; read_selection must release it and must not
    # send Ctrl+C until ctrl is no longer pressed.
    result = paste.read_selection(("ctrl",))

    assert "release:ctrl" in events
    # The release must happen before the synthetic copy.
    assert events.index("release:ctrl") < events.index("send:ctrl+c")
    assert result == "the selection"
