"""Fix #4: a hung UIA read leaks at most one thread (single-flight lock).

Python can't kill a thread, so a UIA provider that stalls GetValuePattern keeps
the read thread alive past our timeout. A non-blocking in-flight lock guarantees
that while one read is still stuck we return empty context immediately instead
of spawning a fresh reader on every dictation; the stuck worker releases the
lock when it finally returns, bounding the leak to one thread.
"""
from __future__ import annotations

import threading
import time

import context_win as cw


def _reset_lock():
    # Ensure a clean, released lock regardless of prior test state.
    try:
        cw._uia_read_lock.release()
    except RuntimeError:
        pass


def test_fast_read_returns_value_and_frees_lock(monkeypatch):
    _reset_lock()
    monkeypatch.setattr(cw, "get_focused_text", lambda: "hej Kalmar")
    assert cw._focused_text_with_timeout(timeout=0.2) == "hej Kalmar"
    # Lock must be free again for the next dictation.
    assert cw._uia_read_lock.acquire(blocking=False)
    cw._uia_read_lock.release()


def test_hung_read_times_out_then_lock_blocks_second_read(monkeypatch):
    _reset_lock()
    release = threading.Event()

    def hang():
        release.wait(2.0)   # stays "stuck" until we let it finish
        return "late"

    monkeypatch.setattr(cw, "get_focused_text", hang)

    t0 = time.monotonic()
    first = cw._focused_text_with_timeout(timeout=0.05)
    elapsed = time.monotonic() - t0

    assert first == ""            # timed out, empty context
    assert elapsed < 1.0          # bounded by timeout, not the 2s hang

    # While the first reader is still stuck, a second read must NOT spawn a new
    # thread — the held lock makes it return empty immediately.
    monkeypatch.setattr(
        cw, "get_focused_text",
        lambda: (_ for _ in ()).throw(AssertionError("spawned a 2nd reader")))
    assert cw._focused_text_with_timeout(timeout=0.05) == ""

    # Let the stuck worker finish; it releases the lock so reads recover.
    release.set()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if cw._uia_read_lock.acquire(blocking=False):
            cw._uia_read_lock.release()
            break
        time.sleep(0.01)
    else:
        raise AssertionError("stuck worker never released the lock")
