"""L1: UIA off the critical path — snapshot reuse, single read, bounded wait."""
from __future__ import annotations

import importlib
import sys
import threading
import time
from types import SimpleNamespace

import numpy as np


def _reload_dictation(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    return importlib.reload(importlib.import_module("dictation"))


def _base_mode(dictation, transcriber, monkeypatch, pasted):
    mode = object.__new__(dictation.DictationMode)
    mode.transcriber = transcriber
    mode._worker_stop = threading.Event()
    mode._active = True
    mode._modifier_keys = ()
    mode.hotkey = "ctrl+space"
    mode.indicator = None
    mode.on_status = lambda m: None
    mode.context_awareness = True
    mode.learning_enabled = True
    mode.command_mode_enabled = False
    mode.raw_mode = False
    mode.min_rms = 0.0
    mode._last_block = ""
    mode._field_reader = None
    monkeypatch.setattr(
        dictation, "paste_text",
        lambda text, active_modifiers=(), replace_len=0: pasted.append(text))
    return mode


def test_l1_consumes_snapshot_without_sync_uia_read(monkeypatch):
    dictation = _reload_dictation(monkeypatch)
    import context_win

    # Any *synchronous* UIA read on the worker must blow up the test.
    def boom():
        raise AssertionError("synchronous UIA read on the critical path")
    monkeypatch.setattr(context_win, "get_focused_text", boom)

    learned = {}
    monkeypatch.setitem(
        sys.modules, "learning",
        SimpleNamespace(learn_from_observation=lambda last, obs: learned.update(
            last=last, obs=obs)))

    pasted = []
    tr = SimpleNamespace(transcribe=lambda a, **kw: "hej",
                         llm_enabled=False, last_polish_state="local")
    mode = _base_mode(dictation, tr, monkeypatch, pasted)
    mode._last_pasted = "hej kammar"

    ctx = context_win.ContextInfo(
        app="notepad", title="t", profile_key="default",
        profile_description="", polish=True, capitalize=True,
        onscreen_names="Kalmar", focused_text="hej Kalmar", read_ms=5.0)
    holder = dictation._ContextHolder()
    holder.ctx = ctx
    holder.event.set()
    mode._ctx_result = holder

    mode._process_job(np.ones(16000, dtype=np.float32), 1, 16000, 0.5, 0.0)

    assert pasted == ["hej"]              # transcription pasted
    # Learning consumed the snapshot's focused_text (no extra UIA read).
    assert learned == {"last": "hej kammar", "obs": "hej Kalmar"}


def test_l1_bounded_wait_on_hung_context(monkeypatch):
    dictation = _reload_dictation(monkeypatch)
    monkeypatch.setattr(dictation, "_CTX_JOIN_TIMEOUT", 0.05)

    pasted = []
    captured = {}
    tr = SimpleNamespace(
        transcribe=lambda a, **kw: (captured.update(kw) or "hej"),
        llm_enabled=False, last_polish_state="local")
    mode = _base_mode(dictation, tr, monkeypatch, pasted)
    mode._last_pasted = ""

    # A holder whose resolution never completes (event never set, ctx None).
    holder = dictation._ContextHolder()
    mode._ctx_result = holder

    t0 = time.monotonic()
    mode._process_job(np.ones(16000, dtype=np.float32), 1, 16000, 0.5, 0.0)
    elapsed = time.monotonic() - t0

    assert pasted == ["hej"]              # dictation proceeded with empty context
    assert elapsed < 1.0                  # bounded by _CTX_JOIN_TIMEOUT, not hung
    assert captured.get("capitalize") is True
    assert captured.get("extra_hotwords") == ""
