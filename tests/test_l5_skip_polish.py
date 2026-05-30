"""L5.6: skip polish for trivial transcripts."""
from __future__ import annotations

import importlib
import sys
import threading
import time
from types import SimpleNamespace

import numpy as np


def _reload(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    return importlib.reload(importlib.import_module("dictation"))


def test_is_trivial_predicate(monkeypatch):
    d = _reload(monkeypatch)
    assert d._is_trivial("hej då", 6) is True
    assert d._is_trivial("tack så mycket", 6) is True
    # Too many words.
    assert d._is_trivial("ett två tre fyra fem sex sju", 6) is False
    # Disfluency / self-correction → must polish.
    assert d._is_trivial("öh hej", 6) is False
    assert d._is_trivial("klockan fem nej förresten sex", 6) is False
    assert d._is_trivial("", 6) is False


def _mode(d, monkeypatch, transcribe_text, pasted, polished):
    mode = object.__new__(d.DictationMode)
    mode.transcriber = SimpleNamespace(
        transcribe=lambda a, **kw: transcribe_text,
        llm_enabled=True, last_polish_state="local",
        polish_async=lambda *a, **k: polished.append(1))
    mode._worker_stop = threading.Event()
    mode._active = True
    mode._modifier_keys = ()
    mode.hotkey = "ctrl+space"
    mode.indicator = None
    mode.on_status = lambda m: None
    mode.context_awareness = False
    mode.command_mode_enabled = False
    mode.snippets_enabled = False
    mode.polish_skip_trivial = True
    mode.polish_skip_max_words = 6
    monkeypatch.setattr(d, "paste_text",
                        lambda text, active_modifiers=(), replace_len=0: pasted.append(text))
    return mode


def test_trivial_skips_polish_and_pastes_directly(monkeypatch):
    d = _reload(monkeypatch)
    pasted, polished = [], []
    mode = _mode(d, monkeypatch, "hej då", pasted, polished)
    mode._transcribe(np.ones(16000, dtype=np.float32))
    assert pasted == ["hej då"]
    assert polished == []                 # polish skipped


def test_nontrivial_still_polishes(monkeypatch):
    d = _reload(monkeypatch)
    pasted, polished = [], []
    mode = _mode(d, monkeypatch,
                 "klockan fem nej förresten sex", pasted, polished)
    mode._transcribe(np.ones(16000, dtype=np.float32))
    for _ in range(50):
        if polished:
            break
        time.sleep(0.01)
    assert polished == [1]                 # disfluency → polish ran
