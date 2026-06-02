import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def reload_with_home(module_name: str, tmp_path: Path):
    module = importlib.import_module(module_name)
    from json_store import JsonCache
    module._store = JsonCache(tmp_path / f"{module_name}.json", default={})
    return module


@pytest.fixture
def fake_transcriber_deps(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=object),
    )


def test_transcriber_postprocess_cleans_common_artifacts(fake_transcriber_deps):
    transcriber = importlib.import_module("transcriber")

    result = transcriber._postprocess("  , hej  hej ,du!!!  ")

    assert result == "Hej, du!"


def test_config_save_uses_keyring_and_excludes_secret(tmp_path, monkeypatch):
    config = importlib.reload(importlib.import_module("config"))
    secrets = {}

    config.CONFIG_DIR = tmp_path
    config.CONFIG_FILE = tmp_path / "config.json"
    config.keyring = SimpleNamespace(
        get_password=lambda service, username: secrets.get((service, username)),
        set_password=lambda service, username, value: secrets.__setitem__((service, username), value),
        delete_password=lambda service, username: secrets.pop((service, username), None),
    )

    config.save({
        **config.DEFAULTS,
        "llm_api_key_github": "secret-token",
        "model_size": "tiny",
    })

    saved = json.loads(config.CONFIG_FILE.read_text(encoding="utf-8"))
    loaded = config.load()

    # Inga av nyckelfälten får ligga på disk.
    for provider in ("github", "staik", "berget", "openai", "custom"):
        assert f"llm_api_key_{provider}" not in saved
    assert "llm_api_key" not in saved  # legacy
    assert loaded["llm_api_key_github"] == "secret-token"
    assert loaded["llm_api_key_staik"] == ""
    assert loaded["model_size"] == "tiny"


def test_config_load_migrates_legacy_secret_off_disk(tmp_path):
    config = importlib.reload(importlib.import_module("config"))
    secrets = {}

    config.CONFIG_DIR = tmp_path
    config.CONFIG_FILE = tmp_path / "config.json"
    # Gammal config: legacy fältnamn på disk + legacy nyckel i keyring.
    config.CONFIG_FILE.write_text(
        json.dumps({"model_size": "base", "llm_model": "openai/gpt-4.1"}),
        encoding="utf-8",
    )
    secrets[(config._KEYRING_SERVICE, config._LEGACY_KEYRING_USERNAME)] = "legacy-secret"
    config.keyring = SimpleNamespace(
        get_password=lambda service, username: secrets.get((service, username)),
        set_password=lambda service, username, value: secrets.__setitem__((service, username), value),
        delete_password=lambda service, username: secrets.pop((service, username), None),
    )

    loaded = config.load()
    saved = json.loads(config.CONFIG_FILE.read_text(encoding="utf-8"))

    # Legacy-nyckeln har migrerats till github-entryt.
    assert loaded["llm_api_key_github"] == "legacy-secret"
    assert (config._KEYRING_SERVICE, config._keyring_user("github")) in secrets
    assert (config._KEYRING_SERVICE, config._LEGACY_KEYRING_USERNAME) not in secrets
    # llm_model migrerat till llm_model_github.
    assert loaded["llm_model_github"] == "openai/gpt-4.1"
    assert "llm_api_key" not in saved
    assert "llm_model" not in saved
    assert saved["model_size"] == "base"


def test_llm_polish_falls_back_without_logging_body(monkeypatch, caplog):
    llm_polish = importlib.import_module("llm_polish")

    def raise_http_error(*args, **kwargs):
        raise llm_polish.urllib.error.HTTPError(
            url="https://example.test",
            code=400,
            msg="bad request",
            hdrs=None,
            fp=SimpleNamespace(read=lambda: b"echoed sensitive text"),
        )

    monkeypatch.setattr(llm_polish, "_call_api", raise_http_error)

    with caplog.at_level("WARNING"):
        result = llm_polish.polish("hemlig text", "token")

    assert result.text == "hemlig text"
    assert not result.changed
    assert "hemlig text" not in caplog.text


def test_llm_polish_resolves_github_token_from_environment(monkeypatch):
    llm_polish = importlib.import_module("llm_polish")
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    monkeypatch.delenv("GH_TOKEN", raising=False)

    assert llm_polish.resolve_api_key("") == "env-token"
    assert llm_polish.resolve_api_key("explicit-token") == "explicit-token"


