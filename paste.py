"""Clipboard-based paste with terminal detection and modifier release."""
import logging
import queue
import threading
import time
import ctypes

import pyperclip
import keyboard

from modifiers import CANONICAL_MODIFIERS, normalize_all

log = logging.getLogger("freewispr")

_PASTE_LOCK = threading.Lock()

# AP7.4: when enabled, the user's previous clipboard is restored shortly after
# the synthetic paste lands, instead of leaving the dictated text behind.
# Opt-in (off keeps the CLI "paste manually from clipboard" fallback).
_restore_clipboard = False
# Delay before restoring — long enough for the synthetic Ctrl+V/Shift+Insert to
# consume the dictated text first. Module-level so tests can shrink it.
_RESTORE_DELAY_S = 0.4


def set_restore_clipboard(enabled: bool) -> None:
    """Enable/disable clipboard restoration (AP7.4). Called from config apply."""
    global _restore_clipboard
    _restore_clipboard = bool(enabled)


def _active_window_class() -> str:
    """Best-effort Win32 class name for the foreground window."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, len(buf))
        return buf.value
    except Exception:
        return ""


def _paste_shortcut() -> str:
    # Classic console windows often ignore synthetic Ctrl+V; Shift+Insert is
    # the most compatible paste chord for conhost/cmd/PowerShell prompts.
    if _active_window_class() == "ConsoleWindowClass":
        return "shift+insert"
    return "ctrl+v"


def _release_modifiers(active_modifiers: tuple[str, ...] = ()):
    """Force-release modifier keys that are actually held.

    Releasing keys that are NOT pressed (e.g. ``windows`` when no Win is held)
    can trigger the Start menu on Windows 10/11. We therefore release only
    the modifiers from the active hotkey, or fall back to checking every
    canonical modifier when none is supplied.
    """
    candidates = normalize_all(active_modifiers) if active_modifiers else CANONICAL_MODIFIERS
    for key in candidates:
        try:
            if keyboard.is_pressed(key):
                keyboard.release(key)
        except Exception:
            pass


def _paste_and_keep_clipboard(text: str, replace_len: int = 0):
    """Copy dictated text to clipboard and try to paste it.

    The dictated text intentionally stays in the clipboard. This makes CLI
    workflows reliable even when synthetic Ctrl+V/Shift+Insert is ignored by
    the terminal: the user can paste manually and still gets the right text.

    ``replace_len`` (AP5 command mode): backspace that many characters first to
    delete the previously pasted block before pasting the replacement.
    """

    prev_clip = None
    if _restore_clipboard:
        # Snapshot the user's clipboard so we can put it back afterwards.
        # pyperclip is text-only: an empty result means "no text" (e.g. an
        # image) — skip restoration in that case rather than wiping it.
        try:
            prev_clip = pyperclip.paste()
        except Exception:
            prev_clip = None

    with _PASTE_LOCK:
        try:
            if replace_len > 0:
                # Delete the previous block (best-effort; assumes the caret is
                # still right after it, the common case just after dictation).
                for _ in range(replace_len):
                    keyboard.send("backspace")
            # Copy dictated text (trailing space for natural continuation)
            pyperclip.copy(text + " ")
            # keyboard.send has no built-in PAUSE (saves ~200 ms vs pyautogui)
            keyboard.send(_paste_shortcut())
        except Exception as e:
            log.warning("Kunde inte skicka Ctrl+V: %s", e)
            return

    if _restore_clipboard and prev_clip:
        # Restore after a short delay so the synthetic paste consumes the
        # dictated text first. Best-effort, never blocks the paste worker.
        def _restore(saved: str) -> None:
            time.sleep(_RESTORE_DELAY_S)
            with _PASTE_LOCK:
                try:
                    pyperclip.copy(saved)
                except Exception:
                    pass
        threading.Thread(target=_restore, args=(prev_clip,),
                         name="clip-restore", daemon=True).start()


_paste_queue: queue.Queue[tuple[str, int]] = queue.Queue()


def _paste_worker():
    while True:
        text, replace_len = _paste_queue.get()
        try:
            _paste_and_keep_clipboard(text, replace_len)
        except Exception:
            pass


threading.Thread(target=_paste_worker, daemon=True, name="paste-worker").start()


def _paste_and_keep_clipboard_async(text: str, replace_len: int = 0):
    _paste_queue.put((text, replace_len))


def erase_last(n: int) -> None:
    """AP7.7 undo: backspace over the last pasted block (no re-paste).

    Best-effort, assumes the caret is still right after the block. Runs on a
    daemon thread so it never blocks the caller.
    """
    if n <= 0:
        return

    def _run():
        with _PASTE_LOCK:
            try:
                for _ in range(n):
                    keyboard.send("backspace")
            except Exception as e:
                log.warning("Kunde inte ångra senaste blocket: %s", e)

    threading.Thread(target=_run, daemon=True, name="undo-erase").start()


def paste_text(text: str, active_modifiers: tuple[str, ...] = (),
               replace_len: int = 0):
    """Paste text at the current cursor position.

    Steps:
      1. Release modifier keys that are actually held (only those from the
         dictation hotkey, to avoid triggering Start menu when releasing Win)
      2. Spawn a serialized async worker that copies dictated text to the
         clipboard and sends the best paste shortcut for the active window.
         The text stays in clipboard as a fallback for CLI terminals.

    ``replace_len`` backspaces over the previous block first (command mode).
    """
    text = text.strip()
    if not text:
        return

    # Release modifiers synchronously — must happen before Ctrl+V is sent.
    _release_modifiers(active_modifiers)
    _paste_and_keep_clipboard_async(text, replace_len)
