"""
Tkinter-based windows for freewispr-swedish.
- FloatingIndicator : small always-on-top pill (recording / transcribing state)
- SnippetsWindow    : manage trigger → expansion pairs
- DictionaryWindow  : manage word corrections (Whisper mistakes)
- SettingsWindow    : hotkey, model, mic, GPU toggle
"""
import tkinter as tk
from tkinter import ttk, messagebox
import math
import random
import threading
import time as time_module
import ctypes

import snippets as snippet_module
import corrections as corr_module
import config as cfg_module

# llm_polish is imported lazily inside SettingsWindow methods.
# Pulling it in at module import time forces openai + httpx (~80 ms cold)
# which delays the tray icon and every window open, even when the user
# never touches LLM polish.


def _llm():
    """Lazy import shim for LLM settings helpers."""
    from llm_polish import AVAILABLE_MODELS, DEFAULT_MODEL, normalize_model, test_connection
    return AVAILABLE_MODELS, DEFAULT_MODEL, normalize_model, test_connection


def _llm_providers():
    """Lazy shim for the multi-provider LLM helpers (ctk Settings UI)."""
    from llm_polish import (
        PROVIDERS, provider_labels, provider_default_model,
        is_user_configurable_url, normalize_model, fetch_models, test_connection,
    )
    return {
        "PROVIDERS": PROVIDERS,
        "labels": provider_labels,
        "default_model": provider_default_model,
        "user_configurable_url": is_user_configurable_url,
        "normalize_model": normalize_model,
        "fetch_models": fetch_models,
        "test_connection": test_connection,
    }


def _tr_providers():
    """Lazy shim for remote-transcription provider helpers."""
    from remote_transcribe import (
        PROVIDERS, provider_labels, provider_default_model, test_connection,
    )
    return {
        "PROVIDERS": PROVIDERS,
        "labels": provider_labels,
        "default_model": provider_default_model,
        "test_connection": test_connection,
    }


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


BG = "#0f0f0f"
BG2 = "#1a1a1a"
ACC = "#006aa7"
ACC2 = "#004f7c"
FG = "#e8e8e8"
FG2 = "#888"
FONT = ("Segoe UI", 10)


BG3 = "#232323"


def _style(root):
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure("TButton", background=ACC, foreground=FG, font=FONT, relief="flat", padding=6)
    s.map("TButton", background=[("active", ACC2)])
    s.configure("Danger.TButton", background="#c0392b", foreground=FG, font=FONT, relief="flat", padding=6)
    s.map("Danger.TButton", background=[("active", "#96281b")])
    s.configure("TLabel", background=BG, foreground=FG, font=FONT)
    s.configure("Sub.TLabel", background=BG, foreground=FG2, font=("Segoe UI", 9))
    s.configure("Card.TLabel", background=BG2, foreground=FG, font=FONT)
    s.configure("CardSub.TLabel", background=BG2, foreground=FG2, font=("Segoe UI", 9))
    s.configure("CardHead.TLabel", background=BG2, foreground=ACC, font=("Segoe UI", 10, "bold"))
    s.configure("TFrame", background=BG)
    s.configure("Card.TFrame", background=BG2)
    s.configure("TEntry", fieldbackground=BG3, foreground=FG, font=FONT,
                insertcolor=FG, borderwidth=1, relief="flat")
    s.map("TEntry",
          fieldbackground=[("focus", BG3), ("!focus", BG3)],
          foreground=[("focus", FG), ("!focus", FG)],
          bordercolor=[("focus", ACC), ("!focus", FG2)])
    s.configure("TCombobox", fieldbackground=BG3, foreground=FG, font=FONT,
                borderwidth=1, relief="flat")
    s.map("TCombobox",
          fieldbackground=[("readonly", BG3)],
          foreground=[("readonly", FG)],
          bordercolor=[("focus", ACC), ("!focus", FG2)])
    s.configure("TCheckbutton", background=BG2, foreground=FG, font=FONT)
    s.map("TCheckbutton", background=[("active", BG2)])
    s.configure("Treeview",
                background=BG2, foreground=FG,
                fieldbackground=BG2, font=FONT,
                rowheight=28, borderwidth=0, relief="flat")
    s.configure("Treeview.Heading",
                background=BG, foreground=FG2,
                font=("Segoe UI", 9), relief="flat")
    s.map("Treeview",
          background=[("selected", ACC)],
          foreground=[("selected", FG)])

    # Fix combobox dropdown colors
    root.option_add("*TCombobox*Listbox.background", BG3)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACC)
    root.option_add("*TCombobox*Listbox.selectForeground", FG)


# --------------------------------------------------------------------------- #
#  Floating indicator pill                                                     #
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
#  Shared helper: entry dialog for add/edit rows                              #
# --------------------------------------------------------------------------- #

class _PairDialog(tk.Toplevel):
    """Modal dialog with two fields: a short trigger/key and a longer value."""

    def __init__(self, parent, title, key_label, val_label,
                 key="", val="", on_save=None):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        _style(self)

        self._on_save = on_save

        pad = {"padx": 20, "pady": 5}

        ttk.Label(self, text=key_label, style="Sub.TLabel").pack(anchor="w", padx=20, pady=(16, 2))
        self._key_var = tk.StringVar(value=key)
        ttk.Entry(self, textvariable=self._key_var, width=36).pack(anchor="w", **pad)

        ttk.Label(self, text=val_label, style="Sub.TLabel").pack(anchor="w", padx=20, pady=(10, 2))
        self._val = tk.Text(self, height=4, width=40,
                            bg=BG2, fg=FG, font=FONT,
                            insertbackground=FG, relief="flat",
                            borderwidth=1, highlightthickness=1,
                            highlightbackground=FG2, highlightcolor=ACC)
        self._val.pack(padx=20, pady=(0, 4))
        self._val.insert("1.0", val)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=20, pady=(8, 16))
        ttk.Button(btn_row, text="Spara", command=self._save).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Avbryt", command=self.destroy).pack(side="left")

        self.wait_window()

    def _save(self):
        key = self._key_var.get().strip().lower()
        val = self._val.get("1.0", "end-1c").strip()
        if not key:
            messagebox.showwarning("freewispr-swedish", "Trigger/ord kan inte vara tomt.", parent=self)
            return
        if not val:
            messagebox.showwarning("freewispr-swedish", "Ersättningstext kan inte vara tom.", parent=self)
            return
        if self._on_save:
            self._on_save(key, val)
        self.destroy()


# --------------------------------------------------------------------------- #
#  Snippets window                                                             #
# --------------------------------------------------------------------------- #

