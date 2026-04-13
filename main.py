"""
freewispr-swedish — Svensk speech-to-text för Windows
Entry point: system tray icon + dictation mode.
"""
import sys
import logging
from pathlib import Path

# --------------------------------------------------------------------------- #
#  Logging — sätts upp FÖRST, innan alla andra imports
# --------------------------------------------------------------------------- #

_LOG_DIR = Path.home() / ".freewispr-swedish"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = _LOG_DIR / "freewispr.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(_LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("freewispr")
log.info("=== freewispr-swedish startar ===")

try:
    import threading
    import tkinter as tk

    from PIL import Image, ImageDraw
    import pystray

    import config as cfg_module
    from transcriber import Transcriber
    from dictation import DictationMode
    from ui import SettingsWindow, SnippetsWindow, DictionaryWindow, FloatingIndicator, _style
    log.info("Alla imports OK")
except Exception:
    log.critical("Import kraschade", exc_info=True)
    sys.exit(1)

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

    model_size = _config.get("model_size", "small")
    _set_tray_status("Laddar modell...")
    try:
        _transcriber = Transcriber(
            model_size=model_size,
            use_cuda=_config.get("use_cuda", True),
        )
    except Exception as e:
        log.error("Modellfel (%s): %s", model_size, e, exc_info=True)
        log.info("Försöker fallback till 'small' med CPU...")
        _set_tray_status(f"Modellfel — fallback till 'small'")
        try:
            _transcriber = Transcriber(
                model_size="small",
                use_cuda=False,
            )
            # Update config so we don't crash again next time
            _config["model_size"] = "small"
            _config["use_cuda"] = False
            cfg_module.save(_config)
        except Exception as e2:
            log.error("Även fallback misslyckades: %s", e2, exc_info=True)
            _set_tray_status("FEL: Kunde inte ladda någon modell")
            return
    log.info("Modell laddad! Appen är redo.")

    _dictation = DictationMode(
        _transcriber,
        hotkey=_config.get("hotkey", "ctrl+space"),
        on_status=_set_tray_status,
        indicator=_indicator,
        mic_device=_config.get("mic_device"),
    )
    _dictation.start()
    _set_tray_status(f"Klar — håll {_config.get('hotkey','ctrl+space').upper()} för att prata")

    # Auto-enable startup on first launch (when running as exe)
    if getattr(sys, 'frozen', False) and not _is_startup_enabled():
        try:
            _enable_startup()
            _rebuild_menu()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
#  Status helpers                                                              #
# --------------------------------------------------------------------------- #

def _set_tray_status(msg: str):
    if _tray_icon:
        _tray_icon.title = f"freewispr-swedish — {msg}"
    if _status_var and _tk_root:
        _tk_root.after(0, lambda: _status_var.set(msg))


# --------------------------------------------------------------------------- #
#  Tray menu callbacks                                                         #
# --------------------------------------------------------------------------- #

def _open_snippets(_=None):
    if _tk_root:
        _tk_root.after(0, lambda: SnippetsWindow())


def _open_dictionary(_=None):
    if _tk_root:
        _tk_root.after(0, lambda: DictionaryWindow())


def _open_settings(_=None):
    if _tk_root:
        _tk_root.after(0, _show_settings)


def _show_settings():
    SettingsWindow(_config, on_save=_apply_settings)