def test_llm_polish_resolves_github_token_from_gh_cli(monkeypatch):
    llm_polish = importlib.import_module("llm_polish")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    def fake_run(*args, **kwargs):
        assert args[0] == ["gh", "auth", "token"]
        return SimpleNamespace(returncode=0, stdout="gh-token\n")

    monkeypatch.setattr(llm_polish.subprocess, "run", fake_run)
    assert llm_polish.resolve_api_key("") == "gh-token"


# --------------------------------------------------------------------------- #
#  New regression tests for refactors landed in this round.
# --------------------------------------------------------------------------- #

def test_dictation_parse_hotkey_splits_modifiers_and_trigger():
    """_parse_hotkey must return ("space", ("ctrl", "shift")) for chorded hotkeys."""
    dictation = importlib.import_module("dictation")

    trigger, modifiers = dictation._parse_hotkey("ctrl+shift+space")
    assert trigger == "space"
    assert set(modifiers) == {"ctrl", "shift"}

    trigger, modifiers = dictation._parse_hotkey("f9")
    assert trigger == "f9"
    assert modifiers == ()


# --------------------------------------------------------------------------- #
#  Fas 1: modifier normalisation + dictation off-hook pipeline regression.
# --------------------------------------------------------------------------- #

def test_modifiers_normalize_aliases():
    """All aliases for the Windows key must collapse to 'windows'."""
    modifiers = importlib.import_module("modifiers")
    assert modifiers.normalize("win") == "windows"
    assert modifiers.normalize("Cmd") == "windows"
    assert modifiers.normalize("SUPER") == "windows"
    assert modifiers.normalize("control") == "ctrl"
    assert modifiers.normalize("ctrl") == "ctrl"
    assert modifiers.normalize("nonsense") is None
    assert modifiers.normalize("") is None


def test_modifiers_normalize_all_dedupes_and_preserves_order():
    modifiers = importlib.import_module("modifiers")
    result = modifiers.normalize_all(["Ctrl", "shift", "control", "win", "cmd"])
    # ctrl/control collapse; win/cmd collapse to windows.
    assert result == ("ctrl", "shift", "windows")


def test_modifiers_is_modifier():
    modifiers = importlib.import_module("modifiers")
    assert modifiers.is_modifier("alt")
    assert modifiers.is_modifier("CMD")
    assert not modifiers.is_modifier("space")


def test_dictation_parse_hotkey_normalises_cmd_to_windows():
    """A hotkey with 'cmd' must yield canonical 'windows' so paste releases it."""
    dictation = importlib.import_module("dictation")

    trigger, modifiers = dictation._parse_hotkey("cmd+shift+space")
    assert trigger == "space"
    # 'cmd' must be normalised to 'windows' so paste._release_modifiers
    # actually releases the held Win key after Ctrl+V.
    assert set(modifiers) == {"windows", "shift"}


def test_audio_finalize_handles_empty_input():
    """finalize_audio must gracefully return an empty array for zero input."""
    import numpy as np
    audio = importlib.import_module("audio")
    result = audio.finalize_audio(np.empty(0, dtype=np.float32), 1, 16000)
    assert result.shape == (0,)
    assert result.dtype.name == "float32"


def test_audio_finalize_selects_loudest_stereo_channel():
    """Multi-channel input must preserve signal even if it is not on channel 0."""
    import numpy as np
    audio = importlib.import_module("audio")
    # Stereo buffer: left channel silent, right channel contains the mic.
    stereo = np.array([[0.0, 1.0], [0.0, 1.0], [0.0, 1.0], [0.0, 1.0]],
                      dtype=np.float32)
    result = audio.finalize_audio(stereo, 2, audio.TARGET_RATE)
    assert result.shape == (4,)
    assert np.allclose(result, 1.0)


def test_audio_finalize_averages_balanced_stereo_channels():
    import numpy as np
    audio = importlib.import_module("audio")
    stereo = np.array([[1.0, 0.5], [1.0, 0.5]], dtype=np.float32)

    result = audio.finalize_audio(stereo, 2, audio.TARGET_RATE)

    assert np.allclose(result, 0.75)


