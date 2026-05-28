"""Tests for the MicRecorder prewarm rolling buffer + prepend logic.

These don't touch a real audio device — they construct a MicRecorder and
drive its callback directly with synthetic input. The goal is to verify
the ring-buffer write semantics and that start() prepends the rolling
history into the main capture buffer in chronological order.
"""
import numpy as np
import pytest

from audio import MicRecorder


def _make_recorder_with_prewarm(rate=16000, channels=1, prewarm_secs=0.5):
    """Build a MicRecorder ready for prewarm without opening a real device."""
    r = MicRecorder()
    r._rate = rate
    r._buffer_channels = channels
    # Allocate main capture buffer (mimics _ensure_buffer for tests).
    capacity = rate * 5  # 5 seconds is enough for any test below
    if channels > 1:
        r._buffer = np.zeros((capacity, channels), dtype=np.float32)
    else:
        r._buffer = np.zeros(capacity, dtype=np.float32)
    r._buffer_capacity = capacity
    # Allocate prewarm rolling buffer.
    r._prewarm_capacity = max(1, int(rate * prewarm_secs))
    r._prewarm_buf = np.zeros(r._prewarm_capacity, dtype=np.float32)
    r._prewarming = True
    r._prewarm_requested = True
    return r


def _drive_callback(recorder, samples_1d):
    """Mimic sounddevice handing us a (frames, channels) ndarray."""
    indata = samples_1d.astype(np.float32).reshape(-1, 1)
    recorder._cb(indata, frames=len(samples_1d), time=None, status=None)


def test_prewarm_buffer_fills_below_capacity():
    r = _make_recorder_with_prewarm(rate=1000, prewarm_secs=0.5)  # cap=500
    _drive_callback(r, np.arange(100, dtype=np.float32))
    assert r._prewarm_written == 100
    assert r._prewarm_write == 100
    assert np.array_equal(r._prewarm_buf[:100], np.arange(100, dtype=np.float32))


def test_prewarm_buffer_wraps_when_exceeding_capacity():
    r = _make_recorder_with_prewarm(rate=1000, prewarm_secs=0.5)  # cap=500
    _drive_callback(r, np.arange(700, dtype=np.float32))
    # We wrote 700 samples into a 500-slot ring. The newest 500 should be
    # values 200..699. Reading them in chronological order means starting
    # at write%cap=200 and wrapping.
    assert r._prewarm_written == 500
    assert r._prewarm_write == 200
    history = np.concatenate((r._prewarm_buf[r._prewarm_write:],
                              r._prewarm_buf[:r._prewarm_write]))
    assert np.array_equal(history, np.arange(200, 700, dtype=np.float32))


def test_prewarm_does_not_write_to_main_buffer_or_update_level():
    r = _make_recorder_with_prewarm(rate=1000, prewarm_secs=0.5)
    r.level = 0.0  # baseline
    _drive_callback(r, np.full(100, 0.5, dtype=np.float32))
    assert r._buffer_offset == 0
    # Level callback must not fire during prewarm — would make the
    # indicator equalizer dance when nothing is being recorded.
    assert r.level == 0.0


def test_start_prepends_prewarm_history_in_chronological_order():
    r = _make_recorder_with_prewarm(rate=1000, prewarm_secs=0.5)  # cap=500
    # Fill 300 samples (no wrap yet).
    _drive_callback(r, np.arange(1, 301, dtype=np.float32))
    # Now simulate start() but without opening a real stream — we patch
    # _stream to a sentinel so the fast path triggers.
    r._stream = object()
    # Manually replicate the prepend that start() would do under lock.
    r._prewarming = False
    r._buffer_offset = 0
    r._sumsq = 0.0
    r._sumsq_count = 0
    r._buffer_overflow = False
    r.recording = True
    with r._prewarm_lock:
        r._prepend_prewarm_locked()
    assert r._buffer_offset == 300
    assert np.array_equal(r._buffer[:300], np.arange(1, 301, dtype=np.float32))
    # Prewarm cursor is reset so the next callback writes to main, not the
    # rolling buffer.
    assert r._prewarm_written == 0
    assert r._prewarm_write == 0


def test_start_prepends_after_wrap_in_chronological_order():
    r = _make_recorder_with_prewarm(rate=1000, prewarm_secs=0.5)  # cap=500
    # Write 700 samples — older 200 fall off, newest 500 (200..699) survive.
    _drive_callback(r, np.arange(700, dtype=np.float32))
    r._stream = object()
    r._prewarming = False
    r._buffer_offset = 0
    r._sumsq = 0.0
    r._sumsq_count = 0
    r._buffer_overflow = False
    r.recording = True
    with r._prewarm_lock:
        r._prepend_prewarm_locked()
    assert r._buffer_offset == 500
    assert np.array_equal(r._buffer[:500], np.arange(200, 700, dtype=np.float32))


def test_stop_fast_with_prewarm_requested_keeps_stream_open():
    r = _make_recorder_with_prewarm(rate=1000, prewarm_secs=0.5)
    # Simulate an active recording: stream open, prewarming off, main buffer
    # has some content, prewarm cursors leftover from a previous capture.
    r._stream = object()
    r._prewarming = False
    r.recording = True
    r._buffer[:50] = np.arange(50, dtype=np.float32)
    r._buffer_offset = 50
    r._prewarm_write = 123
    r._prewarm_written = 456

    captured, channels, rate = r.stop_fast()

    assert len(captured) == 50
    assert r._stream is not None, "stream must stay open when prewarm requested"
    assert r._prewarming is True, "must flip back into prewarming mode"
    assert r.recording is False
    # Rolling cursors reset so the next start() doesn't replay stale audio
    # that overlapped with the just-captured segment.
    assert r._prewarm_write == 0
    assert r._prewarm_written == 0


def test_stop_fast_without_prewarm_requested_closes_stream():
    r = _make_recorder_with_prewarm(rate=1000, prewarm_secs=0.5)
    r._prewarm_requested = False
    r._stream = object()
    r.recording = True
    r._buffer_offset = 10

    captured, _, _ = r.stop_fast()

    # When prewarm is off we get the legacy behaviour: stream closed.
    assert r._stream is None


def test_shutdown_clears_all_state():
    r = _make_recorder_with_prewarm()
    r._stream = object()
    r.shutdown()
    assert r._stream is None
    assert r._prewarming is False
    assert r._prewarm_requested is False
    assert r.recording is False
