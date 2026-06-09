"""Tests for the performance-research round: streaming finalize, context tail."""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import numpy as np
import pytest


# --------------------------------------------------------------------------- #
#  audio.StreamingFinalizer — incremental == batch
# --------------------------------------------------------------------------- #

def _audio():
    return importlib.import_module("audio")


def test_streaming_finalizer_matches_batch_resample():
    audio = _audio()
    if not audio.StreamingFinalizer.available():
        pytest.skip("soxr saknas")
    rate = 48000
    rng = np.random.default_rng(7)
    raw = (rng.standard_normal((rate * 5, 2)) * 0.1).astype(np.float32)

    batch = audio.finalize_audio(raw.copy(), 2, rate)
    sf = audio.StreamingFinalizer(2, rate)
    out = [sf.feed(chunk) for chunk in np.array_split(raw, 9)]
    inc = np.concatenate([o for o in out if o.size])

    # The stream lags batch by the (unflushed) filter tail only.
    assert batch.size - inc.size < rate // 100  # < 10 ms worth of samples
    n = min(inc.size, batch.size)
    assert np.allclose(inc[:n], batch[:n], atol=1e-3)


def test_streaming_finalizer_locks_lone_channel():
    audio = _audio()
    if not audio.StreamingFinalizer.available():
        pytest.skip("soxr saknas")
    rate = 16000  # no resample → output == downmix, easy to assert
    rng = np.random.default_rng(7)
    left = (rng.standard_normal(rate) * 0.2).astype(np.float32)
    raw = np.column_stack([left, np.zeros(rate, dtype=np.float32)])

    sf = audio.StreamingFinalizer(2, rate)
    out = np.concatenate([sf.feed(c) for c in np.array_split(raw, 4)])
    # Lone active channel selected (matching _to_mono), not averaged/halved.
    assert np.allclose(out, left, atol=1e-6)


def test_streaming_finalizer_16k_passthrough_mono():
    audio = _audio()
    if not audio.StreamingFinalizer.available():
        pytest.skip("soxr saknas")
    sf = audio.StreamingFinalizer(1, 16000)
    x = np.ones(1000, dtype=np.float32)
    assert np.array_equal(sf.feed(x), x)
    assert sf.feed(np.empty(0, dtype=np.float32)).size == 0


# --------------------------------------------------------------------------- #
#  dictation._context_tail_for_stt — continuation bias + privacy gate
# --------------------------------------------------------------------------- #

def _mode(dictation, *, consent=False):
    mode = object.__new__(dictation.DictationMode)
    mode.context_to_remote_accepted = consent
    return mode


def _ctx(text):
    return SimpleNamespace(focused_text=text)


def test_context_tail_local_provider_passes_tail(monkeypatch):
    d = importlib.import_module("dictation")
    mode = _mode(d)
    assert mode._context_tail_for_stt(_ctx("Hej världen."), "local") == "Hej världen."


def test_context_tail_remote_without_consent_is_empty():
    d = importlib.import_module("dictation")
    mode = _mode(d, consent=False)
    assert mode._context_tail_for_stt(_ctx("känslig text"), "staik") == ""


def test_context_tail_remote_with_consent_passes():
    d = importlib.import_module("dictation")
    mode = _mode(d, consent=True)
    assert mode._context_tail_for_stt(_ctx("ok text"), "staik") == "ok text"


def test_context_tail_collapses_whitespace_and_caps_length():
    d = importlib.import_module("dictation")
    mode = _mode(d)
    long = ("ord" + "x" * 5 + " ") * 100 + "slutet av meningen"
    tail = mode._context_tail_for_stt(_ctx(long.replace(" ", "\n", 3)), "local")
    assert "\n" not in tail
    assert len(tail) <= d._CTX_TAIL_MAX_CHARS
    assert tail.endswith("slutet av meningen")
    # No mid-word start: the first token is a complete word from the source.
    assert not tail.startswith("x")


def test_context_tail_none_ctx_is_empty():
    d = importlib.import_module("dictation")
    mode = _mode(d)
    assert mode._context_tail_for_stt(None, "local") == ""