class SnippetsWindow:
    """
    Hantera snippet-bibliotek.
    Säg en trigger exakt → den ersätts med fulltext.
    T.ex. "min adress" → "Exempelvägen 123, 123 45 Staden"
    """

    def __init__(self):
        # CustomTkinter only re-styles the chrome; the Treeview is still ttk
        # because ctk hasn't shipped a native tree widget. That's fine — the
        # ttk style is applied via _style() and matches the dark theme.
        if _CTK_AVAILABLE:
            try:
                ctk.set_appearance_mode("system")
            except Exception:
                pass
            self.root = ctk.CTkToplevel()
        else:
            self.root = tk.Toplevel()
        self.root.title("freewispr-swedish — Snippets")
        self.root.geometry("640x440")
        if not _CTK_AVAILABLE:
            self.root.configure(bg=BG)
        _style(self.root)
        self._build()
        self._load()

    def _build(self):
        outer = ctk.CTkFrame(self.root, fg_color="transparent") if _CTK_AVAILABLE \
                else tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True, padx=16, pady=16)

        if _CTK_AVAILABLE:
            ctk.CTkLabel(
                outer, text="Snippets", anchor="w",
                font=ctk.CTkFont(size=15, weight="bold"),
            ).pack(anchor="w")
            ctk.CTkLabel(
                outer, anchor="w", justify="left",
                text="Säg en trigger exakt vid diktering — den expanderar till fulltext.",
                text_color=("gray40", "gray60"),
            ).pack(anchor="w", pady=(2, 10))
        else:
            ttk.Label(outer, text="Snippets",
                      font=("Segoe UI", 13, "bold")).pack(anchor="w")
            ttk.Label(
                outer, style="Sub.TLabel",
                text="Säg en trigger exakt vid diktering — den expanderar till fulltext.",
            ).pack(anchor="w", pady=(0, 10))

        # Treeview (always ttk — no ctk equivalent)
        tree_wrap = tk.Frame(outer, bg=BG)
        tree_wrap.pack(fill="both", expand=True, pady=(0, 10))

        cols = ("trigger", "expansion")
        self._tree = ttk.Treeview(tree_wrap, columns=cols, show="headings",
                                  selectmode="browse")
        self._tree.heading("trigger",   text="Trigger")
        self._tree.heading("expansion", text="Ersätter med")
        self._tree.column("trigger",   width=160, minwidth=100, stretch=False)
        self._tree.column("expansion", width=420, minwidth=200)
        self._tree.pack(side="left", fill="both", expand=True)

        sb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self._tree.yview)
        sb.pack(side="right", fill="y")
        self._tree.configure(yscrollcommand=sb.set)

        # Button row
        btn_row = ctk.CTkFrame(outer, fg_color="transparent") if _CTK_AVAILABLE \
                  else ttk.Frame(outer)
        btn_row.pack(fill="x")

        if _CTK_AVAILABLE:
            ctk.CTkButton(btn_row, text="Lägg till", command=self._add,
                          width=110).pack(side="left", padx=(0, 8))
            ctk.CTkButton(btn_row, text="Redigera", command=self._edit,
                          width=110, fg_color="transparent", border_width=1,
                          text_color=("gray20", "gray80")
                          ).pack(side="left", padx=(0, 8))
            ctk.CTkButton(btn_row, text="Ta bort", command=self._delete,
                          width=110, fg_color=("#c0392b", "#96281b"),
                          hover_color="#7c1f15").pack(side="left")
        else:
            ttk.Button(btn_row, text="Lägg till", command=self._add
                       ).pack(side="left", padx=(0, 8))
            ttk.Button(btn_row, text="Redigera", command=self._edit
                       ).pack(side="left", padx=(0, 8))
            ttk.Button(btn_row, text="Ta bort", command=self._delete,
                       style="Danger.TButton").pack(side="left")

    def _load(self):
        for item in self._tree.get_children():
            self._tree.delete(item)
        for trigger, expansion in snippet_module.load().items():
            preview = expansion[:80] + "…" if len(expansion) > 80 else expansion
            self._tree.insert("", "end", values=(trigger, preview))

    def _add(self):
        _PairDialog(
            self.root,
            title="Lägg till Snippet",
            key_label='Trigger (t.ex. "min adress", "mvh", "tack"):',
            val_label="Ersätts med:",
            on_save=self._save_pair,
        )

    def _edit(self):
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("freewispr-swedish", "Välj en snippet att redigera.", parent=self.root)
            return
        trigger = self._tree.item(sel[0])["values"][0]
        snips = snippet_module.load()
        _PairDialog(
            self.root,
            title="Redigera Snippet",
            key_label='Trigger:',
            val_label="Ersätts med:",
            key=trigger,
            val=snips.get(trigger, ""),
            on_save=lambda new_key, new_val, old=trigger: self._update_pair(old, new_key, new_val),
        )

    def _delete(self):
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("freewispr-swedish", "Välj en snippet att ta bort.", parent=self.root)
            return
        trigger = self._tree.item(sel[0])["values"][0]
        if not messagebox.askyesno("freewispr-swedish", f'Ta bort snippet "{trigger}"?', parent=self.root):
            return
        snips = snippet_module.load()
        snips.pop(trigger, None)
        snippet_module.save(snips)
        self._load()

    def _save_pair(self, key: str, val: str):
        snips = snippet_module.load()
        snips[key] = val
        snippet_module.save(snips)
        self._load()

    def _update_pair(self, old_key: str, new_key: str, new_val: str):
        snips = snippet_module.load()
        snips.pop(old_key, None)
        snips[new_key] = new_val
        snippet_module.save(snips)
        self._load()


# --------------------------------------------------------------------------- #
#  Personal dictionary window                                                  #
# --------------------------------------------------------------------------- #

