"""Fix #1: on-screen names reach a *remote* STT provider only with consent.

On-screen names freely bias the *local* decoder (they never leave the machine)
but are a separate data category that must not be forwarded to a remote STT
provider unless the user has explicitly accepted it.
"""
from __future__ import annotations

import importlib
import sys
import threading
from types import SimpleNamespace

import numpy as np


def _reload_dictation(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    return importlib.reload(importlib.import_module("dictation"))


def _mode(dictation, transcriber, monkeypatch, *, provider, consent):
    mode = object.__new__(dictation.DictationMode)
    mode.transcriber = transcriber
    mode._worker_stop = threading.Event()
    mode._active = True
    mode._modifier_keys = ()
    mode.hotkey = "ctrl+space"
    mode.indicator = None
    mode.on_status = lambda m: None
    mode.context_awareness = True
    mode.learning_enabled = False
    mode.command_mode_enabled = False
    mode.raw_mode = False
    mode.min_rms = 0.0
    mode._last_block = ""
    mode._last_pasted = ""
    mode._field_reader = None
    mode.context_to_remote_accepted = consent
    transcriber.transcription_provider = provider
    monkeypatch.setattr(
        dictation, "paste_text",
        lambda text, active_modifiers=(), replace_len=0: None)
    return mode


def _run(dictation, mode, names):
    import context_win
    ctx = context_win.ContextInfo(
        app="notepad", title="t", profile_key="default",
        profile_description="", polish=True, capitalize=True,
        onscreen_names=names, focused_text="", read_ms=1.0)
    holder = dictation._ContextHolder()
    holder.ctx = ctx
    holder.event.set()
    mode._ctx_result = holder
    mode._process_job(np.ones(16000, dtype=np.float32), 1, 16000, 0.5, 0.0)


def test_remote_without_consent_strips_onscreen_names(monkeypatch):
    dictation = _reload_dictation(monkeypatch)
    captured = {}
    tr = SimpleNamespace(
        transcribe=lambda a, **kw: (captured.update(kw) or "hej"),
        llm_enabled=False, last_polish_state="local")
    mode = _mode(dictation, tr, monkeypatch, provider="staik", consent=False)
    _run(dictation, mode, "Kalmar, Åsa")
    assert captured.get("extra_hotwords") == ""


def test_remote_with_consent_forwards_onscreen_names(monkeypatch):
    dictation = _reload_dictation(monkeypatch)
    captured = {}
    tr = SimpleNamespace(
        transcribe=lambda a, **kw: (captured.update(kw) or "hej"),
        llm_enabled=False, last_polish_state="local")
    mode = _mode(dictation, tr, monkeypatch, provider="staik", consent=True)
    _run(dictation, mode, "Kalmar, Åsa")
    assert captured.get("extra_hotwords") == "Kalmar, Åsa"


def test_local_provider_always_uses_onscreen_names(monkeypatch):
    dictation = _reload_dictation(monkeypatch)
    captured = {}
    tr = SimpleNamespace(
        transcribe=lambda a, **kw: (captured.update(kw) or "hej"),
        llm_enabled=False, last_polish_state="local")
    # No consent, but local STT never leaves the machine → names still used.
    mode = _mode(dictation, tr, monkeypatch, provider="local", consent=False)
    _run(dictation, mode, "Kalmar, Åsa")
    assert captured.get("extra_hotwords") == "Kalmar, Åsa"
