"""
freewispr-swedish — Svensk speech-to-text för Windows
Entry point: system tray icon + dictation mode.
"""
from __future__ import annotations

import gc
import sys
import logging
from pathlib import Path

# --------------------------------------------------------------------------- #
#  AppUserModelID — must be set before *any* window is created (and ideally
#  before tkinter is even imported by a transitive dependency), otherwise
#  Windows groups our taskbar entry under pythonw.exe and shows the Python
#  logo. Setting it here at module top is the earliest we can.
# --------------------------------------------------------------------------- #
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "se.freewispr.swedish.app")
    except Exception:
        pass

# --------------------------------------------------------------------------- #
#  Logging — basic config now, file handler is wired in main()
# --------------------------------------------------------------------------- #

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("freewispr")

# --------------------------------------------------------------------------- #
#  Version - single source of truth. Bumpa här vid release och tagga git.
# --------------------------------------------------------------------------- #
__version__ = "1.0.0"

log.info("=== freewispr-swedish %s startar ===", __version__)

_LOG_DIR = Path.home() / ".freewispr-swedish"
_LOG_FILE = _LOG_DIR / "freewispr.log"


def _attach_file_logging() -> None:
    """Create the log dir and attach the file handler.

    Done from main() (not at import) so unit tests can ``import main`` /
    transitively pull config without writing to disk.
    """
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
        )
        logging.getLogger().addHandler(handler)
    except Exception as e:
        log.warning("Kunde inte aktivera filloggning: %s", e)

try:
    import multiprocessing as mp
    import threading
    import tkinter as tk

    from PIL import Image, ImageDraw
    import pystray

    import config as cfg_module
    # Heavy modules are imported lazily via _make_transcriber/_make_dictation
    # so the tray icon appears in <1 second.
    from ui import SettingsWindow, _style
    from ui.qt_indicator import FloatingIndicator
    log.info("Snabb-imports OK")
except Exception:
    log.critical("Import kraschade", exc_info=True)
    sys.exit(1)

# --------------------------------------------------------------------------- #
#  Globals                                                                     #
# --------------------------------------------------------------------------- #

_config: dict = {}
_transcriber = None   # Transcriber (lazy-imported)
_dictation = None     # DictationMode (lazy-imported)
_flow = None          # FlowMode (AP6, lazy-imported)
_tray_icon: pystray.Icon | None = None
_tk_root: tk.Tk | None = None
_status_var: tk.StringVar | None = None
_indicator: FloatingIndicator | None = None
# Singleton reference — _show_settings reuses the live window when one is
# already open instead of spawning unlimited copies.
_settings_window = None

# Set by the background update-check thread when a newer release is
# detected on GitHub. Read by _build_menu() to surface the menu entry and
# by _open_release_page() to know where to send the user.
_pending_update = None  # updater.UpdateInfo | None

# Serializes settings-driven reloads. Without it, a user spamming Save
# could spawn two _reload threads, double-loading the model into VRAM
# and leaking a Transcriber + DictationMode pair.
_reload_lock = threading.Lock()

# Serializes _apply_settings itself so two concurrent Save clicks can't
# interleave config mutations / dictation restarts. The tray menu can
# fire Save from a different thread than tkinter, and _reload_lock alone
# only protects the model-reload branch.
_config_lock = threading.Lock()


# --------------------------------------------------------------------------- #
#  DRY constructors for Transcriber / DictationMode                            #
# --------------------------------------------------------------------------- #

def _active_llm_settings() -> tuple[bool, str, str, str, str]:
    """Plocka ut (enabled, api_key, model, provider, base_url) för aktiv LLM-provider.

    Hålls i en funktion så _make_transcriber och _apply_settings ser
    exakt samma vy av configgen.
    """
    provider = _config.get("llm_provider", "github")
    enabled = bool(
        _config.get("llm_enabled", False)
        and _config.get("llm_privacy_accepted", False)
    )
    api_key = _config.get(f"llm_api_key_{provider}", "")
    model = _config.get(f"llm_model_{provider}", "")
    base_url = _config.get("llm_custom_base_url", "") if provider == "custom" else ""
    return enabled, api_key, model, provider, base_url


