"""Qt-backed floating indicator with Tk fallback.

The rest of the app still runs on Tkinter. Qt owns its own GUI event loop, so
the animated indicator is isolated in a child process and controlled through a
small command queue. If Qt cannot start, the existing Tk indicator is used.
"""
from __future__ import annotations

import logging
import json
import math
import os
import queue
import sys
import subprocess
import threading
import time
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Callable

from ui.indicator import FloatingIndicator as TkFloatingIndicator


log = logging.getLogger("freewispr")

_BG = "#1a1d24"
_FG = "#eaedf2"
_BLUE = "#006AA7"
_YELLOW = "#FECC02"
_MIX = "#7F9B55"
_CYAN = "#40C7FF"
_DONE = "#22c55e"
_ERROR = "#ef4444"

_LIGHT_BG = "#f6f3ed"
_LIGHT_LINE = "#e6e1d8"
_INK = "#111827"

_LEVEL_SEND_INTERVAL_SECONDS = 1.0 / 30.0


class FloatingIndicator:
    """Process-isolated Qt indicator with the same public API as Tk version."""

    def __init__(
        self,
        root,
        follow_mouse: bool = True,
        *,
        process_factory: Callable[[bool], Any] | None = None,
        fallback_factory: Callable[..., Any] = TkFloatingIndicator,
        qt_available: Callable[[], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
        autostart: bool = True,
    ):
        self._root = root
        self._follow_mouse = bool(follow_mouse)
        self._process_factory = process_factory or _start_indicator_subprocess
        self._fallback_factory = fallback_factory
        self._qt_available = qt_available or _qt_available
        self._clock = clock

        self._process = None
        self._fallback = None
        self._last_level_sent = 0.0
        self._closed = False
        self._style = "modern"

        if autostart:
            self._ensure_started()

    def set_follow_mouse(self, enabled: bool):
        self._follow_mouse = bool(enabled)
        if self._fallback is not None:
            self._fallback.set_follow_mouse(enabled)
            return
        if self._ensure_started():
            self._send({"type": "follow_mouse", "enabled": bool(enabled)})

    def set_style(self, style: str):
        self._style = style
        if style == "classic":
            if self._process is not None:
                try:
                    self._send({"type": "quit"})
                    self._process.wait(timeout=0.5)
                except Exception:
                    pass
                if self._process and self._process.poll() is None:
                    try:
                        self._process.terminate()
                    except Exception:
                        pass
                self._process = None
            self._start_fallback()
        else:
            if self._fallback is not None:
                try:
                    self._fallback.hide()
                except Exception:
                    pass
                self._fallback = None
            if self._ensure_started():
                opacity = 0.0 if style == "transparent" else 0.65
                self._send({"type": "opacity", "opacity": opacity})

    def show(self, message: str, state: str = "listen", level_source=None):
        if self._fallback is not None:
            self._fallback.show(message, state=state, level_source=level_source)
            return
        if self._ensure_started():
            self._send({"type": "show", "message": str(message), "state": str(state)})
        elif self._fallback is not None:
            self._fallback.show(message, state=state, level_source=level_source)

    def push_level(self, level: float) -> None:
        if self._fallback is not None:
            self._fallback.push_level(level)
            return
        now = self._clock()
        if now - self._last_level_sent + 1e-9 < _LEVEL_SEND_INTERVAL_SECONDS:
            return
        self._last_level_sent = now
        if self._ensure_started():
            self._send({"type": "level", "level": float(level)})

    def hide(self, delay_ms: int = 650):
        if self._fallback is not None:
            self._fallback.hide(delay_ms=delay_ms)
            return
        if self._ensure_started():
            self._send({"type": "hide", "delay_ms": int(delay_ms)})

    def close(self) -> None:
        self._closed = True
        if self._fallback is not None:
            return
        process = self._process
        if process is None:
            return
        try:
            self._send({"type": "quit"})
            process.wait(timeout=1.0)
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=1.0)
        except Exception:
            log.debug("Qt-indikatorn kunde inte stängas rent", exc_info=True)

    def _ensure_started(self) -> bool:
        if self._closed:
            return False
        if self._style == "classic":
            self._start_fallback()
            return False
        if self._fallback is not None:
            return False
        if not self._qt_available():
            log.info("PySide6 saknas; använder Tk-indikator")
            self._start_fallback()
            return False
        if self._process is not None:
            if self._process.poll() is None:
                return True
            self._start_fallback()
            return False
        try:
            self._process = self._process_factory(self._follow_mouse)
            opacity = 0.0 if self._style == "transparent" else 0.65
            self._send({"type": "opacity", "opacity": opacity})
        except Exception:
            log.warning("Kunde inte starta Qt-indikatorn; använder Tk-fallback", exc_info=True)
            self._start_fallback()
            return False
        return True

    def _send(self, command: dict[str, Any]) -> None:
        process = self._process
        stdin = getattr(process, "stdin", None) if process is not None else None
        if stdin is None:
            return
        try:
            stdin.write(json.dumps(command, separators=(",", ":")) + "\n")
            stdin.flush()
        except Exception:
            log.debug("Kunde inte skicka kommando till Qt-indikator", exc_info=True)
            self._start_fallback()

    def _start_fallback(self) -> None:
        if self._fallback is not None:
            return
        self._fallback = self._fallback_factory(self._root, follow_mouse=self._follow_mouse)


