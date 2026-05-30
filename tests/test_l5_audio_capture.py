"""L5.4: prefer 16 kHz mono capture; finalize_audio skips resample at 16k."""
from __future__ import annotations

import importlib

import numpy as np


def test_build_candidates_prefers_16k_mono(monkeypatch):
    audio = importlib.reload(importlib.import_module("audio"))
    monkeypatch.setattr(audio, "_devices", lambda: [
        {"name": "Mic", "max_input_channels": 2, "hostapi": 0,
         "default_samplerate": 48000.0},
    ])
    monkeypatch.setattr(audio, "_hostapis", lambda: [{"name": "WASAPI"}])
    monkeypatch.setattr(audio, "_api_priority", lambda: {0: 0})

    rec = object.__new__(audio.MicRecorder)
    rec._device_index = None
    rec._device_name = None
    rec._device_api = None

    cands = rec._build_candidates()
    assert cands, "expected at least one candidate"
    # First candidate is 16 kHz mono on the device.
    idx, rate, ch, _label = cands[0]
    assert (rate, ch) == (16000, 1)
    # Native-rate candidates are still present as fallback.
    assert any(rate == 48000 for (_i, rate, _c, _l) in cands)


def test_finalize_audio_skips_resample_at_16k():
    audio = importlib.reload(importlib.import_module("audio"))
    buf = np.ones(16000, dtype=np.float32) * 0.1
    out = audio.finalize_audio(buf, 1, 16000)
    # No resampling: identical length, unchanged content.
    assert out.shape[0] == 16000
    assert np.allclose(out, buf)


def test_finalize_audio_resamples_from_48k():
    audio = importlib.reload(importlib.import_module("audio"))
    buf = np.ones(48000, dtype=np.float32) * 0.1
    out = audio.finalize_audio(buf, 1, 48000)
    # ~1 s at 16 kHz after resampling (allow filter edge tolerance).
    assert 15000 <= out.shape[0] <= 17000