def _active_transcription_settings() -> tuple[str, str, str, str]:
    """(provider, api_key, model, base_url) för aktiv transkriberingsleverantör."""
    provider = _config.get("transcription_provider", "local")
    if provider == "local":
        return "local", "", "", ""
    # Remote: kräver consent — annars degradera till lokal.
    if not _config.get("transcription_privacy_accepted", False):
        log.warning("transcription_provider=%s utan consent — använder lokal", provider)
        return "local", "", "", ""
    # Egen nyckel per remote-leverantör (separat från LLM-nyckeln).
    api_key = _config.get(f"transcription_api_key_{provider}", "")
    model = _config.get(f"transcription_model_{provider}", "")
    base_url = (
        _config.get("transcription_custom_base_url", "")
        if provider == "custom" else ""
    )
    return provider, api_key, model, base_url


def _make_transcriber(model_size: str, use_cuda: bool):
    """Build a Transcriber from current _config + the given overrides.

    Kept in one place so _load_app, fallback, and reload paths cannot
    drift apart in how they wire up LLM credentials.
    """
    from transcriber import Transcriber
    llm_enabled, llm_key, llm_model, llm_provider, llm_base = _active_llm_settings()
    tr_provider, tr_key, tr_model, tr_base = _active_transcription_settings()
    return Transcriber(
        model_size=model_size,
        use_cuda=use_cuda,
        llm_enabled=llm_enabled,
        llm_api_key=llm_key,
        llm_model=llm_model,
        llm_provider=llm_provider,
        llm_base_url=llm_base,
        transcription_provider=tr_provider,
        transcription_api_key=tr_key,
        transcription_model=tr_model,
        transcription_base_url=tr_base,
        beam_size=int(_config.get("whisper_beam_size", 1)),
        vad_filter=bool(_config.get("whisper_vad_filter", True)),
        no_speech_threshold=float(_config.get("whisper_no_speech_threshold", 0.6)),
        compute_type=str(_config.get("whisper_compute_type", "")),
        kblab_revision=str(_config.get("kblab_revision", "default")),
        transcription_temperature=float(_config.get("transcription_temperature", 0.0)),
        expect_english_terms=bool(_config.get("expect_english_terms", False)),
        remote_audio_format=str(_config.get("remote_audio_format", "wav")),
        whisper_batched=bool(_config.get("whisper_batched", False)),
    )


def _apply_runtime_flags():
    """Push module-level runtime flags from config (AP7)."""
    try:
        import paste
        paste.set_restore_clipboard(bool(_config.get("restore_clipboard", False)))
    except Exception as e:
        log.debug("Kunde inte applicera runtime-flaggor: %s", e)


def _make_dictation(transcriber):
    from dictation import DictationMode, DEFAULT_MIN_RMS
    return DictationMode(
        transcriber,
        hotkey=_config.get("hotkey", "ctrl+space"),
        on_status=_set_tray_status,
        indicator=_indicator,
        mic_device=_config.get("mic_device"),
        min_rms=float(_config.get("min_rms", DEFAULT_MIN_RMS)),
        raw_mode=bool(_config.get("llm_raw_mode", False)),
        llm_timeout_sec=float(_config.get("llm_timeout_sec", 15.0)),
        context_awareness=bool(_config.get("context_awareness_enabled", True)),
        learning_enabled=bool(_config.get("learning_enabled", True)),
        app_profiles=_config.get("app_profiles") or {},
        command_mode_enabled=bool(_config.get("command_mode_enabled", True)),
        llm_replace_mode=bool(_config.get("llm_replace_mode", False)),
        context_to_remote_accepted=bool(
            _config.get("context_to_remote_accepted", False)),
        cancel_hotkey=_config.get("cancel_hotkey", "esc"),
        snippets_enabled=bool(_config.get("snippets_enabled", True)),
        silence_trim_enabled=bool(_config.get("silence_trim_enabled", True)),
        polish_skip_trivial=bool(_config.get("polish_skip_trivial", True)),
        polish_skip_max_words=int(_config.get("polish_skip_max_words", 6)),
        live_transcribe_enabled=bool(_config.get("live_transcribe_enabled", False)),
        voice_edit_hotkey=_config.get("voice_edit_hotkey", ""),
    )


# --------------------------------------------------------------------------- #
#  Tray icon image — prefer bundled asset, fall back to Pillow-drawn mic      #
# --------------------------------------------------------------------------- #

