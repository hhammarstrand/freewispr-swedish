"""Targeted tests for the critical-review fixes.

Covers: warmer snapshot/restart semantics, paste-worker failure visibility +
lazy start, and the audio-prep error path resetting the indicator.
"""
from __future__ import annotations

import importlib
import threading
from types import SimpleNamespace

import numpy as np


# --------------------------------------------------------------------------- #
#  Transcriber warmers (L3/L5.3)
# --------------------------------------------------------------------------- #

def _bare_transcriber(transcriber):
    inst = object.__new__(transcriber.Transcriber)
    inst._cred_lock = threading.Lock()
    inst.llm_enabled = True
    inst.llm_api_key = "key-1"
    inst.llm_model = "m1"
    inst.llm_provider = "github"
    inst.llm_base_url = ""
    inst.transcription_provider = "local"
    inst.transcription_api_key = ""
    inst.transcription_model = ""
    inst.transcription_base_url = ""
    inst._llm_warm_stop = threading.Event()
    inst._tr_warm_stop = threading.Event()
    return inst


def test_llm_warmer_uses_credential_snapshot(monkeypatch):
    """The warmer must warm with the credentials captured at start — mutating
    self.* afterwards must not leak into the (one-shot) warm call."""
    transcriber = importlib.import_module("transcriber")
    llm_polish = importlib.import_module("llm_polish")

    calls = []
    first_call = threading.Event()

    def fake_warm(key, **kw):
        calls.append((key, kw.get("provider")))
        first_call.set()

    monkeypatch.setattr(llm_polish, "warm", fake_warm)
    inst = _bare_transcriber(transcriber)
    inst._start_llm_warmer()
    assert first_call.wait(timeout=2.0), "warmer never ran"
    # Mutate live attributes — the snapshot taken at start must win.
    inst.llm_api_key = "key-2"
    inst.llm_provider = "openai"
    inst._llm_warm_stop.set()  # stop the loop
    assert calls[0] == ("key-1", "github")


def test_restart_warmers_stops_old_and_uses_new_snapshot(monkeypatch):
    transcriber = importlib.import_module("transcriber")
    llm_polish = importlib.import_module("llm_polish")

    calls = []
    call_seen = threading.Event()

    def fake_warm(key, **kw):
        calls.append(key)
        call_seen.set()

    monkeypatch.setattr(llm_polish, "warm", fake_warm)
    inst = _bare_transcriber(transcriber)
    inst._start_llm_warmer()
    assert call_seen.wait(timeout=2.0)
    old_stop = inst._llm_warm_stop

    call_seen.clear()
    inst.update_credentials(
        (True, "key-2", "m2", "github", ""),
        ("local", "", "", ""),
    )
    inst.restart_warmers()
    # The old loop's stop event must be set so it exits...
    assert old_stop.is_set()
    # ...and a fresh event installed for the new loop.
    assert inst._llm_warm_stop is not old_stop
    assert call_seen.wait(timeout=2.0), "restarted warmer never ran"
    inst._llm_warm_stop.set()
    assert "key-2" in calls


# --------------------------------------------------------------------------- #
#  Paste worker: lazy start + visible failures
# --------------------------------------------------------------------------- #

def test_paste_worker_not_started_at_import():
    paste = importlib.reload(importlib.import_module("paste"))
    assert paste._worker_started is False


def test_paste_worker_logs_failures_and_survives(monkeypatch, caplog):
    paste = importlib.reload(importlib.import_module("paste"))
    done = threading.Event()
    results = []
    # Built at runtime so it can't appear in the logged traceback's source
    # lines — the invariant-6 assertion below must only match the payload.
    secret = "hemlig" + "diktering" + "xyzzy"

    def fail_on_secret(text, replace_len=0):
        if text == secret:
            raise RuntimeError("clipboard exploded")
        results.append(text)
        done.set()

    monkeypatch.setattr(paste, "_paste_and_keep_clipboard", fail_on_secret)
    with caplog.at_level("WARNING"):
        paste._paste_and_keep_clipboard_async(secret)
        # The worker must survive the exception and process the next job.
        paste._paste_and_keep_clipboard_async("ok")
        assert done.wait(timeout=2.0), "worker died after exception"
    assert results == ["ok"]
    assert "Inklistring misslyckades" in caplog.text
    # Invariant 6: never log the dictated text itself, only metadata.
    assert secret not in caplog.text


# --------------------------------------------------------------------------- #
#  Audio-prep failure resets the indicator (no stuck "Transkriberar…")
# --------------------------------------------------------------------------- #

class _FakeIndicator:
    def __init__(self):
        self.calls = []

    def show(self, message, state="listen", level_source=None):
        self.calls.append(("show", message, state))

    def hide(self, delay_ms=800):
        self.calls.append(("hide", delay_ms))


def test_process_job_audio_prep_failure_shows_error(monkeypatch):
    dictation = importlib.reload(importlib.import_module("dictation"))

    def broken_finalize(audio_raw, channels, rate):
        raise ValueError("bad audio shape")

    monkeypatch.setattr(dictation, "finalize_audio", broken_finalize)

    mode = object.__new__(dictation.DictationMode)
    mode.min_rms = 0.0
    mode.hotkey = "ctrl+space"
    mode.learning_enabled = False
    mode.indicator = _FakeIndicator()
    statuses = []
    mode.on_status = statuses.append
    mode.transcriber = SimpleNamespace()

    # Must not raise — and must reset the indicator with a visible error.
    mode._process_job(np.ones(16000, dtype=np.float32), 1, 16000, 0.5, 0.0)

    assert ("show", "Kunde inte bearbeta ljudet", "error") in mode.indicator.calls
    assert any("Fel" in s for s in statuses)


# --------------------------------------------------------------------------- #
#  CT2 CPU-thread auto-resolution (perf)
# --------------------------------------------------------------------------- #

def test_resolve_cpu_threads_auto_floors_at_ct2_default(monkeypatch):
    transcriber = importlib.import_module("transcriber")
    # Small machine (4 logical → 2 physical): never below CT2's default of 4.
    monkeypatch.setattr(transcriber.os, "cpu_count", lambda: 4)
    assert transcriber._resolve_cpu_threads(0) == 4
    # Big machine (16 logical → 8 physical): use the physical cores.
    monkeypatch.setattr(transcriber.os, "cpu_count", lambda: 16)
    assert transcriber._resolve_cpu_threads(0) == 8
    # cpu_count unknown: sane fallback, still >= 4.
    monkeypatch.setattr(transcriber.os, "cpu_count", lambda: None)
    assert transcriber._resolve_cpu_threads(0) == 4
    # Explicit config value always wins.
    assert transcriber._resolve_cpu_threads(2) == 2
