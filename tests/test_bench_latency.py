"""L0: benchmark harness + latency logging fields."""
from __future__ import annotations

import importlib
import io
import time
import wave

import numpy as np


def _load_bench():
    return importlib.import_module("tests.bench_latency")


def test_run_bench_reports_percentiles_for_all_steps():
    bench = _load_bench()
    audio = np.ones(1600, dtype=np.float32)
    res = bench.run_bench(
        audio, iterations=5,
        transcribe=lambda a: (time.sleep(0.001) or "hej"),
        polish=lambda t: (time.sleep(0.001) or t + "!"),
        paste=lambda t: None,
        context=lambda: None,
        conn_provider=lambda: 1.0,
    )
    for k in ("transcribe_ms", "llm_ms", "paste_ms", "context_hotpath_ms", "conn_ms"):
        assert k in res, f"missing {k}"
        assert "p50" in res[k] and "p95" in res[k]
        assert res[k]["p95"] >= res[k]["p50"]


def test_run_bench_skips_optional_steps():
    bench = _load_bench()
    audio = np.ones(800, dtype=np.float32)
    res = bench.run_bench(audio, iterations=3, transcribe=lambda a: "x")
    assert "transcribe_ms" in res
    # No polish/paste/context/conn callables → those keys absent.
    assert "llm_ms" not in res
    assert "conn_ms" not in res


def test_load_wav_roundtrip(tmp_path):
    bench = _load_bench()
    path = tmp_path / "a.wav"
    samples = (np.ones(1000, dtype=np.float32) * 0.5)
    pcm = (samples * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm.tobytes())
    _ = buf
    audio, rate = bench.load_wav(str(path))
    assert rate == 16000
    assert audio.shape[0] == 1000
    assert audio.dtype == np.float32


def test_percentile_helpers():
    bench = _load_bench()
    vals = [10, 20, 30, 40, 50]
    assert bench._percentile(vals, 50) == 30
    assert bench._percentile([], 50) == 0.0
    assert bench._percentile([7], 95) == 7


def test_log_latency_accepts_and_records_new_fields(monkeypatch):
    import sys
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    dictation = importlib.reload(importlib.import_module("dictation"))
    dictation._latency_samples.clear()

    # Should not raise with the full set of L0 fields.
    for _ in range(3):
        dictation.DictationMode._log_latency(
            100, 200, 300, 5,
            context_hotpath_ms=2, uia_ms=120, conn_ms=0,
            conn_reused=True, first_token_ms=80)

    assert len(dictation._latency_samples) == 3
    assert dictation._latency_samples[-1]["transcribe_ms"] == 200