# When frozen by PyInstaller, assets live next to the executable in _MEIPASS.
_ASSET_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets"
_ICON_PATH = _ASSET_DIR / "icon.ico"


def _draw_fallback_icon() -> Image.Image:
    """Mic glyph drawn with Pillow — used only if assets/icon.ico is missing."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, size - 4, size - 4], fill="#006aa7")
    cx = size // 2
    draw.rounded_rectangle([cx - 9, 12, cx + 9, 36], radius=9, fill="white")
    draw.arc([cx - 16, 26, cx + 16, 50], start=0, end=180, fill="white", width=3)
    draw.line([cx, 50, cx, 58], fill="white", width=3)
    draw.line([cx - 8, 58, cx + 8, 58], fill="white", width=3)
    return img


def _make_icon() -> Image.Image:
    """Load the bundled tray icon, fall back to a drawn one on any failure."""
    if _ICON_PATH.is_file():
        try:
            return Image.open(_ICON_PATH)
        except Exception as e:
            log.warning("Kunde inte läsa %s: %s — använder fallback", _ICON_PATH, e)
    return _draw_fallback_icon()


# --------------------------------------------------------------------------- #
#  App init                                                                    #
# --------------------------------------------------------------------------- #

def _run_first_run_dialog() -> str | None:
    """Show the FirstRunDialog on the Tk main thread and block until closed.

    Called from the background _load_app thread. We marshal the dialog onto
    the Tk main thread (mandatory — Tk widgets aren't thread-safe), then
    wait on an Event for the dialog to close, then read back the result.
    Returns the chosen model size on success, ``None`` if the user cancelled.
    """
    if _tk_root is None:
        log.warning("Kan inte visa first-run-dialog: ingen Tk-rot")
        return None

    from ui import FirstRunDialog

    done = threading.Event()
    result: dict[str, str | None] = {"size": None}

    def _show():
        try:
            dlg = FirstRunDialog(_tk_root)
            result["size"] = dlg.result
        except Exception as e:
            log.error("FirstRunDialog kraschade: %s", e, exc_info=True)
        finally:
            done.set()

    _tk_root.after(0, _show)
    done.wait()
    return result["size"]


def _load_app():
    global _config, _transcriber, _dictation

    log.info("Laddar config och modell…")

    _config = cfg_module.load()
    _apply_runtime_flags()

    # One-shot migration of legacy snippets.json + corrections.json into the
    # new personal_context.json. Idempotent: skipped once the context file
    # exists. Originals are left on disk as a safety net.
    try:
        from migrate_context import migrate_if_needed
        if migrate_if_needed():
            log.info("Personlig kontext skapad från tidigare snippets/ordlista — "
                     "se Inställningar > Kontext för att granska")
    except Exception as mig_err:
        log.warning("Migration av kontext misslyckades (ej blockerande): %s",
                    mig_err)

    model_size = _config.get("model_size", "small")
    _set_tray_status("Laddar modell…")
    if _indicator:
        _indicator.set_follow_mouse(_config.get("indicator_follow_mouse", True))
    try:
        try:
            _transcriber = _make_transcriber(model_size, _config.get("use_cuda", True))
        except FileNotFoundError as fnf:
            # No local model cached. Offer the friendly first-run dialog
            # instead of crashing with a cryptic tray status. Only surfaces
            # when transcription_provider=="local" — remote configs never
            # raise FileNotFoundError here.
            log.info("Ingen lokal modell hittades (%s) — visar first-run-dialog", fnf)
            _set_tray_status("Välkommen — välj modell att ladda ned")
            chosen = _run_first_run_dialog()
            if chosen:
                log.info("First-run klar — användaren valde '%s'", chosen)
                _config["model_size"] = chosen
                try:
                    cfg_module.save(_config)
                except Exception as save_err:
                    log.warning("Kunde inte spara vald modellstorlek: %s", save_err)
                # Retry with the freshly-downloaded model. Honour the user's
                # current use_cuda preference; _make_transcriber's outer
                # try/except still handles GPU-fail-to-CPU fallback below.
                _transcriber = _make_transcriber(chosen, _config.get("use_cuda", True))
            else:
                # User cancelled. Fall back to remote transcription if the
                # config already has it wired up (consent + provider), else
                # surface a clear instruction in the tray.
                tr_provider, _, _, _ = _active_transcription_settings()
                if tr_provider != "local":
                    log.info("First-run avbruten — använder remote-transkribering (%s)", tr_provider)
                    _transcriber = _make_transcriber(model_size, _config.get("use_cuda", True))
                else:
                    log.info("First-run avbruten och ingen remote-konfig — avslutar laddning")
                    _set_tray_status("Avsluta och installera modell manuellt")
                    return
    except Exception as e:
        log.error("Modellfel (%s): %s", model_size, e, exc_info=True)
        log.info("Försöker fallback till 'small' med CPU…")
        _set_tray_status("Modellfel — fallback till 'small'")
        try:
            _transcriber = _make_transcriber("small", False)
            # Update config so we don't crash again next time
            _config["model_size"] = "small"
            _config["use_cuda"] = False
            cfg_module.save(_config)
        except Exception as e2:
            log.error("Även fallback misslyckades: %s", e2, exc_info=True)
            _set_tray_status("FEL: Kunde inte ladda någon modell")
            return
    log.info("Modell laddad! Appen är redo.")

    _dictation = _make_dictation(_transcriber)
    _dictation.start()
    _set_tray_status(f"Klar — håll {_config.get('hotkey','ctrl+space').upper()} för att prata")

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

def _open_settings(_=None):
    if _tk_root:
        _tk_root.after(0, _show_settings)


def _show_settings():
    """Open Settings — or focus the existing window if one is already open.

    Prevents the user from spawning unlimited Settings windows by mashing
    the tray menu / double-clicking. Keeps a weak reference to the live
    window; reopens fresh once the user has closed it.
    """
    global _settings_window
    existing = _settings_window
    if existing is not None:
        root = getattr(existing, "root", None)
        # `winfo_exists` returns "1"/"0" as a string in classic tk and an
        # int in customtkinter — both truthy-check correctly.
        try:
            if root is not None and root.winfo_exists():
                root.deiconify()
                root.lift()
                root.focus_force()
                return
        except Exception:
            # Window was destroyed without us noticing; fall through to
            # creating a fresh one.
            pass
        _settings_window = None

    _settings_window = SettingsWindow(_config, on_save=_apply_settings)


def _apply_settings(new_cfg: dict):
    """Validated settings update. Serialised on _config_lock so two
    rapid Save clicks can't interleave mutations / dictation restarts."""
    with _config_lock:
        return _apply_settings_locked(new_cfg)


def _apply_settings_locked(new_cfg: dict):
    global _config, _dictation, _transcriber

    old_config = dict(_config)  # shallow copy for rollback
    old_model = _config.get("model_size")
    old_cuda = _config.get("use_cuda")
    old_llm = _active_llm_settings()
    old_tr = _active_transcription_settings()

    # Apply in-memory first; persist to disk only after the change is
    # validated (model loaded, dictation rebuilt, etc.). This way a failed
    # reload doesn't leave a broken config on disk for the next launch.
    _config.update(new_cfg)
    _apply_runtime_flags()
    # Reflect e.g. flow_mode_enabled visibility in the tray menu.
    _rebuild_menu()

    def _persist() -> bool:
        try:
            cfg_module.save(_config)
            return True
        except Exception as e:
            log.error("Kunde inte spara inställningar: %s", e, exc_info=True)
            _set_tray_status("Fel: kunde inte spara inställningar")
            if _indicator:
                _indicator.show("Kunde inte spara inställningar", state="error")
                _indicator.hide(delay_ms=4000)
            return False

    def _rollback():
        _config.clear()
        _config.update(old_config)

    new_model = _config.get("model_size", "small")
    new_cuda = _config.get("use_cuda", True)
    new_llm = _active_llm_settings()
    new_tr = _active_transcription_settings()

    model_changed = (old_model != new_model) or (old_cuda != new_cuda)
    llm_changed = old_llm != new_llm
    # Byte mellan local <-> remote kräver full rebuild eftersom det styr
    # om WhisperModel laddas eller inte. Byten *mellan* remote-leverantörer
    # går också via rebuild — det är billigt (ingen modell laddas).
    transcription_changed = old_tr != new_tr
    tr_topology_changed = (old_tr[0] == "local") != (new_tr[0] == "local")

    # Fast path: LLM-only change *eller* remote-only transcription-change.
    # Mutera befintlig transcriber så vi slipper 5-15 s + extra VRAM för
    # en full reload. Endast tillåtet när topologin (local↔remote) inte ändras.
    fast_path = (
        (llm_changed or transcription_changed)
        and not model_changed
        and not tr_topology_changed
        and _transcriber is not None
    )
    if fast_path:
        old_transcriber_state = (
            _transcriber.llm_enabled,
            _transcriber.llm_api_key,
            _transcriber.llm_model,
            _transcriber.llm_provider,
            _transcriber.llm_base_url,
            _transcriber.transcription_provider,
            _transcriber.transcription_api_key,
            _transcriber.transcription_model,
            _transcriber.transcription_base_url,
        )
        (_transcriber.llm_enabled, _transcriber.llm_api_key,
         _transcriber.llm_model, _transcriber.llm_provider,
         _transcriber.llm_base_url) = new_llm
        (_transcriber.transcription_provider, _transcriber.transcription_api_key,
         _transcriber.transcription_model, _transcriber.transcription_base_url) = new_tr
        log.info("LLM/transkriberings-inställningar uppdaterade i befintlig transcriber")
        # Restart the connection warmers so they stop pinging the old endpoint
        # and pick up an immutable snapshot of the new credentials.
        try:
            _transcriber.restart_warmers()
        except Exception as e:
            log.debug("Kunde inte starta om warmers: %s", e)
        # Hotkey/mic may still have changed; rebuild dictation cheaply.
        _restart_dictation()
        if not _persist():
            _rollback()
            (_transcriber.llm_enabled, _transcriber.llm_api_key,
             _transcriber.llm_model, _transcriber.llm_provider,
             _transcriber.llm_base_url,
             _transcriber.transcription_provider, _transcriber.transcription_api_key,
             _transcriber.transcription_model,
             _transcriber.transcription_base_url) = old_transcriber_state
            try:
                _transcriber.restart_warmers()
            except Exception as e:
                log.debug("Kunde inte starta om warmers vid rollback: %s", e)
            _restart_dictation()
            return False
        _set_tray_status(
            f"Inställningar sparade — håll {_config.get('hotkey','ctrl+space').upper()} för att prata"
        )
        return True

    # Topology change (local <-> remote) faller igenom till model_changed-grenen
    # nedan så att Whisper-modellen laddas/släpps korrekt.
    if tr_topology_changed:
        model_changed = True

    if model_changed:
        if _indicator:
            _indicator.set_follow_mouse(_config.get("indicator_follow_mouse", True))
            _indicator.set_style(_config.get("indicator_style", "modern"))
        # Acquire before returning to the event loop so a second Save cannot
        # mutate _config in the gap before the background thread starts.
        if not _reload_lock.acquire(blocking=False):
            log.warning("Modellomladdning pågår redan — avvisar denna")
            _rollback()
            _set_tray_status("Vänta: modell laddas fortfarande")
            if _indicator:
                _indicator.show("Vänta: modell laddas", state="error")
                _indicator.hide(delay_ms=2000)
            return False
        _set_tray_status(f"Laddar modell '{new_model}'…")
        if _indicator:
            _indicator.show(f"Laddar modell '{new_model}'…", state="transcribe")

        def _reload():
            global _transcriber, _dictation
            try:
                old_transcriber = _transcriber
                old_dictation = _dictation
                try:
                    new_transcriber = _make_transcriber(new_model, new_cuda)
                except Exception as e:
                    log.error("Fel vid modellbyte: %s", e, exc_info=True)
                    _set_tray_status("Modellfel — använder tidigare modell")
                    if _indicator:
                        _indicator.show(f"Modellfel: {e}", state="error")
                        _indicator.hide(delay_ms=4000)
                    # Roll back the in-memory config so the next Save attempt
                    # sees the real previous state.
                    _rollback()
                    return
                # Unhook old hotkeys before starting the new DictationMode so
                # two hook sets cannot record/paste concurrently. Do not wait
                # for the old worker here; close() below will wait on the
                # model lock if a transcription is still in flight.
                if old_dictation is not None:
                    try:
                        old_dictation.stop(wait=False)
                    except Exception as e:
                        log.debug("Kunde inte stoppa gammal dictation rent: %s", e)
                # Release the old WhisperModel BEFORE the new one goes live so
                # two models don't stay pinned in VRAM (small CUDA GPUs OOM).
                # We're already on the background reload thread, so blocking
                # here on close() — which waits for any in-flight transcription
                # to finish on the model lock — doesn't freeze the UI. The new
                # model is already allocated above; closing first would forfeit
                # the rollback path if _make_transcriber had failed.
                if old_transcriber is not None:
                    try:
                        old_transcriber.close()
                    except Exception as e:
                        log.debug("Kunde inte stänga gammal transcriber: %s", e)
                    finally:
                        old_transcriber = None
                        gc.collect()
                _transcriber = new_transcriber
                _dictation = _make_dictation(_transcriber)
                _dictation.start()
                log.info("Modell '%s' laddad!", new_model)
                # Model loaded OK — now it's safe to persist the new config.
                if not _persist():
                    # Rare: disk write failed after a successful reload.
                    # Leave the running app on the new model (already loaded)
                    # but warn the user that the next launch will revert.
                    log.warning("Modell laddad men config kunde inte sparas")
                _set_tray_status(
                    f"Modell '{new_model}' klar — håll {_config.get('hotkey','ctrl+space').upper()} för att prata"
                )
                if _indicator:
                    _indicator.show(f"Modell '{new_model}' klar", state="done")
                    _indicator.hide(delay_ms=2000)
            finally:
                _reload_lock.release()

        threading.Thread(target=_reload, daemon=True).start()
        return True

    # No model/LLM change — just hotkey/mic. Restart dictation cheaply.
    if _indicator:
        _indicator.set_follow_mouse(_config.get("indicator_follow_mouse", True))
        _indicator.set_style(_config.get("indicator_style", "modern"))
    _restart_dictation()
    if not _persist():
        _rollback()
        _restart_dictation()  # rebind to rolled-back hotkey/mic
        return False
    _set_tray_status(
        f"Inställningar sparade — håll {_config.get('hotkey','ctrl+space').upper()} för att prata"
    )
    return True


def _restart_dictation():
    """Stop the current DictationMode (if any) and start a fresh one
    bound to the current _transcriber + _config."""
    global _dictation
    if _dictation:
        _dictation.stop()
    if _transcriber is None:
        return
    _dictation = _make_dictation(_transcriber)
    _dictation.start()


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


_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "freewispr-swedish"


def _open_run_key(write: bool = False):
    """Return an open HKCU\\...\\Run registry key. Caller must CloseKey."""
    import winreg
    access = winreg.KEY_SET_VALUE if write else winreg.KEY_READ
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, access)


