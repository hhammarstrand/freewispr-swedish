"""L5.5: RMS silence-trim + VAD-fallback only on empty."""
from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import numpy as np


def _reload_dictation(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    return importlib.reload(importlib.import_module("dictation"))


def test_trim_silence_removes_edges_keeps_speech(monkeypatch):
    d = _reload_dictation(monkeypatch)
    rate = 16000
    silence = np.zeros(rate, dtype=np.float32)          # 1 s
    speech = np.ones(rate, dtype=np.float32) * 0.2      # 1 s voiced
    audio = np.concatenate([silence, speech, silence])
    out = d._trim_silence(audio, rate, 0.05)
    # Trimmed shorter than the 3 s input, but the 1 s of speech is preserved
    # (plus padding), never clipped below it.
    assert out.size < audio.size
    assert out.size >= rate


def test_trim_silence_all_speech_unchanged(monkeypatch):
    d = _reload_dictation(monkeypatch)
    audio = np.ones(16000, dtype=np.float32) * 0.2
    out = d._trim_silence(audio, 16000, 0.05)
    assert out.size == audio.size


def test_trim_silence_all_silence_unchanged(monkeypatch):
    d = _reload_dictation(monkeypatch)
    audio = np.zeros(16000, dtype=np.float32)
    out = d._trim_silence(audio, 16000, 0.05)
    assert out.size == audio.size       # nothing crosses threshold → keep input


def test_vad_fallback_only_runs_when_empty(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    transcriber = importlib.reload(importlib.import_module("transcriber"))
    calls = []

    class FakeModel:
        def __init__(self, results):
            self._results = results

        def transcribe(self, audio, **kwargs):
            calls.append(kwargs["vad_filter"])
            text = self._results[len(calls) - 1]
            seg = [SimpleNamespace(text=text)] if text else []
            return iter(seg), SimpleNamespace()

    # VAD pass returns empty → no-VAD pass recovers "hej".
    inst = object.__new__(transcriber.Transcriber)
    inst.language = "sv"
    inst._model_lock = __import__("threading").RLock()
    inst.vad_filter = True
    inst.model = FakeModel(["", "hej"])
    out = inst._transcribe_local(np.ones(16000, dtype=np.float32))
    assert out == "Hej"
    assert calls == [True, False]       # both passes ran (VAD empty → retry)


def test_vad_no_fallback_when_vad_nonempty(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    transcriber = importlib.reload(importlib.import_module("transcriber"))
    calls = []

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            calls.append(kwargs["vad_filter"])
            return iter([SimpleNamespace(text="hej")]), SimpleNamespace()

    inst = object.__new__(transcriber.Transcriber)
    inst.language = "sv"
    inst._model_lock = __import__("threading").RLock()
    inst.vad_filter = True
    inst.model = FakeModel()
    out = inst._transcribe_local(np.ones(16000, dtype=np.float32))
    assert out == "Hej"
    assert calls == [True]              # VAD non-empty → no second pass