def test_audio_callback_rms_uses_loudest_channel(monkeypatch):
    """Silence gate RMS must not miss a mic signal on the right channel."""
    import numpy as np
    audio = importlib.import_module("audio")

    recorder = audio.MicRecorder()
    recorder._ensure_buffer(audio.TARGET_RATE, 2)
    recorder.recording = True
    indata = np.array([[0.0, 0.5], [0.0, 0.5]], dtype=np.float32)

    recorder._cb(indata, len(indata), None, None)

    assert recorder.level == pytest.approx(0.5)
    assert recorder.rms() == pytest.approx(0.5)


def test_indicator_push_level_throttles_redraws(monkeypatch):
    """push_level must coalesce rapid audio-thread calls into ≤1 pending
    Tk redraw — otherwise a 50 Hz audio callback floods after()."""
    # Stub out tkinter — we only need the FloatingIndicator class itself,
    # not a real Tk root.
    import sys as _sys
    fake_tk = type(_sys)("tkinter")
    fake_tk.Tk = object
    fake_tk.Toplevel = object
    fake_tk.Label = object
    fake_tk.Canvas = object
    fake_tk.Frame = object
    fake_tk.BooleanVar = object
    fake_tk.StringVar = object
    fake_tk.Button = object
    fake_tk.Entry = object
    fake_ttk = type(_sys)("tkinter.ttk")
    fake_ttk.Style = object
    fake_ttk.Combobox = object
    fake_ttk.Treeview = object
    fake_ttk.Scrollbar = object
    fake_messagebox = type(_sys)("tkinter.messagebox")
    fake_messagebox.showerror = lambda *a, **k: None
    fake_messagebox.askokcancel = lambda *a, **k: True
    fake_tk.ttk = fake_ttk
    fake_tk.messagebox = fake_messagebox
    monkeypatch.setitem(_sys.modules, "tkinter", fake_tk)
    monkeypatch.setitem(_sys.modules, "tkinter.ttk", fake_ttk)
    monkeypatch.setitem(_sys.modules, "tkinter.messagebox", fake_messagebox)

    ui = importlib.reload(importlib.import_module("ui"))

    scheduled: list = []

    class FakeRoot:
        def after(self, delay, fn=None, *args):
            scheduled.append((delay, fn, args))
            return 1
        def after_cancel(self, _id):
            pass

    ind = ui.FloatingIndicator(FakeRoot())
    # Simulate a shown listen window without invoking real Tk.
    ind._win = object()
    ind._canvas = object()
    ind._state = "listen"

    # 50 rapid pushes should result in exactly one scheduled redraw
    # (subsequent ones coalesce while _pending_push is True).
    for _ in range(50):
        ind.push_level(0.2)
    assert len(scheduled) == 1


def test_main_apply_settings_serialised(monkeypatch):
    """_apply_settings must acquire _config_lock before delegating, so
    two concurrent Save clicks can't interleave config mutations."""
    import threading as _th

    pytest.importorskip("PIL")
    pytest.importorskip("pystray")
    # main imports tkinter at module load; without it reload(main) raises
    # ModuleNotFoundError. Gate on tkinter too so this skips cleanly on any
    # environment missing the full GUI stack (matches test_ap7_robustness).
    pytest.importorskip("tkinter")
    main = importlib.reload(importlib.import_module("main"))

    assert isinstance(main._config_lock, type(_th.Lock()))

    holds = []

    def tracer(cfg):
        holds.append(main._config_lock.locked())
        return True

    monkeypatch.setattr(main, "_apply_settings_locked", tracer)
    main._apply_settings({"hotkey": "ctrl+space"})
    assert holds == [True]


def test_apply_window_icon_lazily_loads_taskbar_photo(monkeypatch, tmp_path):
    """Settings can be created outside the root-icon path; the visible
    Toplevel still needs iconphoto(), otherwise Windows shows Python in
    the taskbar."""
    styles = importlib.reload(importlib.import_module("ui.styles"))
    icon_path = tmp_path / "assets" / "icon.ico"
    icon_path.parent.mkdir()
    icon_path.write_bytes(b"fake icon; loader is mocked")
    calls = []

    class FakeWindow:
        def iconbitmap(self, path):
            calls.append(("bitmap", path))

        def iconphoto(self, default, photo):
            calls.append(("photo", default, photo))

        def after(self, delay, fn):
            calls.append(("after", delay, fn))

    monkeypatch.setattr(styles, "_resolve_icon_path", lambda: icon_path)
    monkeypatch.setattr(styles, "_load_largest_ico_frame_as_photo", lambda root: "photo")
    styles._root_photo = None

    styles.apply_window_icon(FakeWindow())

    assert ("bitmap", str(icon_path)) in calls
    assert ("photo", False, "photo") in calls
    delayed = [call for call in calls if call[0] == "after"]
    assert len(delayed) == 1
    assert delayed[0][1] == 500

    calls.clear()
    delayed[0][2]()
    assert ("bitmap", str(icon_path)) in calls
    assert ("photo", False, "photo") in calls