def _is_startup_enabled() -> bool:
    import winreg
    try:
        key = _open_run_key(write=False)
        try:
            winreg.QueryValueEx(key, _RUN_VALUE)
        finally:
            winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _toggle_startup(_=None):
    import winreg
    key = _open_run_key(write=True)
    try:
        if _is_startup_enabled():
            winreg.DeleteValue(key, _RUN_VALUE)
            _set_tray_status("Borttagen från uppstart")
        else:
            winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, _startup_exe_path())
            _set_tray_status("Startar med Windows ✓")
    finally:
        winreg.CloseKey(key)
    _rebuild_menu()


def _rebuild_menu():
    if _tray_icon:
        _tray_icon.menu = _build_menu()


def _flow_active() -> bool:
    return bool(_flow and _flow.active)


def _toggle_flow(_=None):
    """AP6: start/stop continuous Flow-läge (local transcription only)."""
    global _flow
    if not _config.get("flow_mode_enabled", False):
        return
    if _transcriber is None:
        _set_tray_status("Flow-läge: modellen laddas fortfarande")
        return
    try:
        if _flow is None:
            from flow import FlowMode
            _flow = FlowMode(
                _transcriber,
                mic_device=_config.get("mic_device"),
                on_status=_set_tray_status,
                indicator=_indicator,
                min_rms=float(_config.get("min_rms", 0.003)),
            )
        # Flow and push-to-talk shouldn't fight over the mic — pause dictation
        # while Flow runs.
        if not _flow.active and _dictation is not None:
            _dictation.stop(wait=False)
        _flow.toggle()
        if not _flow.active and _dictation is not None:
            _dictation.start()
    except Exception as e:
        log.error("Flow-läge fel: %s", e, exc_info=True)
    _rebuild_menu()