class DictionaryWindow:
    """
    Hantera personliga ordkorrigeringar.
    Whispers output skannas och matchande ord ersätts automatiskt.
    T.ex. "fritspr" → "freewispr-swedish", "prak" → "Prakhar"
    """

    def __init__(self):
        if _CTK_AVAILABLE:
            try:
                ctk.set_appearance_mode("system")
            except Exception:
                pass
            self.root = ctk.CTkToplevel()
        else:
            self.root = tk.Toplevel()
        self.root.title("freewispr-swedish — Personlig ordlista")
        self.root.geometry("600x420")
        if not _CTK_AVAILABLE:
            self.root.configure(bg=BG)
        _style(self.root)
        self._build()
        self._load()

    def _build(self):
        outer = ctk.CTkFrame(self.root, fg_color="transparent") if _CTK_AVAILABLE \
                else tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True, padx=16, pady=16)

        if _CTK_AVAILABLE:
            ctk.CTkLabel(
                outer, text="Personlig ordlista", anchor="w",
                font=ctk.CTkFont(size=15, weight="bold"),
            ).pack(anchor="w")
            ctk.CTkLabel(
                outer, anchor="w", justify="left",
                text="Ord som Whisper missförstår ersätts automatiskt efter transkribering.",
                text_color=("gray40", "gray60"),
            ).pack(anchor="w", pady=(2, 10))
        else:
            ttk.Label(outer, text="Personlig ordlista",
                      font=("Segoe UI", 13, "bold")).pack(anchor="w")
            ttk.Label(
                outer, style="Sub.TLabel",
                text="Ord som Whisper missförstår ersätts automatiskt efter transkribering.",
            ).pack(anchor="w", pady=(0, 10))

        # Treeview (always ttk — no ctk equivalent)
        tree_wrap = tk.Frame(outer, bg=BG)
        tree_wrap.pack(fill="both", expand=True, pady=(0, 10))

        cols = ("wrong", "right")
        self._tree = ttk.Treeview(tree_wrap, columns=cols, show="headings",
                                  selectmode="browse")
        self._tree.heading("wrong", text="Whisper hör")
        self._tree.heading("right", text="Ersätt med")
        self._tree.column("wrong", width=230, minwidth=100, stretch=False)
        self._tree.column("right", width=310, minwidth=150)
        self._tree.pack(side="left", fill="both", expand=True)

        sb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self._tree.yview)
        sb.pack(side="right", fill="y")
        self._tree.configure(yscrollcommand=sb.set)

        # Button row
        btn_row = ctk.CTkFrame(outer, fg_color="transparent") if _CTK_AVAILABLE \
                  else ttk.Frame(outer)
        btn_row.pack(fill="x")

        if _CTK_AVAILABLE:
            ctk.CTkButton(btn_row, text="Lägg till", command=self._add,
                          width=110).pack(side="left", padx=(0, 8))
            ctk.CTkButton(btn_row, text="Redigera", command=self._edit,
                          width=110, fg_color="transparent", border_width=1,
                          text_color=("gray20", "gray80")
                          ).pack(side="left", padx=(0, 8))
            ctk.CTkButton(btn_row, text="Ta bort", command=self._delete,
                          width=110, fg_color=("#c0392b", "#96281b"),
                          hover_color="#7c1f15").pack(side="left")
        else:
            ttk.Button(btn_row, text="Lägg till", command=self._add
                       ).pack(side="left", padx=(0, 8))
            ttk.Button(btn_row, text="Redigera", command=self._edit
                       ).pack(side="left", padx=(0, 8))
            ttk.Button(btn_row, text="Ta bort", command=self._delete,
                       style="Danger.TButton").pack(side="left")

    def _load(self):
        for item in self._tree.get_children():
            self._tree.delete(item)
        for wrong, right in corr_module.load().items():
            self._tree.insert("", "end", values=(wrong, right))

    def _add(self):
        _PairDialog(
            self.root,
            title="Lägg till korrigering",
            key_label="Whisper hör (det som blir fel):",
            val_label="Ersätt med (korrekt stavning/namn):",
            on_save=self._save_pair,
        )

    def _edit(self):
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("freewispr-swedish", "Välj ett ord att redigera.", parent=self.root)
            return
        wrong = self._tree.item(sel[0])["values"][0]
        corrs = corr_module.load()
        _PairDialog(
            self.root,
            title="Redigera korrigering",
            key_label="Whisper hör:",
            val_label="Ersätt med:",
            key=wrong,
            val=corrs.get(wrong, ""),
            on_save=lambda nk, nv, old=wrong: self._update_pair(old, nk, nv),
        )

    def _delete(self):
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("freewispr-swedish", "Välj ett ord att ta bort.", parent=self.root)
            return
        wrong = self._tree.item(sel[0])["values"][0]
        if not messagebox.askyesno("freewispr-swedish", f'Ta bort korrigering för "{wrong}"?', parent=self.root):
            return
        corrs = corr_module.load()
        corrs.pop(wrong, None)
        corr_module.save(corrs)
        self._load()

    def _save_pair(self, key: str, val: str):
        corrs = corr_module.load()
        corrs[key] = val
        corr_module.save(corrs)
        self._load()

    def _update_pair(self, old_key: str, new_key: str, new_val: str):
        corrs = corr_module.load()
        corrs.pop(old_key, None)
        corrs[new_key] = new_val
        corr_module.save(corrs)
        self._load()


# --------------------------------------------------------------------------- #
#  Settings window                                                             #
# --------------------------------------------------------------------------- #

# Tk keysym → human-readable name mapping for hotkey capture.
# Only keysyms whose lowercase form differs from the wanted display name
# are listed here; everything else falls through to ``event.keysym.lower()``.
_KEY_NAMES = {
    "Control_L": "ctrl", "Control_R": "right ctrl",
    "Alt_L": "alt", "Alt_R": "right alt",
    "Shift_L": "shift", "Shift_R": "right shift",
    "Return": "enter", "Escape": "esc",
    "BackSpace": "backspace",
}


class _HotkeyCapture(tk.Frame):
    """A clickable widget that captures key combinations."""

    def __init__(self, parent, variable: tk.StringVar, **kw):
        super().__init__(parent, bg=BG3, highlightthickness=1,
                         highlightbackground=FG2, highlightcolor=ACC,
                         padx=12, pady=8, cursor="hand2")
        self._var = variable
        self._capturing = False
        self._held: dict[str, str] = {}  # keysym → display name

        self._display = tk.Label(self, text="", bg=BG3, fg=FG,
                                 font=("Segoe UI Semibold", 11), anchor="w")
        self._display.pack(side="left", fill="x", expand=True)

        self._hint = tk.Label(self, text="", bg=BG3, fg=FG2,
                              font=("Segoe UI", 9), anchor="e")
        self._hint.pack(side="right")

        self._update_display()

        # Click to start capture
        for w in (self, self._display, self._hint):
            w.bind("<Button-1>", self._start_capture)

    def _update_display(self):
        val = self._var.get()
        self._display.configure(text=val if val else "...")
        if not self._capturing:
            self._hint.configure(text="klicka for att andra")

    def _start_capture(self, _=None):
        self._capturing = True
        self._held.clear()
        self.configure(highlightbackground=ACC, highlightcolor=ACC)
        self._display.configure(text="...", fg=ACC)
        self._hint.configure(text="tryck tangentkombination")
        self.focus_set()
        self.bind("<KeyPress>", self._on_key_press)
        self.bind("<KeyRelease>", self._on_key_release)
        self.bind("<FocusOut>", self._cancel_capture)

    def _on_key_press(self, event):
        if not self._capturing:
            return
        if event.keysym == "Escape":
            self._cancel_capture()
            return
        name = _KEY_NAMES.get(event.keysym, event.keysym.lower())
        self._held[event.keysym] = name
        self._display.configure(text="+".join(self._held.values()), fg=FG)

    def _on_key_release(self, event):
        if not self._capturing or not self._held:
            return
        # Commit the combo on first key release
        combo = "+".join(self._held.values())
        self._var.set(combo)
        self._stop_capture()

    def _cancel_capture(self, _=None):
        self._stop_capture()

    def _stop_capture(self):
        self._capturing = False
        self._held.clear()
        self.configure(highlightbackground=FG2, highlightcolor=ACC)
        self.unbind("<KeyPress>")
        self.unbind("<KeyRelease>")
        self.unbind("<FocusOut>")
        self._display.configure(fg=FG)
        self._update_display()