def test_pyinstaller_build_bundles_icon_for_tk_taskbar():
    """--icon brands the exe, but Tk taskbar icons need icon.ico available
    as runtime data under assets/ too."""
    repo = Path(__file__).resolve().parents[1]
    build_bat = (repo / "build.bat").read_text(encoding="utf-8")
    workflow = (repo / ".github" / "workflows" / "build-windows.yml").read_text(encoding="utf-8")

    assert '--add-data "assets/icon.ico;assets"' in build_bat
    assert '--add-data "assets/icon.ico;assets"' in workflow

    # freewispr-swedish.spec is a machine-specific PyInstaller artifact and is
    # gitignored (*.spec), so it is absent on CI. Only assert on it when a local
    # spec exists.
    spec_path = repo / "freewispr-swedish.spec"
    if not spec_path.exists():
        pytest.skip("freewispr-swedish.spec is gitignored and absent (CI/build artifact)")
    spec = spec_path.read_text(encoding="utf-8")
    assert "('assets/icon.ico', 'assets')" in spec


def test_config_load_keeps_legacy_secret_when_keyring_migration_fails(tmp_path):
    config = importlib.reload(importlib.import_module("config"))
    config.CONFIG_DIR = tmp_path
    config.CONFIG_FILE = tmp_path / "config.json"
    config.CONFIG_FILE.write_text(
        json.dumps({"model_size": "base"}),
        encoding="utf-8",
    )
    # set_password kraschar -> migrering till per-provider entry misslyckas.
    config.keyring = SimpleNamespace(
        get_password=lambda service, username: (
            "legacy-secret" if username == config._LEGACY_KEYRING_USERNAME else None
        ),
        set_password=lambda service, username, value: (_ for _ in ()).throw(RuntimeError("no backend")),
        delete_password=lambda service, username: None,
    )

    loaded = config.load()
    saved = json.loads(config.CONFIG_FILE.read_text(encoding="utf-8"))

    # Migrering misslyckades -> nyckeln finns inte i någon provider-slot, men
    # appen ska inte krascha och inte heller skriva nyckeln till disk.
    assert loaded["llm_api_key_github"] == ""
    assert "llm_api_key" not in saved


def test_config_save_restores_secret_if_json_write_fails(tmp_path, monkeypatch):
    config = importlib.reload(importlib.import_module("config"))
    secrets = {(config._KEYRING_SERVICE, config._keyring_user("github")): "old-secret"}
    config.CONFIG_DIR = tmp_path
    config.CONFIG_FILE = tmp_path / "config.json"
    config.keyring = SimpleNamespace(
        get_password=lambda service, username: secrets.get((service, username)),
        set_password=lambda service, username, value: secrets.__setitem__((service, username), value),
        delete_password=lambda service, username: secrets.pop((service, username), None),
    )
    monkeypatch.setattr(config, "save_json_atomic",
                        lambda path, data: (_ for _ in ()).throw(RuntimeError("disk full")))

    with pytest.raises(RuntimeError):
        config.save({**config.DEFAULTS, "llm_api_key_github": "new-secret"})

    assert secrets[(config._KEYRING_SERVICE, config._keyring_user("github"))] == "old-secret"


def test_config_save_fails_if_secret_delete_fails(tmp_path):
    config = importlib.reload(importlib.import_module("config"))
    secrets = {(config._KEYRING_SERVICE, config._keyring_user("github")): "old-secret"}
    config.CONFIG_DIR = tmp_path
    config.CONFIG_FILE = tmp_path / "config.json"

    def delete_fail(service, username):
        raise RuntimeError("delete failed")

    config.keyring = SimpleNamespace(
        get_password=lambda service, username: secrets.get((service, username)),
        set_password=lambda service, username, value: secrets.__setitem__((service, username), value),
        delete_password=delete_fail,
    )

    with pytest.raises(RuntimeError):
        # Sätter github-nyckeln till tom -> försöker delete -> failar.
        config.save({**config.DEFAULTS, "llm_api_key_github": ""})

    assert secrets[(config._KEYRING_SERVICE, config._keyring_user("github"))] == "old-secret"


