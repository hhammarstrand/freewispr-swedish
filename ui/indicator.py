"""
FloatingIndicator — small always-on-top pill (recording / transcribing state).
"""
import tkinter as tk
import math
import random
import time as time_module
import ctypes

from ui.styles import BG2, FG, ACC


def _virtual_screen_bounds(root) -> tuple[int, int, int, int]:
    """Return (left, top, right, bottom) for the whole desktop.

    Tk's ``winfo_screenwidth`` usually reports only the primary monitor on
    Windows. Multi-monitor desktops can have negative X/Y coordinates, so the
    floating indicator must clamp to the virtual screen instead.
    """
    try:
        user32 = ctypes.windll.user32
        left = int(user32.GetSystemMetrics(76))   # SM_XVIRTUALSCREEN
        top = int(user32.GetSystemMetrics(77))    # SM_YVIRTUALSCREEN
        width = int(user32.GetSystemMetrics(78))  # SM_CXVIRTUALSCREEN
        height = int(user32.GetSystemMetrics(79)) # SM_CYVIRTUALSCREEN
        if width > 0 and height > 0:
            return left, top, left + width, top + height
    except Exception:
        pass
    return 0, 0, int(root.winfo_screenwidth()), int(root.winfo_screenheight())


class FloatingIndicator:
    """Compact always-on-top pill with animated equalizer bars.

    States:
      listen     — blue bars driven by live microphone level
      transcribe — orange bars pulsing as a traveling sine wave
      done       — green bars at medium height (static)
      error      — red bars at minimum height (static)
    """

    _COLORS = {
        "listen":      "#006aa7",
        "transcribe":  "#f39c12",
        "done":        "#27ae60",
        "error":       "#e74c3c",
    }

    _NUM_BARS = 5
    _BAR_W = 4
    _BAR_GAP = 3
    _BAR_MIN = 3.0
    _BAR_MAX = 18.0
    _CANVAS_H = 22
    _FOLLOW_MS = 16  # ~60 FPS cursor follow; cheap because unchanged geometry is skipped
    _CURSOR_OFFSET_X = 18
    _CURSOR_OFFSET_Y = 18
    _SCREEN_MARGIN = 8

    def __init__(self, root: tk.Tk, follow_mouse: bool = True):
        self._root = root
        self._follow_mouse = bool(follow_mouse)
        self._win: tk.Toplevel | None = None
        self._label: tk.Label | None = None
        self._canvas: tk.Canvas | None = None
        self._bars: list[int] = []
        self._bar_heights = [self._BAR_MIN] * self._NUM_BARS
        self._level_source = None  # callable -> float (mic RMS) [legacy pull]
        self._anim_job = None
        self._hide_job = None
        self._follow_job = None
        self._last_geometry: str | None = None
        self._screen_bounds: tuple[int, int, int, int] | None = None
        self._state: str = "listen"
        self._phase: int = 0
        # Push-driven listen state — audio callback writes _pushed_level and
        # marshals a redraw via _root.after(0, ...). Throttled so a 16 kHz
        # callback fired ~50 Hz can't flood the Tk event queue.
        self._pushed_level: float = 0.0
        self._pending_push: bool = False
        self._last_push_ms: float = 0.0
        self._PUSH_MIN_INTERVAL_MS = 33.0  # ~30 Hz max redraw

    @property
    def _canvas_w(self) -> int:
        return self._NUM_BARS * self._BAR_W + (self._NUM_BARS - 1) * self._BAR_GAP

    # -- public API --------------------------------------------------------- #

    def set_follow_mouse(self, enabled: bool):
        self._follow_mouse = bool(enabled)
        if not self._follow_mouse and self._follow_job:
            self._root.after_cancel(self._follow_job)
            self._follow_job = None
        if self._win is not None:
            self._win.update_idletasks()
            self._position_indicator()

    def show(self, message: str, state: str = "listen", level_source=None):
        """Show the indicator. *level_source* is an optional callable returning
        the current mic RMS (float) — used as a fallback driver for the
        equalizer in listen state when ``push_level`` is not wired."""
        self._state = state
        self._level_source = level_source if state == "listen" else None
        self._pushed_level = 0.0
        self._last_push_ms = 0.0  # re-enable polling fallback until first push
        self._phase = 0
        if self._hide_job:
            self._root.after_cancel(self._hide_job)
            self._hide_job = None
        self._root.after(0, self._show, message, state)

    def push_level(self, level: float) -> None:
        """Thread-safe push of a new mic RMS level from the audio callback.

        Replaces the 50 ms pull-based polling loop in listen state: the
        audio thread tells the UI when a new level is available, the UI
        only redraws on demand. Throttled to ~30 Hz so high-rate callbacks
        don't saturate the Tk event queue.
        """
        if self._state != "listen" or self._win is None:
            return
        self._pushed_level = float(level)
        if self._pending_push:
            return
        now_ms = time_module.monotonic() * 1000.0
        wait = self._PUSH_MIN_INTERVAL_MS - (now_ms - self._last_push_ms)
        self._pending_push = True
        if wait <= 0:
            self._root.after(0, self._consume_push)
        else:
            self._root.after(int(wait), self._consume_push)

    def _consume_push(self):
        self._pending_push = False
        self._last_push_ms = time_module.monotonic() * 1000.0
        if self._state != "listen" or self._canvas is None:
            return
        self._animate_level(self._pushed_level)

    def hide(self, delay_ms: int = 800):
        if self._hide_job:
            self._root.after_cancel(self._hide_job)
        self._hide_job = self._root.after(delay_ms, self._hide)

    # -- internal ----------------------------------------------------------- #

    def _show(self, message: str, state: str):
        color = self._COLORS.get(state, ACC)

        if self._win is None:
            self._win = tk.Toplevel(self._root)
            self._win.overrideredirect(True)
            self._win.attributes("-topmost", True)
            self._win.attributes("-alpha", 0.93)
            self._win.configure(bg=BG2)

            outer = tk.Frame(self._win, bg=BG2, padx=14, pady=7)
            outer.pack()

            self._canvas = tk.Canvas(
                outer, width=self._canvas_w, height=self._CANVAS_H,
                bg=BG2, highlightthickness=0,
            )
            self._canvas.pack(side="left", padx=(0, 10))
            self._create_bars(color)

            self._label = tk.Label(outer, text=message, bg=BG2, fg=FG,
                                   font=("Segoe UI", 10))
            self._label.pack(side="left")

            self._win.update_idletasks()
            self._position_indicator()
        else:
            if self._label:
                self._label.configure(text=message)
            self._recolor_bars(color)
            self._win.update_idletasks()
            self._position_indicator()

        if self._follow_mouse and self._follow_job is None:
            self._follow_cursor()

        # Cancel any previous animation
        if self._anim_job:
            self._root.after_cancel(self._anim_job)
            self._anim_job = None

        # Animated states get a loop; static states set bars once
        if state in ("listen", "transcribe"):
            self._animate()
        else:
            self._set_static_bars(state)

    def _create_bars(self, color: str):
        self._bars = []
        self._bar_heights = [self._BAR_MIN] * self._NUM_BARS
        for i in range(self._NUM_BARS):
            x = i * (self._BAR_W + self._BAR_GAP)
            y_top = self._CANVAS_H - self._BAR_MIN
            bar = self._canvas.create_rectangle(
                x, y_top, x + self._BAR_W, self._CANVAS_H,
                fill=color, outline="",
            )
            self._bars.append(bar)

    def _recolor_bars(self, color: str):
        if self._canvas:
            for bar in self._bars:
                self._canvas.itemconfigure(bar, fill=color)

    def _set_static_bars(self, state: str):
        """Set bars to a fixed height for done/error states."""
        h = self._BAR_MAX * 0.7 if state == "done" else self._BAR_MIN
        for i in range(self._NUM_BARS):
            x = i * (self._BAR_W + self._BAR_GAP)
            y_top = self._CANVAS_H - h
            if self._canvas and i < len(self._bars):
                self._canvas.coords(
                    self._bars[i], x, y_top, x + self._BAR_W, self._CANVAS_H,
                )

    def _position_indicator(self):
        if self._follow_mouse:
            self._position_near_cursor()
        else:
            self._position_fixed_primary()

    def _position_fixed_primary(self):
        if self._win is None:
            return
        try:
            w = self._win.winfo_reqwidth()
            sw = self._root.winfo_screenwidth()
            geometry = f"+{max(self._SCREEN_MARGIN, (sw - w) // 2)}+18"
            if geometry != self._last_geometry:
                self._win.geometry(geometry)
                self._last_geometry = geometry
        except Exception:
            pass

    def _position_near_cursor(self):
        """Place the pill beside the cursor, clamped to the visible screen."""
        if self._win is None:
            return
        try:
            px = self._root.winfo_pointerx()
            py = self._root.winfo_pointery()
            w = self._win.winfo_reqwidth()
            h = self._win.winfo_reqheight()
            if self._screen_bounds is None:
                self._screen_bounds = _virtual_screen_bounds(self._root)
            left, top, right, bottom = self._screen_bounds
            x = px + self._CURSOR_OFFSET_X
            y = py + self._CURSOR_OFFSET_Y
            if x + w + self._SCREEN_MARGIN > right:
                x = px - w - self._CURSOR_OFFSET_X
            if y + h + self._SCREEN_MARGIN > bottom:
                y = py - h - self._CURSOR_OFFSET_Y
            x = max(left + self._SCREEN_MARGIN,
                    min(x, right - w - self._SCREEN_MARGIN))
            y = max(top + self._SCREEN_MARGIN,
                    min(y, bottom - h - self._SCREEN_MARGIN))
            geometry = f"+{int(x)}+{int(y)}"
            if geometry != self._last_geometry:
                self._win.geometry(geometry)
                self._last_geometry = geometry
        except Exception:
            pass

    def _follow_cursor(self):
        if self._win is None:
            self._follow_job = None
            return
        if not self._follow_mouse:
            self._follow_job = None
            return
        self._position_near_cursor()
        self._follow_job = self._root.after(self._FOLLOW_MS, self._follow_cursor)

    # -- animation loop ----------------------------------------------------- #

    def _animate(self):
        if self._win is None or self._canvas is None:
            return
        # listen state is push-driven via push_level(); fall back to the
        # legacy polling driver only if no pushes have arrived (e.g. a
        # caller wired level_source= but not push_level).
        if self._state == "listen":
            if self._last_push_ms > 0.0:
                return  # push pipeline owns redraws
            self._animate_level()
        elif self._state == "transcribe":
            self._animate_wave()
        interval = 50 if self._state == "listen" else 100
        self._anim_job = self._root.after(interval, self._animate)

    def _animate_level(self, level: float | None = None):
        """Equalizer bars — *level* (0..1) supplied by push_level() or pulled
        from the legacy ``level_source`` callable as a fallback."""
        if level is None:
            level = 0.0
            if self._level_source:
                try:
                    level = min(self._level_source() * 12, 1.0)
                except Exception:
                    pass
        else:
            level = min(level * 12, 1.0)

        for i in range(self._NUM_BARS):
            # Each bar gets a slightly different target for an organic look
            jitter = random.uniform(0.3, 1.3)
            target_h = self._BAR_MIN + level * jitter * (self._BAR_MAX - self._BAR_MIN)
            target_h = max(self._BAR_MIN, min(self._BAR_MAX, target_h))

            cur = self._bar_heights[i]
            if target_h > cur:
                new_h = cur * 0.2 + target_h * 0.8   # fast attack
            else:
                new_h = cur * 0.65 + target_h * 0.35  # slow decay
            self._bar_heights[i] = new_h

            x = i * (self._BAR_W + self._BAR_GAP)
            y_top = self._CANVAS_H - new_h
            self._canvas.coords(
                self._bars[i], x, y_top, x + self._BAR_W, self._CANVAS_H,
            )

    def _animate_wave(self):
        """Traveling sine wave for the transcribe/processing state."""
        self._phase += 1
        for i in range(self._NUM_BARS):
            t = (math.sin(self._phase * 0.18 + i * 0.9) + 1) / 2
            h = self._BAR_MIN + t * (self._BAR_MAX - self._BAR_MIN)
            x = i * (self._BAR_W + self._BAR_GAP)
            y_top = self._CANVAS_H - h
            self._canvas.coords(
                self._bars[i], x, y_top, x + self._BAR_W, self._CANVAS_H,
            )

    def _hide(self):
        self._hide_job = None
        if self._anim_job:
            self._root.after_cancel(self._anim_job)
            self._anim_job = None
        if self._follow_job:
            self._root.after_cancel(self._follow_job)
            self._follow_job = None
        self._level_source = None
        self._last_geometry = None
        self._screen_bounds = None
        if self._win:
            self._win.destroy()
            self._win = None
            self._label = None
            self._canvas = None
            self._bars = []
