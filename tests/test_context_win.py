"""AP3: context awareness — profiles, name extraction, best-effort safety."""
from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def cw():
    return importlib.reload(importlib.import_module("context_win"))


# --------------------------------------------------------------------------- #
#  profile resolution
# --------------------------------------------------------------------------- #

def test_resolve_profile_key_builtin_apps(cw):
    assert cw.resolve_profile_key("teams") == "casual"
    assert cw.resolve_profile_key("outlook") == "email"
    assert cw.resolve_profile_key("powershell") == "code"
    assert cw.resolve_profile_key("notepad") == "default"


def test_resolve_profile_key_substring_and_override(cw):
    # Substring match (e.g. "ms-teams" contains "teams").
    assert cw.resolve_profile_key("ms-teams-work") == "casual"
    # User override wins / extends the defaults.
    assert cw.resolve_profile_key("myeditor", {"myeditor": "code"}) == "code"


def test_code_profile_disables_polish_and_caps(cw):
    p = cw.PROFILES["code"]
    assert p.polish is False
    assert p.capitalize is False
    assert cw.PROFILES["email"].polish is True


# --------------------------------------------------------------------------- #
#  name extraction
# --------------------------------------------------------------------------- #

def test_extract_names_collects_unique_proper_nouns(cw):
    names = cw.extract_names("Hej Johan, vi ses i Kalmar med Åsa och Johan igen")
    parts = [n.strip() for n in names.split(",")]
    assert "Johan" in parts
    assert "Kalmar" in parts
    assert "Åsa" in parts
    assert parts.count("Johan") == 1


def test_extract_names_empty(cw):
    assert cw.extract_names("") == ""
    assert cw.extract_names("inga versaler här alls") == ""


# --------------------------------------------------------------------------- #
#  get_context wiring + best-effort failure handling
# --------------------------------------------------------------------------- #

def test_get_context_resolves_profile_and_names(cw, monkeypatch):
    monkeypatch.setattr(cw, "get_active_app", lambda: ("outlook", "Till: Johan"))
    monkeypatch.setattr(cw, "get_focused_text", lambda: "Hej Kalmar")
    ctx = cw.get_context()
    assert ctx.app == "outlook"
    assert ctx.profile_key == "email"
    assert ctx.profile_description == "formell e-post"
    assert "Johan" in ctx.onscreen_names
    assert "Kalmar" in ctx.onscreen_names


def test_get_active_app_never_raises_without_win32(cw, monkeypatch):
    # Simulate the native modules being absent.
    monkeypatch.setitem(sys.modules, "win32gui", None)
    assert cw.get_active_app() == ("", "")


def test_get_focused_text_handles_value_pattern(cw, monkeypatch):
    fake_ctrl = SimpleNamespace(
        GetValuePattern=lambda: SimpleNamespace(Value="fältets text"),
        Name="namn",
    )
    fake_auto = SimpleNamespace(GetFocusedControl=lambda: fake_ctrl)
    monkeypatch.setitem(sys.modules, "uiautomation", fake_auto)
    assert cw.get_focused_text() == "fältets text"


def test_get_focused_text_returns_empty_on_failure(cw, monkeypatch):
    def boom():
        raise RuntimeError("UIA down")
    fake_auto = SimpleNamespace(GetFocusedControl=boom)
    monkeypatch.setitem(sys.modules, "uiautomation", fake_auto)
    assert cw.get_focused_text() == ""


# --------------------------------------------------------------------------- #
#  dictation integration: code profile disables polish + capitalisation
# --------------------------------------------------------------------------- #

def test_dictation_code_profile_skips_polish_and_caps(monkeypatch):
    import threading

    import numpy as np
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    dictation = importlib.reload(importlib.import_module("dictation"))

    pasted = []
    polish_called = []
    tx_kwargs = {}

    mode = object.__new__(dictation.DictationMode)
    mode.transcriber = SimpleNamespace(
        transcribe=lambda audio, **kw: (tx_kwargs.update(kw) or "git checkout"),
        polish_async=lambda *a, **k: polish_called.append(1),
        last_polish_state="local",
        llm_enabled=True,
    )
    mode._worker_stop = threading.Event()
    mode._active = True
    mode._modifier_keys = ()
    mode.hotkey = "ctrl+space"
    mode.indicator = None
    mode.on_status = lambda msg: None
    mode.raw_mode = False
    mode.context_awareness = True
    mode._resolve_context = lambda: SimpleNamespace(
        profile_description="kod/terminal", onscreen_names="",
        capitalize=False, polish=False)
    monkeypatch.setattr(dictation, "paste_text",
                        lambda text, active_modifiers=(): pasted.append(text))

    mode._transcribe(np.ones(16000, dtype=np.float32))

    assert pasted == ["git checkout"]
    assert polish_called == []          # code profile disabled polish
    assert tx_kwargs.get("capitalize") is False