def test_llm_only_save_failure_restores_transcriber_state(monkeypatch):
    pytest.importorskip("PIL")
    pytest.importorskip("pystray")
    pytest.importorskip("tkinter")
    main = importlib.reload(importlib.import_module("main"))
    old_state = {
        "hotkey": "ctrl+space",
        "model_size": "small",
        "use_cuda": False,
        "llm_enabled": False,
        "llm_privacy_accepted": False,
        "llm_provider": "github",
        "llm_api_key_github": "old-key",
        "llm_model_github": "old-model",
        "transcription_provider": "local",
    }
    main._config = old_state.copy()
    main._transcriber = SimpleNamespace(
        llm_enabled=False,
        llm_provider="github",
        llm_api_key="old-key",
        llm_model="old-model",
        llm_base_url="",
        transcription_provider="local",
        transcription_api_key="",
        transcription_model="",
        transcription_base_url="",
    )
    restarted = []
    monkeypatch.setattr(main, "_restart_dictation", lambda: restarted.append(True))
    monkeypatch.setattr(main.cfg_module, "save",
                        lambda cfg: (_ for _ in ()).throw(RuntimeError("disk full")))

    result = main._apply_settings({
        "llm_enabled": True,
        "llm_privacy_accepted": True,
        "llm_provider": "github",
        "llm_api_key_github": "new-key",
        "llm_model_github": "new-model",
    })

    assert result is False
    assert main._config == old_state
    assert main._transcriber.llm_enabled is False
    assert main._transcriber.llm_api_key == "old-key"
    assert main._transcriber.llm_model == "old-model"
    assert len(restarted) >= 2


def test_paste_text_serializes_clipboard_workers(monkeypatch):
    paste = importlib.reload(importlib.import_module("paste"))
    events = []
    clipboard = {"value": "orig"}

    def fake_copy(value):
        events.append(("copy", value))
        clipboard["value"] = value

    monkeypatch.setattr(paste.pyperclip, "copy", fake_copy)
    monkeypatch.setattr(paste.keyboard, "send", lambda key: events.append(("send", key)))
    monkeypatch.setattr(paste, "_active_window_class", lambda: "NotConsole")
    monkeypatch.setattr(paste, "_release_modifiers", lambda mods=(): None)
    monkeypatch.setattr(paste, "_paste_and_keep_clipboard_async",
                        lambda text, replace_len=0: paste._paste_and_keep_clipboard(text, replace_len))

    paste.paste_text("first")
    paste.paste_text("second")

    assert events == [
        ("copy", "first "), ("send", "ctrl+v"),
        ("copy", "second "), ("send", "ctrl+v"),
    ]
    assert clipboard["value"] == "second "


def test_paste_text_uses_shift_insert_for_console_windows(monkeypatch):
    paste = importlib.reload(importlib.import_module("paste"))
    sent = []
    monkeypatch.setattr(paste, "_active_window_class", lambda: "ConsoleWindowClass")
    monkeypatch.setattr(paste.pyperclip, "copy", lambda value: None)
    monkeypatch.setattr(paste.keyboard, "send", lambda key: sent.append(key))
    monkeypatch.setattr(paste, "_release_modifiers", lambda mods=(): None)
    monkeypatch.setattr(paste, "_paste_and_keep_clipboard_async",
                        lambda text, replace_len=0: paste._paste_and_keep_clipboard(text, replace_len))

    paste.paste_text("hej")

    assert sent == ["shift+insert"]


def test_dictation_worker_does_not_paste_after_stop(monkeypatch):
    import numpy as np
    dictation = importlib.reload(importlib.import_module("dictation"))

    pasted = []
    mode = object.__new__(dictation.DictationMode)
    mode.transcriber = SimpleNamespace(transcribe=lambda audio, **kw: "stale text")
    mode._worker_stop = __import__("threading").Event()
    mode._worker_stop.set()
    mode._active = False
    mode._modifier_keys = ()
    mode.hotkey = "ctrl+space"
    mode.indicator = None
    mode.on_status = lambda msg: None
    monkeypatch.setattr(dictation, "paste_text", lambda text, active_modifiers=(): pasted.append(text))

    mode._transcribe(np.ones(16000, dtype=np.float32))

    assert pasted == []