def _apply_settings(new_cfg: dict):
    global _config, _dictation, _transcriber

    old_model = _config.get("model_size")
    old_cuda = _config.get("use_cuda")

    _config.update(new_cfg)
    cfg_module.save(_config)

    new_model = _config.get("model_size", "small")
    new_cuda = _config.get("use_cuda", True)

    # Reload transcriber if model or CUDA setting changed
    if old_model != new_model or old_cuda != new_cuda:
        _set_tray_status(f"Laddar modell '{new_model}'...")
        if _indicator:
            _indicator.show(f"Laddar modell '{new_model}'...", state="transcribe")

        def _reload():
            global _transcriber, _dictation
            try:
                _transcriber = Transcriber(
                    model_size=new_model,
                    use_cuda=new_cuda,
                )
                log.info("Modell '%s' laddad!", new_model)
            except Exception as e:
                log.error("Fel vid modellbyte: %s", e, exc_info=True)
                _set_tray_status(f"Modellfel — använder tidigare modell")
                if _indicator:
                    _indicator.show(f"Modellfel: {e}", state="error")
                    _indicator.hide(delay_ms=4000)
                return
            # Restart dictation with the new transcriber
            if _dictation:
                _dictation.stop()
            _dictation = DictationMode(
                _transcriber,
                hotkey=_config.get("hotkey", "ctrl+space"),
                on_status=_set_tray_status,
                indicator=_indicator,
                mic_device=_config.get("mic_device"),
            )
            _dictation.start()
            _set_tray_status(f"Modell '{new_model}' klar — håll {_config.get('hotkey','ctrl+space').upper()}")
            if _indicator:
                _indicator.show(f"Modell '{new_model}' klar", state="done")
                _indicator.hide(delay_ms=2000)

        threading.Thread(target=_reload, daemon=True).start()
        return

    # Restart dictation with new hotkey / mic
    if _dictation:
        _dictation.stop()
    _dictation = DictationMode(
        _transcriber,
        hotkey=_config.get("hotkey", "ctrl+space"),
        on_status=_set_tray_status,
        indicator=_indicator,
        mic_device=_config.get("mic_device"),
    )
    _dictation.start()
    _set_tray_status(f"Inställningar sparade — håll {_config.get('hotkey','ctrl+space').upper()} för att prata")


def _startup_exe_path() -> str:
    """Return the command to register for startup."""
    import os
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller exe — register the exe directly
        return f'"{sys.executable}"'
    else:
        # Running as script — use pythonw to avoid console window
        script = os.path.abspath(os.path.join(os.path.dirname(__file__), "main.py"))
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        return f'"{pythonw}" "{script}"'


def _is_startup_enabled() -> bool:
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run")
        winreg.QueryValueEx(key, "freewispr-swedish")
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _enable_startup():
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Microsoft\Windows\CurrentVersion\Run",
                         0, winreg.KEY_SET_VALUE)
    winreg.SetValueEx(key, "freewispr-swedish", 0, winreg.REG_SZ, _startup_exe_path())
    winreg.CloseKey(key)


def _toggle_startup(_=None):
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Microsoft\Windows\CurrentVersion\Run",
                         0, winreg.KEY_SET_VALUE)
    if _is_startup_enabled():
        winreg.DeleteValue(key, "freewispr-swedish")
        _set_tray_status("Borttagen från uppstart")
    else:
        winreg.SetValueEx(key, "freewispr-swedish", 0, winreg.REG_SZ, _startup_exe_path())
        _set_tray_status("Startar med Windows ✓")
    winreg.CloseKey(key)
    _rebuild_menu()


def _rebuild_menu():
    if _tray_icon:
        _tray_icon.menu = _build_menu()


def _build_menu():
    startup_label = "✓ Starta med Windows" if _is_startup_enabled() else "Starta med Windows"
    return pystray.Menu(
        pystray.MenuItem("Snippets", _open_snippets),
        pystray.MenuItem("Personlig ordlista", _open_dictionary),
        pystray.MenuItem("Inställningar", _open_settings),
        pystray.MenuItem(startup_label, _toggle_startup),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Avsluta freewispr-swedish", _quit),
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

    _status_var = tk.StringVar(value="Startar...")
    _indicator = FloatingIndicator(_tk_root)

    # Build tray icon
    menu = _build_menu()
    _tray_icon = pystray.Icon(
        "freewispr-swedish",
        _make_icon(),
        "freewispr-swedish — Startar...",
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
