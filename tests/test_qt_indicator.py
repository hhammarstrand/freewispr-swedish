import json
import sys

import pytest


class FakeRoot:
    def __init__(self):
        self.after_calls = []

    def after(self, delay, fn=None, *args):
        self.after_calls.append((delay, fn, args))
        return len(self.after_calls)

    def after_cancel(self, _job):
        pass


class FakeStdin:
    def __init__(self):
        self.lines = []

    def write(self, line):
        self.lines.append(json.loads(line))

    def flush(self):
        pass


class FakeProcess:
    def __init__(self, *, start_error=None):
        self.start_error = start_error
        self.started = False
        self.terminated = False
        self.stdin = FakeStdin()
        if self.start_error is not None:
            raise self.start_error

    def poll(self):
        return None if not self.terminated else 1

    def wait(self, timeout=None):
        self.started = True

    def terminate(self):
        self.terminated = True


class FakeFallback:
    def __init__(self, root, follow_mouse=True):
        self.root = root
        self.follow_mouse = follow_mouse
        self.calls = []

    def show(self, message, state="listen", level_source=None):
        self.calls.append(("show", message, state, level_source))

    def push_level(self, level):
        self.calls.append(("level", level))

    def hide(self, delay_ms=800):
        self.calls.append(("hide", delay_ms))

    def set_follow_mouse(self, enabled):
        self.calls.append(("follow", enabled))


def test_qt_indicator_sends_show_hide_and_follow_commands():
    qt_indicator = pytest.importorskip("ui.qt_indicator")
    process = FakeProcess()

    indicator = qt_indicator.FloatingIndicator(
        FakeRoot(),
        follow_mouse=False,
        process_factory=lambda follow_mouse: process,
        fallback_factory=FakeFallback,
        qt_available=lambda: True,
        autostart=False,
    )

    indicator.set_follow_mouse(True)
    indicator.show("Transkriberar...", state="transcribe")
    indicator.hide(delay_ms=250)

    assert process.stdin.lines == [
        {"type": "opacity", "opacity": 0.65},
        {"type": "follow_mouse", "enabled": True},
        {"type": "show", "message": "Transkriberar...", "state": "transcribe"},
        {"type": "hide", "delay_ms": 250},
    ]


def test_qt_indicator_falls_back_when_process_start_fails():
    qt_indicator = pytest.importorskip("ui.qt_indicator")
    fallbacks = []

    def fallback_factory(root, follow_mouse=True):
        fallback = FakeFallback(root, follow_mouse=follow_mouse)
        fallbacks.append(fallback)
        return fallback

    indicator = qt_indicator.FloatingIndicator(
        FakeRoot(),
        follow_mouse=True,
        process_factory=lambda follow_mouse: FakeProcess(start_error=RuntimeError("boom")),
        fallback_factory=fallback_factory,
        qt_available=lambda: True,
        autostart=False,
    )

    indicator.show("Lyssnar...", state="listen")
    indicator.push_level(0.25)
    indicator.hide(delay_ms=10)

    assert len(fallbacks) == 1
    assert fallbacks[0].calls == [
        ("show", "Lyssnar...", "listen", None),
        ("level", 0.25),
        ("hide", 10),
    ]


def test_qt_indicator_throttles_level_pushes():
    qt_indicator = pytest.importorskip("ui.qt_indicator")
    process = FakeProcess()
    now = [100.0]

    indicator = qt_indicator.FloatingIndicator(
        FakeRoot(),
        process_factory=lambda follow_mouse: process,
        fallback_factory=FakeFallback,
        qt_available=lambda: True,
        clock=lambda: now[0],
        autostart=False,
    )

    indicator.show("Lyssnar...", state="listen")
    indicator.push_level(0.1)
    indicator.push_level(0.2)
    now[0] += qt_indicator._LEVEL_SEND_INTERVAL_SECONDS
    indicator.push_level(0.3)

    assert process.stdin.lines == [
        {"type": "opacity", "opacity": 0.65},
        {"type": "show", "message": "Lyssnar...", "state": "listen"},
        {"type": "level", "level": 0.1},
        {"type": "level", "level": 0.3},
    ]


def test_qt_indicator_uses_fallback_when_pyside_is_missing():
    qt_indicator = pytest.importorskip("ui.qt_indicator")
    fallbacks = []

    def fallback_factory(root, follow_mouse=True):
        fallback = FakeFallback(root, follow_mouse=follow_mouse)
        fallbacks.append(fallback)
        return fallback

    indicator = qt_indicator.FloatingIndicator(
        FakeRoot(),
        follow_mouse=False,
        process_factory=lambda follow_mouse: FakeProcess(),
        fallback_factory=fallback_factory,
        qt_available=lambda: False,
        autostart=False,
    )

    indicator.show("Transkriberar...", state="transcribe")

    assert len(fallbacks) == 1
    assert fallbacks[0].calls == [("show", "Transkriberar...", "transcribe", None)]


def test_subprocess_entrypoint_does_not_start_main_app(monkeypatch):
    qt_indicator = pytest.importorskip("ui.qt_indicator")
    calls = []

    class FakePopen:
        def __init__(self, args, **kwargs):
            calls.append((args, kwargs))
            self.stdin = FakeStdin()

    monkeypatch.setattr(qt_indicator.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(qt_indicator.sys, "executable", "python-test")
    monkeypatch.setattr(qt_indicator.sys, "frozen", False, raising=False)

    qt_indicator._start_indicator_subprocess(True)

    args, kwargs = calls[0]
    assert args[:3] == ["python-test", "-m", "ui.qt_indicator_child"]
    assert "main.py" not in args
    assert args[-1] == "1"
    assert kwargs["env"]["FREEWISPR_QT_INDICATOR_CHILD"] == "1"


def test_child_module_import_does_not_import_main(monkeypatch):
    sys.modules.pop("ui.qt_indicator_child", None)
    sys.modules.pop("main", None)

    pytest.importorskip("ui.qt_indicator_child")

    assert "main" not in sys.modules