def test_dictation_wait_mode_pastes_polished_not_raw(monkeypatch):
    """When LLM is enabled, raw transcript must NOT be pasted before polish.

    Only the polished text reaches the clipboard, and only once.
    """
    import numpy as np
    import threading
    dictation = importlib.reload(importlib.import_module("dictation"))

    pasted = []

    def fake_polish_async(text, callback, on_stage=None, **kw):
        # Simulate the LLM thread: deliver polished text after a tiny delay.
        def _run():
            callback(text, "POLERAD: " + text)
        threading.Thread(target=_run, daemon=True).start()

    mode = object.__new__(dictation.DictationMode)
    mode.transcriber = SimpleNamespace(
        transcribe=lambda audio, **kw: "ra text",
        polish_async=fake_polish_async,
        last_polish_state="llm_changed",
        llm_enabled=True,
    )
    mode._worker_stop = threading.Event()
    mode._active = True
    mode._modifier_keys = ()
    mode.hotkey = "ctrl+space"
    mode.indicator = None
    mode.on_status = lambda msg: None
    mode.llm_enabled = True
    mode.polish_skip_trivial = False
    monkeypatch.setattr(dictation, "paste_text",
                        lambda text, active_modifiers=(): pasted.append(text))

    mode._transcribe(np.ones(16000, dtype=np.float32))

    # Wait for the background polish callback to fire.
    import time
    for _ in range(50):
        if pasted:
            break
        time.sleep(0.02)

    assert pasted == ["POLERAD: ra text"], \
        f"Expected single polished paste, got: {pasted}"


def test_dictation_wait_mode_watchdog_pastes_raw_on_timeout(monkeypatch):
    """If polish_async never calls back, watchdog must paste the raw text."""
    import numpy as np
    import threading
    dictation = importlib.reload(importlib.import_module("dictation"))

    pasted = []

    def fake_polish_async_hang(text, callback, on_stage=None, **kw):
        # Never calls back — simulating a hung LLM endpoint.
        pass

    mode = object.__new__(dictation.DictationMode)
    mode.transcriber = SimpleNamespace(
        transcribe=lambda audio, **kw: "ra text",
        polish_async=fake_polish_async_hang,
        last_polish_state="local",
        llm_enabled=True,
    )
    mode._worker_stop = threading.Event()
    mode._active = True
    mode._modifier_keys = ()
    mode.hotkey = "ctrl+space"
    mode.indicator = None
    mode.on_status = lambda msg: None
    mode.llm_enabled = True
    mode.polish_skip_trivial = False
    monkeypatch.setattr(dictation, "paste_text",
                        lambda text, active_modifiers=(): pasted.append(text))
    # Shrink watchdog so the test doesn't wait 15 s.
    import threading as _threading_mod
    original_timer = _threading_mod.Timer
    monkeypatch.setattr(dictation.threading, "Timer",
                        lambda interval, fn: original_timer(0.05, fn))

    mode._transcribe(np.ones(16000, dtype=np.float32))

    import time
    for _ in range(50):
        if pasted:
            break
        time.sleep(0.02)

    assert pasted == ["ra text"], \
        f"Expected raw fallback paste after watchdog, got: {pasted}"


def test_dictation_no_llm_mode_pastes_raw_immediately(monkeypatch):
    """LLM disabled = fast path: paste raw text exactly once, no polish call."""
    import numpy as np
    import threading
    dictation = importlib.reload(importlib.import_module("dictation"))

    pasted = []
    polish_called = []

    mode = object.__new__(dictation.DictationMode)
    mode.transcriber = SimpleNamespace(
        transcribe=lambda audio, **kw: "ra text",
        polish_async=lambda *a, **kw: polish_called.append(True),
    )
    mode._worker_stop = threading.Event()
    mode._active = True
    mode._modifier_keys = ()
    mode.hotkey = "ctrl+space"
    mode.indicator = None
    mode.on_status = lambda msg: None
    mode.llm_enabled = False
    monkeypatch.setattr(dictation, "paste_text",
                        lambda text, active_modifiers=(): pasted.append(text))

    mode._transcribe(np.ones(16000, dtype=np.float32))

    assert pasted == ["ra text"]
    assert polish_called == []  # polish_async must NOT be called when LLM off


