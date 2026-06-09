"""Shared test fixtures — stubs for native modules unavailable in CI."""
import importlib.util
import sys
from types import SimpleNamespace

# faster_whisper pulls in ctranslate2 (native) and is not installed in every
# dev environment. Several tests reload transcriber/dictation, which import it
# at module top — without a central stub those tests pass or fail depending on
# which test ran first (whoever left a per-test stub in sys.modules). Stub it
# here ONLY when the real package is missing, so CI/Windows (where it is
# installed) still exercises the real import path.
if "faster_whisper" not in sys.modules and importlib.util.find_spec("faster_whisper") is None:
    sys.modules["faster_whisper"] = SimpleNamespace(
        WhisperModel=object,
        BatchedInferencePipeline=object,
    )

# sounddevice requires PortAudio (C library) which is unavailable on Linux CI.
# Stub it before any test imports audio.py → sounddevice.
if "sounddevice" not in sys.modules:
    _sd = SimpleNamespace(
        query_devices=lambda: [],
        query_hostapis=lambda: [],
        InputStream=type("InputStream", (), {
            "__init__": lambda self, **kw: None,
            "start": lambda self: None,
            "stop": lambda self: None,
            "abort": lambda self: None,
            "close": lambda self: None,
        }),
    )
    sys.modules["sounddevice"] = _sd

# keyboard requires a low-level hook driver on Windows.
if "keyboard" not in sys.modules:
    sys.modules["keyboard"] = SimpleNamespace(
        parse_hotkey=lambda s: ((1,), (2,)),
        is_pressed=lambda key: False,
        add_hotkey=lambda *a, **kw: None,
        on_press_key=lambda *a, **kw: None,
        on_release_key=lambda *a, **kw: None,
        unhook=lambda h: None,
        send=lambda *a, **kw: None,
        release=lambda k: None,
    )

# pyperclip needs a clipboard backend (xclip/xsel on Linux).
if "pyperclip" not in sys.modules:
    _clipboard = {"value": ""}
    sys.modules["pyperclip"] = SimpleNamespace(
        copy=lambda text: _clipboard.__setitem__("value", text),
        paste=lambda: _clipboard["value"],
    )

# pystray is Windows-only.
if "pystray" not in sys.modules:
    sys.modules["pystray"] = SimpleNamespace(
        Icon=lambda *a, **kw: None,
        Menu=SimpleNamespace(SEPARATOR=None),
        MenuItem=lambda *a, **kw: None,
    )

# winsound is Windows-only.
if "winsound" not in sys.modules:
    sys.modules["winsound"] = SimpleNamespace(
        PlaySound=lambda *a, **kw: None,
        SND_MEMORY=0,
        SND_ASYNC=0,
    )

# AP3 context awareness deps are Windows-only. context_win imports them lazily
# inside try/except, so these stubs are only a safety net for tests that import
# them directly; individual tests monkeypatch return values as needed.
if "win32gui" not in sys.modules:
    sys.modules["win32gui"] = SimpleNamespace(
        GetForegroundWindow=lambda: 0,
        GetWindowText=lambda hwnd: "",
    )

if "win32process" not in sys.modules:
    sys.modules["win32process"] = SimpleNamespace(
        GetWindowThreadProcessId=lambda hwnd: (0, 0),
    )

if "psutil" not in sys.modules:
    sys.modules["psutil"] = SimpleNamespace(
        Process=lambda pid: SimpleNamespace(name=lambda: "python.exe"),
    )

if "uiautomation" not in sys.modules:
    sys.modules["uiautomation"] = SimpleNamespace(
        GetFocusedControl=lambda: None,
    )
