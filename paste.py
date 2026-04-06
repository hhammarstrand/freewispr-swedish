import time
import pyperclip
import pyautogui


def paste_text(text: str):
    """Copy text to clipboard and paste at the current cursor position."""
    text = text.strip()
    if not text:
        return

    # Preserve existing clipboard content
    try:
        old = pyperclip.paste()
    except Exception:
        old = ""

    pyperclip.copy(text + " ")
    time.sleep(0.3)  # wait for any held keys to be released
    pyautogui.hotkey("ctrl", "v")

    # Restore clipboard after a short delay
    time.sleep(0.4)
    try:
        pyperclip.copy(old)
    except Exception:
        pass