def test_transcriber_close_waits_for_inflight_transcribe(fake_transcriber_deps):
    import numpy as np
    import threading
    sys.modules["torch"] = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: False, empty_cache=lambda: None)
    )
    transcriber = importlib.reload(importlib.import_module("transcriber"))

    entered = threading.Event()
    release = threading.Event()

    class FakeModel:
        def __init__(self):
            self.in_transcribe = False
            self.closed_during_transcribe = False
        def transcribe(self, *args, **kwargs):
            def segments():
                self.in_transcribe = True
                entered.set()
                try:
                    # close() must not set owner.model to None while this generator runs.
                    release.wait(timeout=2.0)
                    yield SimpleNamespace(text="hej")
                finally:
                    self.in_transcribe = False
            return segments(), SimpleNamespace()

    inst = object.__new__(transcriber.Transcriber)
    inst.model_size = "small"
    inst.language = "sv"
    inst.llm_enabled = False
    inst.llm_api_key = ""
    inst.llm_model = "gpt-4.1-nano"
    inst.llm_provider = "github"
    inst.llm_base_url = ""
    inst.transcription_provider = "local"
    inst.transcription_api_key = ""
    inst.transcription_model = ""
    inst.transcription_base_url = ""
    inst.model = FakeModel()
    inst._model_lock = __import__("threading").RLock()
    original_model = inst.model

    result_holder = {}
    transcribe_thread = threading.Thread(
        target=lambda: result_holder.setdefault(
            "result", inst.transcribe(np.ones(16000, dtype=np.float32))
        )
    )
    transcribe_thread.start()
    assert entered.wait(timeout=1.0)

    close_done = threading.Event()
    close_thread = threading.Thread(target=lambda: (inst.close(), close_done.set()))
    close_thread.start()

    assert not close_done.wait(timeout=0.05)
    release.set()
    transcribe_thread.join(timeout=1.0)
    close_thread.join(timeout=1.0)

    assert result_holder["result"] == "Hej"
    assert close_done.is_set()
    assert inst.model is None
    assert original_model.in_transcribe is False


def test_transcriber_transcribe_returns_local_text_without_llm(monkeypatch, fake_transcriber_deps):
    """transcribe() must return local/postprocessed text without running LLM polish."""
    import numpy as np
    transcriber = importlib.reload(importlib.import_module("transcriber"))

    class FakeModel:
        def transcribe(self, *args, **kwargs):
            return iter([SimpleNamespace(text="hej")]), SimpleNamespace()

    inst = object.__new__(transcriber.Transcriber)
    inst.model_size = "small"
    inst.language = "sv"
    inst.llm_enabled = True
    inst.llm_api_key = ""
    inst.llm_model = "gpt-4.1-nano"
    inst.llm_provider = "github"
    inst.llm_base_url = ""
    inst.transcription_provider = "local"
    inst.transcription_api_key = ""
    inst.transcription_model = ""
    inst.transcription_base_url = ""
    inst.model = FakeModel()
    inst._model_lock = __import__("threading").RLock()

    # transcribe() should return local text (no LLM polish)
    result = inst.transcribe(np.ones(16000, dtype=np.float32))
    assert result == "Hej"
    assert inst.last_polish_state == "local"


def test_transcriber_polish_async_calls_callback_with_polished_text(monkeypatch, fake_transcriber_deps):
    """polish_async() must run LLM polish in background and call the callback."""
    import threading
    transcriber = importlib.reload(importlib.import_module("transcriber"))

    inst = object.__new__(transcriber.Transcriber)
    inst.model_size = "small"
    inst.language = "sv"
    inst.llm_enabled = True
    inst.llm_api_key = ""
    inst.llm_model = "gpt-4.1-nano"
    inst.llm_provider = "github"
    inst.llm_base_url = ""
    inst.on_stage = None

    fake_llm = SimpleNamespace(
        polish=lambda text, key, model=None, provider=None, base_url_override=None, context_text=None, **kw: SimpleNamespace(
            text="hej!", changed=True, latency_ms=1
        )
    )
    monkeypatch.setitem(sys.modules, "llm_polish", fake_llm)

    results = []
    done = threading.Event()

    def cb(original, polished):
        results.append((original, polished))
        done.set()

    inst.polish_async("Hej", cb)
    assert done.wait(timeout=2.0), "polish_async callback was not called"
    assert results == [("Hej", "hej!")]
    assert inst.last_polish_state == "llm_changed"