def _run_indicator_process(command_queue, status_queue, follow_mouse: bool) -> None:
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
    except Exception as exc:  # pragma: no cover - depends on optional PySide6
        try:
            status_queue.put_nowait({"type": "error", "message": repr(exc)})
        except Exception:
            pass
        return

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    widget = _QtIndicatorWidget(command_queue, app, follow_mouse, QtCore, QtGui, QtWidgets)
    widget.start()
    app.exec()


def run_indicator_stdio(follow_mouse: bool) -> None:
    command_queue: queue.Queue[dict[str, Any]] = queue.Queue()

    def read_commands() -> None:
        for line in sys.stdin:
            try:
                command_queue.put_nowait(json.loads(line))
            except Exception:
                continue
        command_queue.put_nowait({"type": "quit"})

    threading.Thread(target=read_commands, name="qt-indicator-stdin", daemon=True).start()
    _run_indicator_process(command_queue, None, follow_mouse)


def _start_indicator_subprocess(follow_mouse: bool):
    root = Path(__file__).resolve().parent.parent
    if getattr(sys, "frozen", False):
        args = [sys.executable, "--qt-indicator-child", "1" if follow_mouse else "0"]
    else:
        args = [sys.executable, "-m", "ui.qt_indicator_child", "1" if follow_mouse else "0"]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    env["FREEWISPR_QT_INDICATOR_CHILD"] = "1"
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.Popen(
        args,
        cwd=str(root),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        bufsize=1,
        env=env,
        creationflags=creationflags,
    )


def _qt_available() -> bool:
    return find_spec("PySide6") is not None