def _dictation_paused() -> bool:
    return bool(_dictation is not None and _dictation.is_paused())


def _toggle_pause(_=None):
    """AP7.3: pause/resume dictation from the tray."""
    if _dictation is None:
        return
    paused = not _dictation.is_paused()
    _dictation.set_paused(paused)
    _set_tray_status("Diktering pausad" if paused
                     else f"Klar — håll {_config.get('hotkey','ctrl+space').upper()}")
    if _indicator:
        if paused:
            _indicator.show("Pausad", state="error")
            _indicator.hide(delay_ms=1500)
    _rebuild_menu()


def _undo_last(_=None):
    """AP7.7: erase the last pasted block."""
    if _dictation is not None:
        _dictation.undo_last()


def _build_menu():
    startup_label = "✓ Starta med Windows" if _is_startup_enabled() else "Starta med Windows"
    items = [
        # default=True makes this the action that runs on left double-click
        # of the tray icon (in addition to being the bold first menu entry).
        pystray.MenuItem("Inställningar", _open_settings, default=True),
    ]
    if _pending_update is not None:
        items.append(pystray.MenuItem(
            f"Uppdatering tillgänglig (v{_pending_update.version})",
            _open_release_page,
        ))
    items.append(pystray.MenuItem(startup_label, _toggle_startup))
    if _dictation is not None:
        pause_label = "Återuppta diktering" if _dictation_paused() else "Pausa diktering"
        items.append(pystray.MenuItem(pause_label, _toggle_pause))
        items.append(pystray.MenuItem("Ångra senaste", _undo_last))
    if _config.get("flow_mode_enabled", False):
        flow_label = "✓ Flow-läge" if _flow_active() else "Flow-läge"
        items.append(pystray.MenuItem(flow_label, _toggle_flow))
    items += [
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Sök efter uppdateringar", _manual_update_check),
        pystray.MenuItem("Avsluta freewispr-swedish", _quit),
    ]
    return pystray.Menu(*items)


