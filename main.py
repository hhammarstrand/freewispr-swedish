"""
freewispr — Windows speech-to-text
Entry point: system tray icon + dictation mode.
"""
import sys
import threading
import tkinter as tk

from PIL import Image, ImageDraw
import pystray

import config as cfg_module
from transcriber import Transcriber
from dictation import DictationMode
from ui import SettingsWindow, FloatingIndicator, _style

# --------------------------------------------------------------------------- #
#  Globals                                                                     #
# --------------------------------------------------------------------------- #

_config: dict = {}
_transcriber: Transcriber | None = None
_dictation: DictationMode | None = None
_tray_icon: pystray.Icon | None = None
_tk_root: tk.Tk | None = None
_status_var: tk.StringVar | None = None
_indicator: FloatingIndicator | None = None


# --------------------------------------------------------------------------- #
#  Tray icon image (drawn with Pillow — no external asset needed)             #
# --------------------------------------------------------------------------- #

def _make_icon() -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Purple circle
    draw.ellipse([4, 4, size - 4, size - 4], fill="#7c5cfc")
    # White mic body
    cx = size // 2
    draw.rounded_rectangle([cx - 9, 12, cx + 9, 36], radius=9, fill="white")
    # Mic stand
    draw.arc([cx - 16, 26, cx + 16, 50], start=0, end=180, fill="white", width=3)
    draw.line([cx, 50, cx, 58], fill="white", width=3)
    draw.line([cx - 8, 58, cx + 8, 58], fill="white", width=3)
    return img


# --------------------------------------------------------------------------- #
#  App init                                                                    #
# --------------------------------------------------------------------------- #

def _load_app():
    global _config, _transcriber, _dictation

    _config = cfg_module.load()

    model_size = _config.get("model_size", "base")
    print(f"Loading Whisper '{model_size}' model...", flush=True)
    _set_tray_status("Loading model…")
    _transcriber = Transcriber(
        model_size=model_size,
        language=_config.get("language", "en"),
        filter_fillers=_config.get("filter_fillers", False),
    )
    print("Model loaded! App is ready.", flush=True)

    _dictation = DictationMode(
        _transcriber,
        hotkey=_config.get("hotkey", "ctrl+space"),
        on_status=_set_tray_status,
        indicator=_indicator,
    )
    _dictation.start()
    _set_tray_status(f"Ready — hold {_config.get('hotkey','ctrl+space').upper()} to speak")


# --------------------------------------------------------------------------- #
#  Status helpers                                                              #
# --------------------------------------------------------------------------- #

def _set_tray_status(msg: str):
    if _tray_icon:
        _tray_icon.title = f"freewispr — {msg}"
    if _status_var and _tk_root:
        _tk_root.after(0, lambda: _status_var.set(msg))


# --------------------------------------------------------------------------- #
#  Tray menu callbacks                                                         #
# --------------------------------------------------------------------------- #

def _open_settings(_=None):
    if _tk_root:
        _tk_root.after(0, _show_settings)


def _show_settings():
    SettingsWindow(_config, on_save=_apply_settings)


def _apply_settings(new_cfg: dict):
    global _config, _dictation, _transcriber
    _config.update(new_cfg)
    cfg_module.save(_config)

    # Rebuild transcriber if filler setting changed
    if _transcriber:
        _transcriber.filter_fillers = _config.get("filter_fillers", False)

    # Restart dictation with new hotkey
    if _dictation:
        _dictation.stop()
    _dictation = DictationMode(
        _transcriber,
        hotkey=_config.get("hotkey", "ctrl+space"),
        on_status=_set_tray_status,
        indicator=_indicator,
    )
    _dictation.start()
    _set_tray_status(f"Settings saved — hold {_config.get('hotkey','ctrl+space').upper()} to speak")


def _is_startup_enabled() -> bool:
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run")
        winreg.QueryValueEx(key, "freewispr")
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _toggle_startup(_=None):
    import winreg
    vbs = r"C:\Users\prakh\AI Experiments\freewispr\launch.vbs"
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Microsoft\Windows\CurrentVersion\Run",
                         0, winreg.KEY_SET_VALUE)
    if _is_startup_enabled():
        winreg.DeleteValue(key, "freewispr")
        _set_tray_status("Removed from startup")
    else:
        winreg.SetValueEx(key, "freewispr", 0, winreg.REG_SZ, f'wscript.exe "{vbs}"')
        _set_tray_status("Will start with Windows ✓")
    winreg.CloseKey(key)
    _rebuild_menu()


def _rebuild_menu():
    if _tray_icon:
        _tray_icon.menu = _build_menu()


def _build_menu():
    startup_label = "✓ Start with Windows" if _is_startup_enabled() else "Start with Windows"
    return pystray.Menu(
        pystray.MenuItem("Settings", _open_settings),
        pystray.MenuItem(startup_label, _toggle_startup),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit freewispr", _quit),
    )


def _quit(_=None):
    if _dictation:
        _dictation.stop()
    if _tray_icon:
        _tray_icon.stop()
    if _tk_root:
        _tk_root.quit()
        _tk_root.destroy()
    sys.exit(0)


# --------------------------------------------------------------------------- #
#  Main                                                                        #
# --------------------------------------------------------------------------- #

def main():
    global _tray_icon, _tk_root, _status_var, _indicator

    # Hidden tk root — keeps tkinter event loop running for Toplevel windows
    _tk_root = tk.Tk()
    _tk_root.withdraw()
    _style(_tk_root)

    _status_var = tk.StringVar(value="Starting…")
    _indicator = FloatingIndicator(_tk_root)

    # Build tray icon
    menu = _build_menu()
    _tray_icon = pystray.Icon(
        "freewispr",
        _make_icon(),
        "freewispr — Starting…",
        menu,
    )

    # Load model in background so the tray appears immediately
    threading.Thread(target=_load_app, daemon=True).start()

    # Run tray in a background thread; tkinter runs on main thread
    tray_thread = threading.Thread(target=_tray_icon.run, daemon=True)
    tray_thread.start()

    # tkinter main loop (needed for Toplevel windows + FloatingIndicator)
    _tk_root.mainloop()


if __name__ == "__main__":
    main()