def test_transcriber_polish_async_unchanged_text(monkeypatch, fake_transcriber_deps):
    """polish_async() callback receives (text, text) when LLM makes no changes."""
    import threading
    transcriber = importlib.reload(importlib.import_module("transcriber"))

    inst = object.__new__(transcriber.Transcriber)
    inst.model_size = "small"
    inst.language = "sv"
    inst.llm_enabled = True
    inst.llm_api_key = ""
    inst.llm_model = "gpt-4.1-nano"
    inst.llm_provider = "github"
    inst.llm_base_url = ""
    inst.on_stage = None

    fake_llm = SimpleNamespace(
        polish=lambda text, key, model=None, provider=None, base_url_override=None, context_text=None, **kw: SimpleNamespace(
            text="Hej", changed=False, latency_ms=1
        )
    )
    monkeypatch.setitem(sys.modules, "llm_polish", fake_llm)

    results = []
    done = threading.Event()

    def cb(original, polished):
        results.append((original, polished))
        done.set()

    inst.polish_async("Hej", cb)
    assert done.wait(timeout=2.0)
    assert results == [("Hej", "Hej")]
    assert inst.last_polish_state == "llm_unchanged"


def test_transcriber_polish_async_handles_exception(monkeypatch, fake_transcriber_deps):
    """polish_async() must call callback(text, text) if polish() raises."""
    import threading
    transcriber = importlib.reload(importlib.import_module("transcriber"))

    inst = object.__new__(transcriber.Transcriber)
    inst.model_size = "small"
    inst.language = "sv"
    inst.llm_enabled = True
    inst.llm_api_key = ""
    inst.llm_model = "gpt-4.1-nano"
    inst.llm_provider = "github"
    inst.llm_base_url = ""
    inst.on_stage = None

    def exploding_polish(*args, **kwargs):
        raise RuntimeError("network down")

    fake_llm = SimpleNamespace(polish=exploding_polish)
    monkeypatch.setitem(sys.modules, "llm_polish", fake_llm)

    results = []
    done = threading.Event()

    def cb(original, polished):
        results.append((original, polished))
        done.set()

    inst.polish_async("Hej", cb)
    assert done.wait(timeout=2.0)
    assert results == [("Hej", "Hej")]
    assert inst.last_polish_state == "local"


def test_polish_async_on_stage_parameter_isolates_overlapping_jobs(monkeypatch, fake_transcriber_deps):
    """Two overlapping polish_async jobs must not steal each other's on_stage callbacks.

    Regression for the race where dictation.py mutated self.transcriber.on_stage
    per job: job B's callback could be overwritten by job A's "restore old_stage"
    when A's polish finally completed.
    """
    import threading
    transcriber = importlib.reload(importlib.import_module("transcriber"))

    def _make_inst() -> object:
        inst = object.__new__(transcriber.Transcriber)
        inst.model_size = "small"
        inst.language = "sv"
        inst.llm_enabled = True
        inst.llm_api_key = ""
        inst.llm_model = "m"
        inst.llm_provider = "github"
        inst.llm_base_url = ""
        inst.on_stage = None
        return inst

    fake_llm = SimpleNamespace(
        polish=lambda text, key, model=None, provider=None, base_url_override=None, context_text=None, **kw: SimpleNamespace(
            text=text, changed=False, latency_ms=1
        )
    )
    monkeypatch.setitem(sys.modules, "llm_polish", fake_llm)

    inst = _make_inst()
    stages_a: list[str] = []
    stages_b: list[str] = []
    done_a = threading.Event()
    done_b = threading.Event()

    inst.polish_async("A", lambda o, p: done_a.set(),
                      on_stage=lambda s: stages_a.append(s))
    inst.polish_async("B", lambda o, p: done_b.set(),
                      on_stage=lambda s: stages_b.append(s))

    assert done_a.wait(timeout=2.0)
    assert done_b.wait(timeout=2.0)
    # Each job's on_stage must fire exactly once with "llm_reviewing"
    # and they must be independent — A's callback never receives B's stage.
    assert stages_a == ["llm_reviewing"], f"job A got: {stages_a}"
    assert stages_b == ["llm_reviewing"], f"job B got: {stages_b}"

