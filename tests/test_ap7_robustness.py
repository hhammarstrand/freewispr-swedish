"""AP7: single-instance lock, clipboard restore, max_tokens budget."""
from __future__ import annotations

import importlib
import time


# --------------------------------------------------------------------------- #
#  AP7.8 — max_tokens budget
# --------------------------------------------------------------------------- #

def test_token_budget_is_token_sized_not_char_sized():
    llm = importlib.reload(importlib.import_module("llm_polish"))
    # ~120-char Swedish utterance: old formula gave 120*1.3+32 = 188 (4-5x too
    # big); token estimate should be far smaller but still cover the output.
    b = llm._token_budget(120)
    assert 60 <= b <= 130
    # Floor.
    assert llm._token_budget(3) == 64
    # Cap.
    assert llm._token_budget(100_000) == 2048
    # Never truncates same-length output (~chars/3 tokens).
    assert llm._token_budget(300) >= 300 / 3


# --------------------------------------------------------------------------- #
#  AP7.4 — clipboard restore
# --------------------------------------------------------------------------- #

def _setup_clip(monkeypatch, paste, initial):
    clip = {"v": initial}
    monkeypatch.setattr(paste.pyperclip, "paste", lambda: clip["v"])
    monkeypatch.setattr(paste.pyperclip, "copy",
                        lambda t: clip.__setitem__("v", t))
    monkeypatch.setattr(paste.keyboard, "send", lambda k: None)
    monkeypatch.setattr(paste, "_active_window_class", lambda: "NotConsole")
    monkeypatch.setattr(paste, "_RESTORE_DELAY_S", 0.01)
    return clip


def test_clipboard_restored_when_enabled(monkeypatch):
    paste = importlib.reload(importlib.import_module("paste"))
    clip = _setup_clip(monkeypatch, paste, "USER PREV")
    paste.set_restore_clipboard(True)
    try:
        paste._paste_and_keep_clipboard("hej")
        # Immediately after, the dictated text is on the clipboard.
        assert clip["v"] == "hej "
        # After the delay it is restored to the user's previous content.
        for _ in range(100):
            if clip["v"] == "USER PREV":
                break
            time.sleep(0.01)
        assert clip["v"] == "USER PREV"
    finally:
        paste.set_restore_clipboard(False)


def test_clipboard_left_behind_when_disabled(monkeypatch):
    paste = importlib.reload(importlib.import_module("paste"))
    clip = _setup_clip(monkeypatch, paste, "USER PREV")
    paste.set_restore_clipboard(False)
    paste._paste_and_keep_clipboard("hej")
    time.sleep(0.05)
    assert clip["v"] == "hej "          # unchanged behaviour (CLI fallback)


def test_clipboard_restore_skips_non_text(monkeypatch):
    paste = importlib.reload(importlib.import_module("paste"))
    # Empty previous clipboard = "no text" (e.g. an image) → don't restore it.
    clip = _setup_clip(monkeypatch, paste, "")
    paste.set_restore_clipboard(True)
    try:
        paste._paste_and_keep_clipboard("hej")
        time.sleep(0.05)
        assert clip["v"] == "hej "      # not wiped back to empty
    finally:
        paste.set_restore_clipboard(False)


# --------------------------------------------------------------------------- #
#  AP7.1 — single-instance lock
# --------------------------------------------------------------------------- #

def test_single_instance_second_acquire_fails():
    si = importlib.reload(importlib.import_module("single_instance"))
    assert si.acquire("test-fw") is True
    try:
        # A second acquire in the same process must fail (port already bound).
        assert si.acquire("test-fw") is False
    finally:
        si.release()
    # After release the lock is available again.
    assert si.acquire("test-fw") is True
    si.release()


def test_main_exits_early_when_locked(monkeypatch):
    import pytest
    # main imports tkinter/PIL/pystray; skip on the headless CI image (same
    # gate the other main-importing tests use). Runs on a full dev env.
    pytest.importorskip("PIL")
    pytest.importorskip("pystray")
    pytest.importorskip("tkinter")

    main = importlib.import_module("main")
    import single_instance
    monkeypatch.setattr(single_instance, "acquire", lambda *a, **k: False)

    def _boom():
        raise AssertionError("main proceeded past the single-instance guard")

    monkeypatch.setattr(main, "_attach_file_logging", _boom)
    # Returns cleanly without touching logging/tray/model.
    assert main.main() is None
