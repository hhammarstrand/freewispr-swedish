"""L5.7: live transcription during recording (snapshot + combine)."""
from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import numpy as np


def test_recorder_snapshot_copies_buffer():
    audio = importlib.reload(importlib.import_module("audio"))
    rec = object.__new__(audio.MicRecorder)
    rec._buffer = np.arange(100, dtype=np.float32)
    rec._buffer_offset = 40
    rec._buffer_channels = 1
    rec._rate = 16000
    snap, ch, rate = rec.snapshot()
    assert snap.shape[0] == 40
    assert ch == 1 and rate == 16000
    # It's a copy — mutating the buffer doesn't change the snapshot.
    rec._buffer[:40] = 0
    assert snap[0] == 0.0 or snap[10] == 10.0  # snapshot kept old values
    assert snap[10] == 10.0


def _reload_dictation(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    return importlib.reload(importlib.import_module("dictation"))


def test_combine_live_joins_partials_with_tail(monkeypatch):
    d = _reload_dictation(monkeypatch)
    # 3 chunks; 2 already consumed live, last decoded as the tail.
    monkeypatch.setattr("flow.split_on_silence",
                        lambda audio, rate, min_rms=0.003: ["c0", "c1", "c2"])
    decoded = []
    mode = object.__new__(d.DictationMode)
    mode.min_rms = 0.003
    mode._live_thread = None
    mode._live_parts = ["Hej", "på"]
    mode._live_consumed = 2
    mode.transcriber = SimpleNamespace(
        transcribe=lambda c, **kw: (decoded.append(c) or "dig"))
    out = mode._combine_live(np.ones(48000, dtype=np.float32))
    assert out == "Hej på dig"
    # Only the unconsumed tail chunk was decoded after release.
    assert decoded == ["c2"]


def test_combine_live_short_utterance_falls_back_to_batch(monkeypatch):
    d = _reload_dictation(monkeypatch)
    # One chunk, nothing consumed live → behaves like a normal batch transcribe.
    monkeypatch.setattr("flow.split_on_silence",
                        lambda audio, rate, min_rms=0.003: ["only"])
    decoded = []
    mode = object.__new__(d.DictationMode)
    mode.min_rms = 0.003
    mode._live_thread = None
    mode._live_parts = []
    mode._live_consumed = 0
    mode.transcriber = SimpleNamespace(
        transcribe=lambda c, **kw: (decoded.append(c) or "Hela meningen"))
    out = mode._combine_live(np.ones(16000, dtype=np.float32))
    assert out == "Hela meningen"
    assert decoded == ["only"]