# --------------------------------------------------------------------------- #
#  Update-check (GitHub Releases)                                              #
# --------------------------------------------------------------------------- #

def _open_release_page(_=None):
    """Öppna release-sidan för den väntande uppdateringen i webbläsaren."""
    if _pending_update is None:
        return
    import webbrowser
    try:
        webbrowser.open(_pending_update.url)
    except Exception as e:
        log.warning("Kunde inte öppna release-sida: %s", e)


def _show_update_toast():
    """Visa Windows-toast om en uppdatering finns. Körs på Tk-tråden."""
    if _pending_update is None or _tray_icon is None:
        return
    try:
        _tray_icon.notify(
            f"Ny version v{_pending_update.version} finns att hämta",
            "freewispr-swedish — uppdatering",
        )
    except Exception as e:
        # Äldre Windows / saknad notification-stöd — menyposten räcker.
        log.debug("Kunde inte visa update-toast: %s", e)


def _check_updates_bg(force: bool = False):
    """Kör update-check i bakgrunden. Krascher sväljs — check får aldrig
    påverka appens funktion."""
    global _pending_update
    try:
        from updater import check_for_update
        info = check_for_update(__version__, force=force)
        if info is not None:
            _pending_update = info
            log.info("Uppdatering hittad: v%s (%s)", info.version, info.url)
            if _tk_root is not None:
                _tk_root.after(0, _show_update_toast)
                _tk_root.after(0, _rebuild_menu)
        elif force:
            # Manuell check — ge alltid återkoppling.
            if _tray_icon is not None:
                try:
                    _tray_icon.notify(
                        f"Du har senaste versionen (v{__version__})",
                        "freewispr-swedish",
                    )
                except Exception:
                    pass
    except Exception as e:
        log.debug("Update-check misslyckades: %s", e)


