import time
import logging
import pyperclip
import pyautogui

log = logging.getLogger("freewispr")

# Modifier keys that could interfere with Ctrl+V if still held
# when paste_text is called (e.g. user just released Ctrl+Space).
_MODIFIERS = ["ctrl", "shift", "alt", "win"]


def _release_modifiers():
    """Force-release all modifier keys so Ctrl+V works cleanly.

    Without this, if the user's hotkey includes Ctrl (e.g. Ctrl+Space),
    the Ctrl key might still be physically held or stuck in the OS
    key state when we fire Ctrl+V, causing unexpected behavior.
    """
    for key in _MODIFIERS:
        try:
            pyautogui.keyUp(key)
        except Exception:
            pass


def paste_text(text: str):
    """Copy text to clipboard and paste at the current cursor position.

    Steps:
      1. Save current clipboard content
      2. Release any held modifier keys (avoids ghost Ctrl/Shift)
      3. Copy dictated text to clipboard
      4. Small delay for key state to settle
      5. Send Ctrl+V
      6. Restore original clipboard content
    """
    text = text.strip()
    if not text:
        return

    # 1. Preserve existing clipboard content
    try:
        old = pyperclip.paste()
    except Exception:
        old = ""

    # 2. Release modifiers — critical for reliable paste
    _release_modifiers()

    # 3. Copy dictated text (with trailing space for natural continuation)
    pyperclip.copy(text + " ")

    # 4. Brief pause for key state + clipboard to settle
    time.sleep(0.05)

    # 5. Paste
    pyautogui.hotkey("ctrl", "v")

    # 6. Restore clipboard after paste completes
    time.sleep(0.3)
    try:
        pyperclip.copy(old)
    except Exception:
        pass