# --------------------------------------------------------------------------- #
#  Settings window — CustomTkinter with tabbed layout                          #
# --------------------------------------------------------------------------- #
#
# Why CustomTkinter:
#   The multi-provider work (LLM provider + remote-transcription provider, each
#   with its own API key and optional base_url) pushed the original flat
#   layout past the point where a single scrolling column was navigable.
#   CTkTabview groups Allmänt / LLM / Transkribering into discrete tabs and
#   gives us native-looking widgets on Windows 11 without bringing in a full
#   Qt/Electron dependency. Falls back to plain Tk if customtkinter isn't
#   installed at runtime — only the Settings UI degrades, the dictation
#   pipeline never touches ctk.
#
# Threading rules (same as the old Tk version):
#   - test_connection() runs on a background thread and marshals results back
#     to the UI via self.root.after(0, ...).
#   - fetch_models() likewise runs in background to avoid blocking provider
#     switches when the network is slow.

try:
    import customtkinter as ctk
    _CTK_AVAILABLE = True
except Exception:
    ctk = None
    _CTK_AVAILABLE = False


# Model-size descriptions reused across both ctk and Tk fallback paths.
_MODEL_INFO = {
    "tiny":   "Snabbast, lägst kvalitet (~40 MB)",
    "base":   "Snabb, grundläggande kvalitet (~150 MB)",
    "small":  "Bra balans mellan hastighet och kvalitet (~500 MB)",
    "medium": "Hög kvalitet, långsammare (~1.5 GB)",
    "large":  "Bästa kvalitet, kräver mer minne (~3 GB)",
}