def _manual_update_check(_=None):
    """Tray-menyns 'Sök efter uppdateringar'-knapp."""
    threading.Thread(
        target=lambda: _check_updates_bg(force=True),
        name="update-check-manual",
        daemon=True,
    ).start()


def _quit(_=None):
    """Tray-menyns 'Avsluta'. Körs på pystray-daemontråden.

    Tk-teardown (quit/destroy) måste ske på tråden som äger mainloop:en, så
    den faktiska nedstängningen marshallas dit. Att anropa quit()/destroy()
    cross-thread kan hänga eller kasta Tcl-fel, och sys.exit() i en daemon-
    tråd avslutar inte processen. Single-instance-låset släpps allra sist
    (i _final_cleanup efter mainloop) så att en omstart inte kan krocka med
    den döende processen medan den fortfarande äger hooks/VRAM.
    """
    root = _tk_root
    if root is not None and threading.current_thread() is not threading.main_thread():
        try:
            root.after(0, _shutdown)
            return
        except Exception:
            pass
    _shutdown()


def _shutdown():
    # Tear down everything that owns OS resources — keyboard hooks, audio
    # streams, VRAM, tray — before stopping the event loop.
    if _flow:
        try:
            _flow.stop(wait=False)
        except Exception:
            pass
    if _dictation:
        try:
            _dictation.stop()
        except Exception:
            pass
    if _indicator:
        try:
            _indicator.close()
        except Exception:
            log.debug("Kunde inte stänga indikatorn rent", exc_info=True)
    if _transcriber:
        try:
            _transcriber.close()
        except Exception:
            pass
    if _tray_icon:
        try:
            _tray_icon.stop()
        except Exception:
            pass
    # End the mainloop; final teardown (destroy + lock release) runs in main()
    # once mainloop() returns. If no loop is running, finish up inline.
    if _tk_root is not None:
        try:
            _tk_root.quit()
            return
        except Exception:
            pass
    _final_cleanup()


