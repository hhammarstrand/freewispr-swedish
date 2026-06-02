"""L5.8: BatchedInferencePipeline (opt-in) — long-clip routing + fallback."""
from __future__ import annotations

import importlib
import sys
import threading
from types import SimpleNamespace

import numpy as np


def _reload(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    return importlib.reload(importlib.import_module("transcriber"))


def test_batched_used_for_long_clip(monkeypatch):
    transcriber = _reload(monkeypatch)
    calls = {"batched": 0, "normal": 0}

    class Batched:
        def transcribe(self, audio, **kw):
            calls["batched"] += 1
            return iter([SimpleNamespace(text="lång text")]), SimpleNamespace()

    class Normal:
        def transcribe(self, audio, **kw):
            calls["normal"] += 1
            return iter([SimpleNamespace(text="x")]), SimpleNamespace()

    inst = object.__new__(transcriber.Transcriber)
    inst.language = "sv"
    inst._model_lock = threading.RLock()
    inst.model = Normal()
    inst._batched = Batched()
    # 25 s clip → routed to the batched pipeline.
    out = inst._transcribe_local(np.ones(16000 * 25, dtype=np.float32))
    assert out == "Lång text"
    assert calls["batched"] == 1 and calls["normal"] == 0


def test_batched_falls_back_on_error(monkeypatch):
    transcriber = _reload(monkeypatch)
    calls = {"normal": 0}

    class Batched:
        def transcribe(self, audio, **kw):
            raise TypeError("unsupported kwarg")

    class Normal:
        def transcribe(self, audio, **kw):
            calls["normal"] += 1
            return iter([SimpleNamespace(text="normal text")]), SimpleNamespace()

    inst = object.__new__(transcriber.Transcriber)
    inst.language = "sv"
    inst._model_lock = threading.RLock()
    inst.model = Normal()
    inst._batched = Batched()
    out = inst._transcribe_local(np.ones(16000 * 25, dtype=np.float32))
    assert out == "Normal text"
    assert calls["normal"] == 1          # graceful fallback to the normal model


def test_short_clip_skips_batched(monkeypatch):
    transcriber = _reload(monkeypatch)
    calls = {"batched": 0, "normal": 0}

    class Batched:
        def transcribe(self, audio, **kw):
            calls["batched"] += 1
            return iter([]), SimpleNamespace()

    class Normal:
        def transcribe(self, audio, **kw):
            calls["normal"] += 1
            return iter([SimpleNamespace(text="kort")]), SimpleNamespace()

    inst = object.__new__(transcriber.Transcriber)
    inst.language = "sv"
    inst._model_lock = threading.RLock()
    inst.model = Normal()
    inst._batched = Batched()
    inst._transcribe_local(np.ones(16000, dtype=np.float32))   # 1 s
    assert calls["batched"] == 0 and calls["normal"] == 1