class SettingsWindow:
    """Tabbed settings window.

    Public contract: ``SettingsWindow(config, on_save=callable)``. The callable
    receives the new config dict and may return ``False`` to veto the save
    (e.g. when the model reload pipeline is busy).
    """

    def __init__(self, config: dict, on_save=None):
        self.cfg = config.copy()
        self.on_save = on_save

        if _CTK_AVAILABLE:
            # Follow Windows light/dark mode and use the neutral blue ctk
            # palette (no Swedish-flag accent in the UI itself — colour is
            # reserved for the tray/exe icon).
            try:
                ctk.set_appearance_mode("system")
                ctk.set_default_color_theme("blue")
            except Exception:
                pass
            self.root = ctk.CTkToplevel()
        else:
            self.root = tk.Toplevel()

        self.root.title("freewispr-swedish — Inställningar")
        self.root.geometry("560x720")
        self.root.minsize(540, 600)

        if not _CTK_AVAILABLE:
            self.root.configure(bg=BG)
            _style(self.root)

        # Shared StringVars / BooleanVars used across tabs. Declared up front
        # so the build methods can wire them without forward references.
        self._init_vars()
        self._build()

    # -- helpers ------------------------------------------------------------- #

    def _init_vars(self):
        c = self.cfg
        self._hotkey_var = tk.StringVar(value=c.get("hotkey", "ctrl+space"))
        self._indicator_follow_var = tk.BooleanVar(
            value=c.get("indicator_follow_mouse", True)
        )
        self._model_var = tk.StringVar(value=c.get("model_size", "small"))
        self._cuda_var = tk.BooleanVar(value=c.get("use_cuda", True))
        self._mic_var = tk.StringVar()  # filled in _build_general

        # LLM
        self._llm_enabled_var = tk.BooleanVar(value=c.get("llm_enabled", False))
        self._llm_provider_var = tk.StringVar(value=c.get("llm_provider", "github"))
        self._llm_model_var = tk.StringVar()  # filled when provider chosen
        self._llm_key_var = tk.StringVar()    # filled when provider chosen
        self._llm_base_url_var = tk.StringVar(
            value=c.get("llm_custom_base_url", "")
        )

        # Transcription
        self._tr_provider_var = tk.StringVar(
            value=c.get("transcription_provider", "local")
        )
        self._tr_model_var = tk.StringVar()
        self._tr_key_var = tk.StringVar()
        self._tr_base_url_var = tk.StringVar(
            value=c.get("transcription_custom_base_url", "")
        )
        self._tr_consent_var = tk.BooleanVar(
            value=c.get("transcription_privacy_accepted", False)
        )

    def _stringvar(self, value: str = "") -> tk.StringVar:
        v = tk.StringVar()
        v.set(value)
        return v

    def _frame(self, parent):
        """Container that adapts to ctk or plain tk."""
        if _CTK_AVAILABLE:
            return ctk.CTkFrame(parent, fg_color="transparent")
        return tk.Frame(parent, bg=BG)

    def _label(self, parent, text, **kw):
        if _CTK_AVAILABLE:
            return ctk.CTkLabel(parent, text=text, anchor="w", **kw)
        return tk.Label(parent, text=text, bg=BG2, fg=FG,
                        font=("Segoe UI", 10), anchor="w")

    def _heading(self, parent, text):
        if _CTK_AVAILABLE:
            return ctk.CTkLabel(
                parent, text=text, anchor="w",
                font=ctk.CTkFont(size=13, weight="bold"),
            )
        return tk.Label(parent, text=text, bg=BG, fg=FG,
                        font=("Segoe UI", 12, "bold"), anchor="w")

    def _hint(self, parent, text):
        if _CTK_AVAILABLE:
            lbl = ctk.CTkLabel(
                parent, text=text, anchor="w",
                font=ctk.CTkFont(size=11),
                text_color=("gray40", "gray60"),
                wraplength=460, justify="left",
            )
        else:
            lbl = tk.Label(parent, text=text, bg=BG, fg=FG2,
                           font=("Segoe UI", 9), anchor="w",
                           wraplength=460, justify="left")
        return lbl

    def _entry(self, parent, var, show=None, width=400):
        if _CTK_AVAILABLE:
            kw = {"textvariable": var, "width": width}
            if show:
                kw["show"] = show
            return ctk.CTkEntry(parent, **kw)
        kw = {"textvariable": var, "bg": BG3, "fg": FG, "font": FONT,
              "insertbackground": FG, "relief": "flat",
              "highlightthickness": 1, "highlightbackground": FG2,
              "highlightcolor": ACC}
        if show:
            kw["show"] = show
        return tk.Entry(parent, **kw)

    def _combobox(self, parent, var, values, width=240, command=None):
        if _CTK_AVAILABLE:
            return ctk.CTkComboBox(
                parent, variable=var, values=list(values),
                width=width, state="readonly", command=command,
            )
        combo = ttk.Combobox(parent, textvariable=var, values=list(values),
                             state="readonly", width=max(10, width // 8))
        if command is not None:
            combo.bind("<<ComboboxSelected>>", lambda _e: command(var.get()))
        return combo

    def _switch(self, parent, text, var):
        if _CTK_AVAILABLE:
            return ctk.CTkSwitch(parent, text=text, variable=var,
                                 onvalue=True, offvalue=False)
        # Reuse the old custom toggle in fallback mode.
        row = tk.Frame(parent, bg=BG, cursor="hand2")
        ind = tk.Label(row, bg=BG, fg=FG2, font=("Segoe UI", 11), width=2)
        ind.pack(side="left")
        lbl = tk.Label(row, text=text, bg=BG, fg=FG, anchor="w",
                       font=("Segoe UI", 10))
        lbl.pack(side="left", fill="x", expand=True)

        def _upd(*_):
            ind.configure(text="\u25c9" if var.get() else "\u25cb",
                          fg=ACC if var.get() else FG2)
        _upd()
        var.trace_add("write", _upd)
        for w in (row, ind, lbl):
            w.bind("<Button-1>", lambda _e: var.set(not var.get()))
        return row

    def _button(self, parent, text, command, *, primary=False, danger=False):
        if _CTK_AVAILABLE:
            kw = {"text": text, "command": command}
            if danger:
                kw["fg_color"] = ("#c0392b", "#96281b")
                kw["hover_color"] = "#7c1f15"
            elif not primary:
                kw["fg_color"] = "transparent"
                kw["border_width"] = 1
                kw["text_color"] = ("gray20", "gray80")
            return ctk.CTkButton(parent, **kw)
        bg = "#c0392b" if danger else (ACC if primary else BG3)
        fg = FG if (primary or danger) else FG2
        return tk.Button(parent, text=text, bg=bg, fg=fg, relief="flat",
                         font=("Segoe UI Semibold", 10) if primary else FONT,
                         activebackground=ACC2 if primary else "#333",
                         activeforeground=FG, padx=18, pady=6, cursor="hand2",
                         command=command)

    # -- build --------------------------------------------------------------- #

    def _build(self):
        outer = self._frame(self.root)
        outer.pack(fill="both", expand=True, padx=18, pady=18)

        self._heading(outer, "Inställningar").pack(anchor="w", pady=(0, 12))

        if _CTK_AVAILABLE:
            self._tabs = ctk.CTkTabview(outer, anchor="nw")
            self._tabs.pack(fill="both", expand=True)
            tab_general = self._tabs.add("Allmänt")
            tab_llm = self._tabs.add("LLM-granskning")
            tab_tr = self._tabs.add("Transkribering")
        else:
            self._tabs = ttk.Notebook(outer)
            self._tabs.pack(fill="both", expand=True)
            tab_general = ttk.Frame(self._tabs)
            tab_llm = ttk.Frame(self._tabs)
            tab_tr = ttk.Frame(self._tabs)
            self._tabs.add(tab_general, text="Allmänt")
            self._tabs.add(tab_llm, text="LLM-granskning")
            self._tabs.add(tab_tr, text="Transkribering")

        self._build_general(tab_general)
        self._build_llm(tab_llm)
        self._build_transcription(tab_tr)

        # Bottom button row
        btn_row = self._frame(outer)
        btn_row.pack(fill="x", pady=(14, 0))
        self._button(btn_row, "Avbryt", self.root.destroy).pack(
            side="right", padx=(8, 0)
        )
        self._button(btn_row, "Spara", self._save, primary=True).pack(
            side="right"
        )

    # ------- Tab: Allmänt --------------------------------------------------- #

    def _build_general(self, parent):
        pad = {"padx": 6, "pady": (10, 0)}

        self._label(parent, "Dikteringstangent",
                    font=ctk.CTkFont(weight="bold") if _CTK_AVAILABLE else None
                    ).pack(anchor="w", **pad)
        hk = _HotkeyCapture(parent, self._hotkey_var)
        hk.pack(fill="x", padx=6, pady=(4, 0))
        self._hint(parent, "Klicka och tryck önskad tangentkombination.").pack(
            anchor="w", padx=6, pady=(4, 8)
        )

        # Lyssnarindikator
        self._label(parent, "Lyssnarindikator",
                    font=ctk.CTkFont(weight="bold") if _CTK_AVAILABLE else None
                    ).pack(anchor="w", **pad)
        self._switch(parent, "Följ muspekaren", self._indicator_follow_var).pack(
            anchor="w", padx=6, pady=(6, 0)
        )
        self._hint(parent, "Av = fast position överst på huvudskärmen.").pack(
            anchor="w", padx=6, pady=(2, 8)
        )

        # Mikrofon
        self._label(parent, "Mikrofon",
                    font=ctk.CTkFont(weight="bold") if _CTK_AVAILABLE else None
                    ).pack(anchor="w", **pad)

        from audio import list_input_devices
        self._mic_devices = list_input_devices()
        mic_names = ["Auto"] + [d["name"] for d in self._mic_devices]

        saved_mic_raw = self.cfg.get("mic_device")
        if isinstance(saved_mic_raw, dict):
            saved_mic = saved_mic_raw.get("name", "")
        else:
            saved_mic = saved_mic_raw or ""
        self._mic_var.set(saved_mic if saved_mic else "Auto")

        self._combobox(parent, self._mic_var, mic_names, width=480,
                       command=lambda _v: self._update_mic_info()).pack(
            anchor="w", padx=6, pady=(4, 0), fill="x"
        )
        self._mic_info = self._hint(parent, "")
        self._mic_info.pack(anchor="w", padx=6, pady=(2, 8))
        self._update_mic_info()

        # Whisper-modell
        self._label(parent, "Whisper-modell",
                    font=ctk.CTkFont(weight="bold") if _CTK_AVAILABLE else None
                    ).pack(anchor="w", **pad)
        self._combobox(parent, self._model_var,
                       ["tiny", "base", "small", "medium", "large"],
                       width=180,
                       command=lambda _v: self._update_model_desc()).pack(
            anchor="w", padx=6, pady=(4, 0)
        )
        self._model_desc = self._hint(parent, "")
        self._model_desc.pack(anchor="w", padx=6, pady=(2, 4))
        self._update_model_desc()

        self._switch(parent, "Använd GPU/CUDA (snabbare med NVIDIA)",
                     self._cuda_var).pack(anchor="w", padx=6, pady=(8, 4))
        self._hint(parent,
                   "Används endast för lokal Whisper-modell. "
                   "Slås av automatiskt vid remote-transkribering.").pack(
            anchor="w", padx=6, pady=(0, 8)
        )

    def _update_mic_info(self):
        name = self._mic_var.get()
        if name == "Auto":
            self._mic_info.configure(
                text="Väljer bästa tillgängliga mikrofon automatiskt."
            )
            return
        for d in self._mic_devices:
            if d["name"] == name:
                self._mic_info.configure(
                    text=f"{d['api']}  •  {d['rate']} Hz  •  {d['channels']} ch"
                )
                return
        self._mic_info.configure(text="")

    def _update_model_desc(self):
        self._model_desc.configure(
            text=_MODEL_INFO.get(self._model_var.get(), "")
        )

    # ------- Tab: LLM ------------------------------------------------------- #

    def _build_llm(self, parent):
        pad = {"padx": 6, "pady": (10, 0)}

        self._switch(parent, "Aktivera LLM-granskning",
                     self._llm_enabled_var).pack(anchor="w", **pad)
        self._hint(parent,
                   "Transkriberad text skickas till vald leverantör för "
                   "lättviktig korrigering. Stäng av för helt lokal "
                   "diktering.").pack(anchor="w", padx=6, pady=(2, 8))

        # Provider selector
        self._label(parent, "Leverantör",
                    font=ctk.CTkFont(weight="bold") if _CTK_AVAILABLE else None
                    ).pack(anchor="w", **pad)

        llm = _llm_providers()
        labels = llm["labels"]()  # {provider_id: human_label}
        # Map label → provider_id for the combobox; ctk's CTkComboBox can
        # only show one string, so we display labels and translate back.
        self._llm_label_to_id = {v: k for k, v in labels.items()}
        self._llm_id_to_label = labels
        cur_pid = self._llm_provider_var.get()
        cur_label = labels.get(cur_pid, next(iter(labels.values())))
        self._llm_provider_label_var = self._stringvar(cur_label)

        self._combobox(parent, self._llm_provider_label_var,
                       list(labels.values()), width=320,
                       command=lambda _v: self._on_llm_provider_change()
                       ).pack(anchor="w", padx=6, pady=(4, 0), fill="x")

        # Model picker
        self._label(parent, "Modell").pack(anchor="w", padx=6, pady=(10, 2))
        self._llm_model_combo = self._combobox(
            parent, self._llm_model_var, [], width=400,
        )
        self._llm_model_combo.pack(anchor="w", padx=6, pady=(0, 0), fill="x")
        self._llm_models_status = self._hint(parent, "")
        self._llm_models_status.pack(anchor="w", padx=6, pady=(2, 4))

        # API key
        self._label(parent, "API-nyckel").pack(anchor="w", padx=6, pady=(10, 2))
        self._llm_key_entry = self._entry(parent, self._llm_key_var, show="•")
        self._llm_key_entry.pack(anchor="w", padx=6, pady=(0, 4), fill="x")

        key_row = self._frame(parent)
        key_row.pack(fill="x", padx=6, pady=(0, 4))
        self._llm_show_key = False
        self._llm_show_btn = self._button(
            key_row, "Visa nyckel", self._toggle_llm_key_visibility,
        )
        self._llm_show_btn.pack(side="left")
        self._llm_test_btn = self._button(
            key_row, "Testa anslutning", self._test_llm, primary=True,
        )
        self._llm_test_btn.pack(side="left", padx=(8, 0))
        self._llm_test_result = self._hint(parent, "")
        self._llm_test_result.pack(anchor="w", padx=6, pady=(4, 8))

        # Custom base URL (visible only for custom provider)
        self._llm_base_label = self._label(parent, "Base URL (custom)")
        self._llm_base_entry = self._entry(parent, self._llm_base_url_var)
        self._llm_base_hint = self._hint(
            parent,
            "T.ex. http://localhost:8080/v1 för en lokal OpenAI-kompatibel server."
        )

        # Initialise dependent widgets (model list, key field, base URL row)
        self._on_llm_provider_change()

    def _on_llm_provider_change(self):
        pid = self._llm_label_to_id.get(
            self._llm_provider_label_var.get(),
            self._llm_provider_var.get(),
        )
        self._llm_provider_var.set(pid)

        # Load saved model + key for this provider.
        llm = _llm_providers()
        saved_model = self.cfg.get(f"llm_model_{pid}", "") or llm["default_model"](pid)
        self._llm_model_var.set(saved_model)
        self._llm_key_var.set(self.cfg.get(f"llm_api_key_{pid}", ""))

        # Populate the model dropdown from the provider's static fallback
        # list immediately, then try to refresh from the server in a thread.
        provider = llm["PROVIDERS"].get(pid)
        static_models = list(provider.fallback_models.keys()) if provider else []
        if saved_model and saved_model not in static_models:
            static_models = [saved_model] + static_models
        self._set_llm_model_choices(static_models)
        self._llm_models_status.configure(text="")

        # Toggle base_url row.
        show_base = llm["user_configurable_url"](pid)
        for w in (self._llm_base_label, self._llm_base_entry, self._llm_base_hint):
            w.pack_forget()
        if show_base:
            self._llm_base_label.pack(anchor="w", padx=6, pady=(10, 2))
            self._llm_base_entry.pack(anchor="w", padx=6, pady=(0, 2), fill="x")
            self._llm_base_hint.pack(anchor="w", padx=6, pady=(0, 8))

        # Async fetch updated models from the server. Best-effort.
        threading.Thread(
            target=self._fetch_llm_models_async,
            args=(pid, self._llm_key_var.get(), self._llm_base_url_var.get()),
            daemon=True,
        ).start()

    def _set_llm_model_choices(self, values: list[str]):
        if not values:
            return
        cur = self._llm_model_var.get()
        if _CTK_AVAILABLE and hasattr(self._llm_model_combo, "configure"):
            try:
                self._llm_model_combo.configure(values=values)
            except Exception:
                pass
        else:
            try:
                self._llm_model_combo["values"] = values
            except Exception:
                pass
        if cur not in values:
            self._llm_model_var.set(values[0])

    def _fetch_llm_models_async(self, pid: str, key: str, base_url: str):
        try:
            llm = _llm_providers()
            models = llm["fetch_models"](key, pid, base_url)
        except Exception:
            models = {}
        if not models:
            return
        names = list(models.keys())
        self.root.after(0, lambda: self._set_llm_model_choices(names))
        self.root.after(
            0,
            lambda: self._llm_models_status.configure(
                text=f"{len(names)} modeller hittade hos leverantören."
            ),
        )

    def _toggle_llm_key_visibility(self):
        self._llm_show_key = not self._llm_show_key
        try:
            self._llm_key_entry.configure(show="" if self._llm_show_key else "•")
        except Exception:
            pass
        self._llm_show_btn.configure(
            text="Dölj nyckel" if self._llm_show_key else "Visa nyckel"
        )

    def _test_llm(self):
        llm = _llm_providers()
        pid = self._llm_provider_var.get()
        key = self._llm_key_var.get().strip()
        model = self._llm_model_var.get()
        base_url = self._llm_base_url_var.get().strip()

        try:
            self._llm_test_btn.configure(state="disabled", text="Testar...")
        except Exception:
            pass
        self._llm_test_result.configure(text="Ansluter...")

        def _run():
            try:
                ok, msg = llm["test_connection"](key, model, pid, base_url)
            except Exception as e:
                ok, msg = False, f"Fel: {e}"
            self.root.after(0, lambda: self._show_llm_test_result(ok, msg))

        threading.Thread(target=_run, daemon=True).start()

    def _show_llm_test_result(self, ok: bool, msg: str):
        try:
            self._llm_test_btn.configure(state="normal", text="Testa anslutning")
        except Exception:
            pass
        prefix = "✓ " if ok else "✗ "
        try:
            if _CTK_AVAILABLE:
                color = ("#27ae60", "#2ecc71") if ok else ("#c0392b", "#e74c3c")
                self._llm_test_result.configure(text=prefix + msg, text_color=color)
            else:
                self._llm_test_result.configure(
                    text=prefix + msg, fg="#27ae60" if ok else "#c0392b"
                )
        except Exception:
            self._llm_test_result.configure(text=prefix + msg)

    # ------- Tab: Transkribering ------------------------------------------- #

    def _build_transcription(self, parent):
        pad = {"padx": 6, "pady": (10, 0)}

        self._label(parent, "Transkriberingsleverantör",
                    font=ctk.CTkFont(weight="bold") if _CTK_AVAILABLE else None
                    ).pack(anchor="w", **pad)
        self._hint(parent,
                   "Lokal = Whisper körs på din dator (privat, snabb på GPU). "
                   "Remote = ljudet skickas till en svensk/EU-server med "
                   "KB-Whisper Large — bättre på svenska men kräver internet "
                   "och samtycke.").pack(anchor="w", padx=6, pady=(2, 8))

        tr = _tr_providers()
        # The radio shows "Lokal" + each remote provider's human label.
        self._tr_label_to_id = {"Lokal Whisper (på datorn)": "local"}
        for pid, label in tr["labels"]().items():
            self._tr_label_to_id[label] = pid
        self._tr_id_to_label = {v: k for k, v in self._tr_label_to_id.items()}
        cur_pid = self._tr_provider_var.get()
        cur_label = self._tr_id_to_label.get(cur_pid, "Lokal Whisper (på datorn)")
        self._tr_provider_label_var = self._stringvar(cur_label)

        self._combobox(parent, self._tr_provider_label_var,
                       list(self._tr_label_to_id.keys()), width=400,
                       command=lambda _v: self._on_tr_provider_change()
                       ).pack(anchor="w", padx=6, pady=(4, 8), fill="x")

        # Remote-only fields go in a sub-frame so we can hide them in "local" mode.
        self._tr_remote_frame = self._frame(parent)
        self._tr_remote_frame.pack(fill="x", padx=0, pady=0)

        self._label(self._tr_remote_frame, "Modell").pack(
            anchor="w", padx=6, pady=(0, 2)
        )
        self._tr_model_entry = self._entry(self._tr_remote_frame, self._tr_model_var)
        self._tr_model_entry.pack(anchor="w", padx=6, pady=(0, 2), fill="x")
        self._tr_model_hint = self._hint(self._tr_remote_frame, "")
        self._tr_model_hint.pack(anchor="w", padx=6, pady=(0, 8))

        self._label(self._tr_remote_frame, "API-nyckel").pack(
            anchor="w", padx=6, pady=(0, 2)
        )
        self._tr_key_entry = self._entry(self._tr_remote_frame, self._tr_key_var, show="•")
        self._tr_key_entry.pack(anchor="w", padx=6, pady=(0, 4), fill="x")

        tr_btn_row = self._frame(self._tr_remote_frame)
        tr_btn_row.pack(fill="x", padx=6, pady=(0, 4))
        self._tr_show_key = False
        self._tr_show_btn = self._button(
            tr_btn_row, "Visa nyckel", self._toggle_tr_key_visibility,
        )
        self._tr_show_btn.pack(side="left")
        self._tr_test_btn = self._button(
            tr_btn_row, "Testa anslutning", self._test_tr, primary=True,
        )
        self._tr_test_btn.pack(side="left", padx=(8, 0))
        self._tr_test_result = self._hint(self._tr_remote_frame, "")
        self._tr_test_result.pack(anchor="w", padx=6, pady=(4, 8))

        # Base URL (custom only)
        self._tr_base_label = self._label(self._tr_remote_frame, "Base URL (custom)")
        self._tr_base_entry = self._entry(self._tr_remote_frame, self._tr_base_url_var)
        self._tr_base_hint = self._hint(
            self._tr_remote_frame,
            "T.ex. https://api.example.com/v1 — måste exponera "
            "/v1/audio/transcriptions och /v1/models."
        )

        # Consent
        self._tr_consent_switch = self._switch(
            self._tr_remote_frame,
            "Jag samtycker till att ljudet skickas till vald server",
            self._tr_consent_var,
        )
        self._tr_consent_switch.pack(anchor="w", padx=6, pady=(8, 0))
        self._hint(self._tr_remote_frame,
                   "Krävs för att aktivera remote-transkribering. "
                   "Stäng av detta och leverantören återgår till lokal "
                   "Whisper.").pack(anchor="w", padx=6, pady=(2, 8))

        self._on_tr_provider_change()

    def _on_tr_provider_change(self):
        pid = self._tr_label_to_id.get(
            self._tr_provider_label_var.get(),
            self._tr_provider_var.get(),
        )
        self._tr_provider_var.set(pid)

        if pid == "local":
            try:
                self._tr_remote_frame.pack_forget()
            except Exception:
                pass
            return

        # Show remote-only fields.
        try:
            self._tr_remote_frame.pack(fill="x", padx=0, pady=0)
        except Exception:
            pass

        tr = _tr_providers()
        default_model = tr["default_model"](pid)
        saved_model = self.cfg.get(f"transcription_model_{pid}", "") or default_model
        self._tr_model_var.set(saved_model)
        self._tr_key_var.set(self.cfg.get(f"transcription_api_key_{pid}", ""))
        self._tr_model_hint.configure(
            text=f"Standard: {default_model}" if default_model else
                 "Ange modellnamn enligt leverantörens dokumentation."
        )

        # Custom base_url row visibility.
        provider = tr["PROVIDERS"].get(pid)
        show_base = bool(provider and provider.user_configurable_url)
        for w in (self._tr_base_label, self._tr_base_entry, self._tr_base_hint):
            w.pack_forget()
        if show_base:
            self._tr_base_label.pack(anchor="w", padx=6, pady=(8, 2))
            self._tr_base_entry.pack(anchor="w", padx=6, pady=(0, 2), fill="x")
            self._tr_base_hint.pack(anchor="w", padx=6, pady=(0, 8))

    def _toggle_tr_key_visibility(self):
        self._tr_show_key = not self._tr_show_key
        try:
            self._tr_key_entry.configure(show="" if self._tr_show_key else "•")
        except Exception:
            pass
        self._tr_show_btn.configure(
            text="Dölj nyckel" if self._tr_show_key else "Visa nyckel"
        )

    def _test_tr(self):
        pid = self._tr_provider_var.get()
        if pid == "local":
            self._tr_test_result.configure(
                text="Lokal Whisper kräver inget anslutningstest."
            )
            return
        key = self._tr_key_var.get().strip()
        base_url = self._tr_base_url_var.get().strip()

        try:
            self._tr_test_btn.configure(state="disabled", text="Testar...")
        except Exception:
            pass
        self._tr_test_result.configure(text="Ansluter...")

        def _run():
            try:
                tr = _tr_providers()
                ok, msg = tr["test_connection"](pid, key, base_url)
            except Exception as e:
                ok, msg = False, f"Fel: {e}"
            self.root.after(0, lambda: self._show_tr_test_result(ok, msg))

        threading.Thread(target=_run, daemon=True).start()

    def _show_tr_test_result(self, ok: bool, msg: str):
        try:
            self._tr_test_btn.configure(state="normal", text="Testa anslutning")
        except Exception:
            pass
        prefix = "✓ " if ok else "✗ "
        try:
            if _CTK_AVAILABLE:
                color = ("#27ae60", "#2ecc71") if ok else ("#c0392b", "#e74c3c")
                self._tr_test_result.configure(text=prefix + msg, text_color=color)
            else:
                self._tr_test_result.configure(
                    text=prefix + msg, fg="#27ae60" if ok else "#c0392b"
                )
        except Exception:
            self._tr_test_result.configure(text=prefix + msg)

    # -- save ---------------------------------------------------------------- #

    def _save(self):
        # Resolve labels back to provider ids in case the combobox change
        # callbacks didn't fire (rare on keyboard navigation).
        llm_pid = self._llm_label_to_id.get(
            self._llm_provider_label_var.get(),
            self._llm_provider_var.get(),
        )
        tr_pid = self._tr_label_to_id.get(
            self._tr_provider_label_var.get(),
            self._tr_provider_var.get(),
        )

        llm_enabled = self._llm_enabled_var.get()
        llm_key = self._llm_key_var.get().strip()
        llm_was_enabled = self.cfg.get("llm_enabled", False)
        llm_privacy_accepted = self.cfg.get("llm_privacy_accepted", False)
        needs_llm_consent = llm_enabled and (
            not llm_was_enabled or not llm_privacy_accepted
        )

        # Sanity: can we store the secret?
        any_key_to_store = bool(llm_key) or bool(self._tr_key_var.get().strip())
        if any_key_to_store and not cfg_module.can_store_secret():
            messagebox.showerror(
                "Kan inte spara API-nyckel",
                "Saknar säker lagring för API-nyckeln. Installera/aktivera "
                "keyring med Windows Credential Manager och försök igen.",
            )
            return

        if needs_llm_consent:
            ok = messagebox.askokcancel(
                "Aktivera LLM-granskning?",
                "LLM-granskning skickar din transkriberade text till vald "
                "leverantör för korrigering.\n\nAktivera bara detta om du "
                "accepterar att texten lämnar datorn.",
            )
            if not ok:
                return

        # Transcription consent — only required when leaving "local".
        if tr_pid != "local" and not self._tr_consent_var.get():
            messagebox.showwarning(
                "Samtycke krävs",
                "Remote-transkribering skickar ditt ljud till en extern "
                "server. Bocka i samtyckesrutan på fliken Transkribering "
                "för att aktivera, eller välj Lokal Whisper.",
            )
            return

        # ---- Build new_cfg ----
        new_cfg = self.cfg.copy()
        new_cfg["hotkey"] = self._hotkey_var.get().strip()
        new_cfg["model_size"] = self._model_var.get()
        new_cfg["use_cuda"] = self._cuda_var.get()
        new_cfg["indicator_follow_mouse"] = self._indicator_follow_var.get()

        mic = self._mic_var.get()
        if mic == "Auto":
            new_cfg["mic_device"] = None
        else:
            picked = next(
                (d for d in getattr(self, "_mic_devices", []) if d["name"] == mic),
                None,
            )
            if picked:
                new_cfg["mic_device"] = {
                    "name": picked["name"],
                    "api": picked["api"],
                    "index": picked["index"],
                }
            else:
                new_cfg["mic_device"] = mic

        # LLM
        new_cfg["llm_enabled"] = llm_enabled
        new_cfg["llm_provider"] = llm_pid
        new_cfg[f"llm_model_{llm_pid}"] = self._llm_model_var.get().strip()
        new_cfg[f"llm_api_key_{llm_pid}"] = llm_key
        new_cfg["llm_custom_base_url"] = self._llm_base_url_var.get().strip()
        new_cfg["llm_privacy_accepted"] = bool(
            llm_enabled and (llm_privacy_accepted or needs_llm_consent)
        )

        # Transcription
        new_cfg["transcription_provider"] = tr_pid
        if tr_pid != "local":
            new_cfg[f"transcription_model_{tr_pid}"] = self._tr_model_var.get().strip()
            new_cfg[f"transcription_api_key_{tr_pid}"] = self._tr_key_var.get().strip()
            new_cfg["transcription_custom_base_url"] = self._tr_base_url_var.get().strip()
        new_cfg["transcription_privacy_accepted"] = bool(
            tr_pid != "local" and self._tr_consent_var.get()
        )

        # Strip removed legacy keys.
        for k in ("filter_fillers", "auto_punctuate", "language",
                  "llm_api_key", "llm_model"):
            new_cfg.pop(k, None)

        if self.on_save:
            if self.on_save(new_cfg) is False:
                return
        self.root.destroy()