def _final_cleanup():
    """Last teardown step — runs on the main thread after mainloop() exits."""
    if _tk_root is not None:
        try:
            _tk_root.destroy()
        except Exception:
            pass
    # Release the single-instance lock LAST, after hooks/VRAM/tray are gone.
    try:
        import single_instance
        single_instance.release()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
#  Main                                                                        #
# --------------------------------------------------------------------------- #

def _notify_already_running() -> None:
    """Pop a modal 'already running' dialog (best-effort, Windows-only).

    Extracted so tests can stub it: the underlying ``MessageBoxW`` is a
    *blocking* modal that would hang a headless test run on Windows, while
    silently no-op'ing on platforms without ``ctypes.windll``.
    """
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, "freewispr-swedish körs redan.", "freewispr-swedish", 0x40)
    except Exception:
        pass


def main():
    global _tray_icon, _tk_root, _status_var, _indicator

    mp.freeze_support()

    # AP7.1: single-instance guard. A second instance would register duplicate
    # hotkeys and load a second Whisper model into VRAM (OOM). Bail out early —
    # before logging/tray/model — if another instance already holds the lock.
    import single_instance
    if not single_instance.acquire():
        log.warning("freewispr-swedish körs redan — avslutar denna instans")
        _notify_already_running()
        return

    # Wire up file logging now (deferred from import time so tests can import
    # this module without touching ~/.freewispr-swedish/).
    _attach_file_logging()

    # Hidden tk root — keeps tkinter event loop running for Toplevel windows
    _tk_root = tk.Tk()
    _tk_root.withdraw()
    _style(_tk_root)
    # Set the process-wide default icon now so any Toplevel that doesn't
    # explicitly decorate itself still picks up the freewispr brand.
    from ui.styles import apply_root_icon
    apply_root_icon(_tk_root)

    _status_var = tk.StringVar(value="Startar...")
    _indicator = FloatingIndicator(_tk_root, follow_mouse=True)

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

    # Check for updates in the background. Runs once at startup; never blocks
    # the UI and never raises into the main thread. Skipped automatically when
    # not running as a frozen PyInstaller exe (dev script mode).
    threading.Thread(
        target=_check_updates_bg,
        name="update-check",
        daemon=True,
    ).start()

    # Run tray in a background thread; tkinter runs on main thread
    tray_thread = threading.Thread(target=_tray_icon.run, daemon=True)
    tray_thread.start()

    # tkinter main loop (needed for Toplevel windows + FloatingIndicator)
    _tk_root.mainloop()
    # mainloop() returns when _shutdown() calls _tk_root.quit(); finish the
    # teardown (window destroy + release the single-instance lock last) here
    # on the main thread. All other threads are daemons and die with us.
    _final_cleanup()


if __name__ == "__main__":
    main()