class _QtIndicatorWidget:
    _HEIGHT = 76
    _PILL_PAD = 12
    _PILL_H = 52
    _MIN_WIDTH = 160
    _MAX_WIDTH = 420
    _MARGIN = 8
    _CURSOR_OFFSET_X = 18
    _CURSOR_OFFSET_Y = 18

    def __init__(self, command_queue, app, follow_mouse, QtCore, QtGui, QtWidgets):
        self._queue = command_queue
        self._app = app
        self._QtCore = QtCore
        self._QtGui = QtGui
        self._QtWidgets = QtWidgets

        self._state = "listen"
        self._message = ""
        self._follow_mouse = bool(follow_mouse)
        self._phase = 0.0
        self._level = 0.0
        self._smoothed_level = 0.0
        self._hide_at = 0.0
        self._width = self._MIN_WIDTH
        self._bg_opacity = 0.65
        self._theme = "dark"

        flags = (
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.Tool
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
        )

        class IndicatorWindow(QtWidgets.QWidget):
            def __init__(self, owner):
                super().__init__(None, flags)
                self._owner = owner

            def paintEvent(self, event):
                self._owner._paint(event)

        self._widget = IndicatorWindow(self)
        self._widget.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._widget.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._widget.setFixedSize(self._width, self._HEIGHT)

        self._timer = QtCore.QTimer()
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._timer.start(16)

    def _tick(self) -> None:
        self._handle_commands()
        if self._hide_at and time.monotonic() >= self._hide_at:
            self._hide_at = 0.0
            self._widget.hide()
        if self._widget.isVisible():
            self._phase += 0.05
            if self._state == "listen":
                self._smoothed_level = self._smoothed_level * 0.82 + self._level * 0.18
            else:
                self._smoothed_level = self._smoothed_level * 0.9
            if self._follow_mouse:
                self._position_near_cursor()
            self._widget.update()

    def _handle_commands(self) -> None:
        while True:
            try:
                command = self._queue.get_nowait()
            except queue.Empty:
                return
            if not isinstance(command, dict):
                continue
            kind = command.get("type")
            if kind == "quit":
                self._app.quit()
                return
            if kind == "follow_mouse":
                self._follow_mouse = bool(command.get("enabled"))
                self._position()
                continue
            if kind == "level":
                self._level = max(0.0, min(float(command.get("level", 0.0)) * 12.0, 1.0))
                continue
            if kind == "theme":
                self._theme = str(command.get("theme", "dark"))
                continue
            if kind == "opacity":
                self._bg_opacity = max(0.0, min(1.0, float(command.get("opacity", 0.65))))
                continue
            if kind == "hide":
                delay_ms = max(0, int(command.get("delay_ms", 800)))
                if delay_ms == 0:
                    self._widget.hide()
                    self._hide_at = 0.0
                else:
                    self._hide_at = time.monotonic() + delay_ms / 1000.0
                continue
            if kind == "show":
                self._state = str(command.get("state", "listen"))
                self._message = str(command.get("message", ""))
                self._resize_to_message()
                self._hide_at = 0.0
                self._position()
                self._widget.show()
                self._widget.raise_()

    def _position(self) -> None:
        if self._follow_mouse:
            self._position_near_cursor()
            return
        screen = self._app.primaryScreen()
        rect = screen.availableGeometry() if screen is not None else self._QtCore.QRect(0, 0, 800, 600)
        self._widget.move(rect.center().x() - self._width // 2, rect.top() + 18)

    def _position_near_cursor(self) -> None:
        pos = self._QtGui.QCursor.pos()
        screen = self._app.screenAt(pos) or self._app.primaryScreen()
        rect = screen.availableGeometry() if screen is not None else self._QtCore.QRect(0, 0, 800, 600)
        x = pos.x() + self._CURSOR_OFFSET_X
        y = pos.y() + self._CURSOR_OFFSET_Y
        if x + self._width + self._MARGIN > rect.right():
            x = pos.x() - self._width - self._CURSOR_OFFSET_X
        if y + self._HEIGHT + self._MARGIN > rect.bottom():
            y = pos.y() - self._HEIGHT - self._CURSOR_OFFSET_Y
        x = max(rect.left() + self._MARGIN, min(x, rect.right() - self._width - self._MARGIN))
        y = max(rect.top() + self._MARGIN, min(y, rect.bottom() - self._HEIGHT - self._MARGIN))
        self._widget.move(x, y)

    def _resize_to_message(self) -> None:
        font = self._QtGui.QFont("Segoe UI", 11, self._QtGui.QFont.Weight.Bold)
        text_width = self._QtGui.QFontMetrics(font).horizontalAdvance(self._message)
        width = text_width + 64
        width = max(self._MIN_WIDTH, min(width, self._MAX_WIDTH))
        if width == self._width:
            return
        old_center = self._widget.geometry().center()
        self._width = width
        self._widget.setFixedSize(self._width, self._HEIGHT)
        self._widget.move(old_center.x() - width // 2, old_center.y() - self._HEIGHT // 2)

    def _paint(self, _event) -> None:
        QtCore = self._QtCore
        QtGui = self._QtGui
        painter = QtGui.QPainter(self._widget)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        rect = QtCore.QRectF(
            self._PILL_PAD,
            self._PILL_PAD,
            self._width - self._PILL_PAD * 2,
            self._PILL_H,
        )
        rx = 16.0

        if self._bg_opacity > 0.0:
            for offset, alpha in [(1, 14), (2, 18), (4, 12), (7, 6)]:
                s_rect = rect.translated(0, offset).adjusted(-offset/1.5, -offset/1.5, offset/1.5, offset/1.5)
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.setBrush(QtGui.QColor(0, 0, 0, alpha))
                painter.drawRoundedRect(s_rect, rx + offset/1.5, rx + offset/1.5)

        bg_grad = QtGui.QLinearGradient(rect.left(), rect.top(), rect.right(), rect.top())
        border_grad = QtGui.QLinearGradient(rect.left(), rect.top(), rect.right(), rect.top())

        center_alpha = int(self._bg_opacity * 255)
        edge_alpha = 0 if self._bg_opacity < 1.0 else center_alpha

        if self._theme == "dark":
            base_r, base_g, base_b = 32, 35, 43
            border_r, border_g, border_b = 255, 255, 255
            border_alpha = int(self._bg_opacity * 34)
        else:
            base_r, base_g, base_b = 236, 235, 230
            border_r, border_g, border_b = 0, 0, 0
            border_alpha = int(self._bg_opacity * 20)

        bg_grad.setColorAt(0.0, QtGui.QColor(base_r, base_g, base_b, edge_alpha))
        bg_grad.setColorAt(0.15, QtGui.QColor(base_r, base_g, base_b, center_alpha))
        bg_grad.setColorAt(0.85, QtGui.QColor(base_r, base_g, base_b, center_alpha))
        bg_grad.setColorAt(1.0, QtGui.QColor(base_r, base_g, base_b, edge_alpha))

        if self._state == "done":
            border_grad.setColorAt(0.0, QtGui.QColor(34, 197, 94, 0))
            border_grad.setColorAt(0.15, QtGui.QColor(34, 197, 94, int(self._bg_opacity * 120)))
            border_grad.setColorAt(0.85, QtGui.QColor(34, 197, 94, int(self._bg_opacity * 120)))
            border_grad.setColorAt(1.0, QtGui.QColor(34, 197, 94, 0))
        elif self._state == "error":
            border_grad.setColorAt(0.0, QtGui.QColor(239, 68, 68, 0))
            border_grad.setColorAt(0.15, QtGui.QColor(239, 68, 68, int(self._bg_opacity * 140)))
            border_grad.setColorAt(0.85, QtGui.QColor(239, 68, 68, int(self._bg_opacity * 140)))
            border_grad.setColorAt(1.0, QtGui.QColor(239, 68, 68, 0))
        else:
            border_grad.setColorAt(0.0, QtGui.QColor(border_r, border_g, border_b, 0))
            border_grad.setColorAt(0.15, QtGui.QColor(border_r, border_g, border_b, border_alpha))
            border_grad.setColorAt(0.85, QtGui.QColor(border_r, border_g, border_b, border_alpha))
            border_grad.setColorAt(1.0, QtGui.QColor(border_r, border_g, border_b, 0))

        painter.setPen(QtGui.QPen(border_grad, 1.0))
        painter.setBrush(bg_grad)
        painter.drawRoundedRect(rect, rx, rx)

        painter.save()
        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, rx, rx)
        painter.setClipPath(path)

        if self._state == "listen":
            self._draw_siri_waveform(painter, rect)
        elif self._state == "transcribe":
            self._draw_transcribe_helix(painter, rect)
        elif self._state == "review":
            self._draw_review_ribbon(painter, rect)

        painter.restore()

        self._draw_shimmering_text(painter, rect)

    def _draw_siri_waveform(self, painter, rect) -> None:
        QtCore = self._QtCore
        QtGui = self._QtGui
        cy = rect.center().y()
        w = rect.width()
        h = rect.height()

        if self._theme == "dark":
            waves = [
                (0.04,  0.0,  0.40, QtGui.QColor(0, 106, 167),   60),
                (0.055, 2.1,  0.32, QtGui.QColor(64, 199, 255),  85),
                (0.03,  4.2,  0.25, QtGui.QColor(254, 204, 2),   75),
                (0.045, 1.3,  0.30, QtGui.QColor(127, 155, 85),  65)
            ]
        else:
            waves = [
                (0.04,  0.0,  0.38, QtGui.QColor(0, 90, 140),    45),
                (0.055, 2.1,  0.30, QtGui.QColor(30, 170, 220),  60),
                (0.03,  4.2,  0.24, QtGui.QColor(220, 170, 2),   50),
                (0.045, 1.3,  0.28, QtGui.QColor(100, 130, 70),  40)
            ]

        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

        for freq, phase_off, amp_mult, color, opacity in waves:
            path = QtGui.QPainterPath()
            path.moveTo(rect.left(), cy)

            amplitude = h * amp_mult * self._smoothed_level

            steps = 60
            for i in range(steps + 1):
                x = rect.left() + (w * i / steps)
                envelope = math.sin(math.pi * i / steps)
                angle = (i * freq * 10.0) - (self._phase * 2.5) + phase_off
                y = cy + math.sin(angle) * amplitude * envelope
                path.lineTo(x, y)

            pen_color = QtGui.QColor(color)
            pen_color.setAlpha(opacity)
            painter.setPen(QtGui.QPen(pen_color, 2.2))
            painter.drawPath(path)

    def _draw_transcribe_helix(self, painter, rect) -> None:
        QtCore = self._QtCore
        QtGui = self._QtGui
        cy = rect.center().y()
        w = rect.width()

        steps = 80
        color1 = QtGui.QColor(254, 204, 2, 90) if self._theme == "dark" else QtGui.QColor(220, 170, 2, 110)
        color2 = QtGui.QColor(0, 190, 255, 95) if self._theme == "dark" else QtGui.QColor(0, 110, 200, 115)

        path1 = QtGui.QPainterPath()
        path2 = QtGui.QPainterPath()

        amp = 11.0
        freq = 0.075

        path1.moveTo(rect.left(), cy)
        path2.moveTo(rect.left(), cy)

        for i in range(steps + 1):
            x = rect.left() + (w * i / steps)
            envelope = math.sin(math.pi * i / steps)

            angle1 = (i * freq * 2.5) - (self._phase * 1.0)
            y1 = cy + math.sin(angle1) * amp * envelope
            path1.lineTo(x, y1)

            angle2 = angle1 + math.pi
            y2 = cy + math.sin(angle2) * amp * envelope
            path2.lineTo(x, y2)

        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.setPen(QtGui.QPen(color1, 2.2, QtCore.Qt.PenStyle.SolidLine))
        painter.drawPath(path1)

        painter.setPen(QtGui.QPen(color2, 2.2, QtCore.Qt.PenStyle.SolidLine))
        painter.drawPath(path2)

        rung_pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 25) if self._theme == "dark" else QtGui.QColor(0, 0, 0, 15), 1.0)
        painter.setPen(rung_pen)
        for i in range(2, steps, 4):
            x = rect.left() + (w * i / steps)
            envelope = math.sin(math.pi * i / steps)
            angle = (i * freq * 2.5) - (self._phase * 1.0)
            y1 = cy + math.sin(angle) * amp * envelope
            y2 = cy + math.sin(angle + math.pi) * amp * envelope
            painter.drawLine(QtCore.QPointF(x, y1), QtCore.QPointF(x, y2))

            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(color1)
            painter.drawEllipse(QtCore.QPointF(x, y1), 1.8, 1.8)
            painter.setBrush(color2)
            painter.drawEllipse(QtCore.QPointF(x, y2), 1.8, 1.8)
            painter.setPen(rung_pen)

    def _draw_review_ribbon(self, painter, rect) -> None:
        QtCore = self._QtCore
        QtGui = self._QtGui
        cy = rect.center().y()
        w = rect.width()
        h = rect.height()

        steps = 60
        freq = 0.02
        amp = h * 0.18

        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

        path1 = QtGui.QPainterPath()
        path1.moveTo(rect.left(), cy)
        path2 = QtGui.QPainterPath()
        path2.moveTo(rect.left(), cy)

        for i in range(steps + 1):
            x = rect.left() + (w * i / steps)
            envelope = math.sin(math.pi * i / steps)

            angle1 = (i * freq * 10.0) - (self._phase * 0.6)
            y1 = cy + math.sin(angle1) * amp * envelope
            path1.lineTo(x, y1)

            angle2 = (i * freq * 8.5) - (self._phase * 0.5) + 1.8
            y2 = cy + math.sin(angle2) * (amp * 0.8) * envelope
            path2.lineTo(x, y2)

        grad1 = QtGui.QLinearGradient(rect.left(), cy, rect.right(), cy)
        if self._theme == "dark":
            grad1.setColorAt(0.0, QtGui.QColor(0, 200, 150, 0))
            grad1.setColorAt(0.5, QtGui.QColor(0, 180, 160, 130))
            grad1.setColorAt(1.0, QtGui.QColor(0, 200, 150, 0))
        else:
            grad1.setColorAt(0.0, QtGui.QColor(0, 150, 130, 0))
            grad1.setColorAt(0.5, QtGui.QColor(0, 150, 120, 150))
            grad1.setColorAt(1.0, QtGui.QColor(0, 150, 130, 0))

        painter.setPen(QtGui.QPen(grad1, 2.5))
        painter.drawPath(path1)

        grad2 = QtGui.QLinearGradient(rect.left(), cy, rect.right(), cy)
        if self._theme == "dark":
            grad2.setColorAt(0.0, QtGui.QColor(0, 130, 220, 0))
            grad2.setColorAt(0.5, QtGui.QColor(0, 150, 220, 110))
            grad2.setColorAt(1.0, QtGui.QColor(0, 130, 220, 0))
        else:
            grad2.setColorAt(0.0, QtGui.QColor(0, 100, 180, 0))
            grad2.setColorAt(0.5, QtGui.QColor(0, 120, 200, 130))
            grad2.setColorAt(1.0, QtGui.QColor(0, 100, 180, 0))

        painter.setPen(QtGui.QPen(grad2, 1.8))
        painter.drawPath(path2)

        for i in range(2):
            p_phase = self._phase * 0.4 + i * math.pi
            px = rect.left() + (rect.width() * 0.25) + ((math.sin(p_phase) + 1.0) / 2.0) * (rect.width() * 0.5)
            py = cy + math.cos(p_phase * 1.8) * 4.0
            painter.setBrush(QtGui.QColor(255, 255, 255, 120) if self._theme == "dark" else QtGui.QColor(0, 150, 130, 140))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawEllipse(QtCore.QPointF(px, py), 1.5, 1.5)

    def _draw_shimmering_text(self, painter, rect) -> None:
        QtCore = self._QtCore
        QtGui = self._QtGui
        font = QtGui.QFont("Segoe UI", 11, QtGui.QFont.Weight.Bold)
        painter.setFont(font)

        metrics = QtGui.QFontMetrics(font)
        text_w = metrics.horizontalAdvance(self._message)

        tx = rect.left() + (rect.width() - text_w) / 2.0
        ty = rect.top() + (rect.height() + metrics.ascent() - metrics.descent()) / 2.0

        gradient_width = 80.0
        total_sweep_width = text_w + gradient_width * 2
        sweep_pos = tx - gradient_width + (self._phase * 12.0) % total_sweep_width

        gradient = QtGui.QLinearGradient(sweep_pos, ty, sweep_pos + gradient_width, ty)

        if self._state == "done":
            text_base_color = QtGui.QColor(34, 197, 94)
            shimmer_highlight = QtGui.QColor(187, 247, 208)
        elif self._state == "error":
            text_base_color = QtGui.QColor(239, 68, 68)
            shimmer_highlight = QtGui.QColor(254, 202, 202)
        elif self._theme == "dark":
            text_base_color = QtGui.QColor(230, 235, 245)
            shimmer_highlight = QtGui.QColor(255, 255, 255)
        else:
            text_base_color = QtGui.QColor(17, 24, 39)
            shimmer_highlight = QtGui.QColor(0, 106, 167)

        if self._state in ("done", "error", "listen", "transcribe", "review"):
            gradient.setColorAt(0.0, text_base_color)
            gradient.setColorAt(0.3, text_base_color)
            gradient.setColorAt(0.5, shimmer_highlight)
            gradient.setColorAt(0.7, text_base_color)
            gradient.setColorAt(1.0, text_base_color)
            painter.setPen(QtGui.QPen(QtGui.QBrush(gradient), 1.0))
        else:
            painter.setPen(QtGui.QPen(text_base_color))

        painter.drawText(QtCore.QPointF(tx, ty), self._message)
