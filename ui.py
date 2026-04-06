"""
Tkinter-based windows for freewispr.
- FloatingIndicator : small always-on-top pill (recording / transcribing state)
- SettingsWindow    : hotkey, model, language, filler filter
"""
import tkinter as tk
from tkinter import ttk


BG = "#0f0f0f"
BG2 = "#1a1a1a"
ACC = "#7c5cfc"
ACC2 = "#5a3fd4"
FG = "#e8e8e8"
FG2 = "#888"
FONT = ("Segoe UI", 10)


def _style(root):
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure("TButton", background=ACC, foreground=FG, font=FONT, relief="flat", padding=6)
    s.map("TButton", background=[("active", ACC2)])
    s.configure("TLabel", background=BG, foreground=FG, font=FONT)
    s.configure("Sub.TLabel", background=BG, foreground=FG2, font=("Segoe UI", 9))
    s.configure("TFrame", background=BG)
    s.configure("TEntry", fieldbackground=BG2, foreground=FG, font=FONT)
    s.configure("TCombobox", fieldbackground=BG2, foreground=FG, font=FONT)
    s.configure("TCheckbutton", background=BG, foreground=FG, font=FONT)
    s.map("TCheckbutton", background=[("active", BG)])


# --------------------------------------------------------------------------- #
#  Floating indicator pill                                                     #
# --------------------------------------------------------------------------- #

class FloatingIndicator:
    """
    Small always-on-top pill that appears during dictation/transcription.
    Shows at the top-centre of the screen with a pulsing dot.
    """

    _COLORS = {
        "listen":      "#7c5cfc",   # purple  — listening
        "transcribe":  "#f39c12",   # amber   — processing
        "done":        "#27ae60",   # green   — pasted
    }

    def __init__(self, root: tk.Tk):
        self._root = root
        self._win: tk.Toplevel | None = None
        self._label: tk.Label | None = None
        self._dot: tk.Label | None = None
        self._blink_job = None
        self._state: str = "listen"

    def show(self, message: str, state: str = "listen"):
        self._state = state
        self._root.after(0, self._show, message, state)

    def hide(self, delay_ms: int = 800):
        self._root.after(delay_ms, self._hide)

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

            self._dot = tk.Label(outer, text="●", bg=BG2, fg=color,
                                 font=("Segoe UI", 9))
            self._dot.pack(side="left", padx=(0, 7))

            self._label = tk.Label(outer, text=message, bg=BG2, fg=FG,
                                   font=("Segoe UI", 10))
            self._label.pack(side="left")

            self._win.update_idletasks()
            sw = self._win.winfo_screenwidth()
            w = self._win.winfo_reqwidth()
            self._win.geometry(f"+{(sw - w) // 2}+18")
        else:
            if self._label:
                self._label.configure(text=message)
            if self._dot:
                self._dot.configure(fg=color)

        if self._blink_job:
            self._root.after_cancel(self._blink_job)
        self._blink(color)

    def _hide(self):
        if self._blink_job:
            self._root.after_cancel(self._blink_job)
            self._blink_job = None
        if self._win:
            self._win.destroy()
            self._win = None
            self._label = None
            self._dot = None

    def _blink(self, color: str):
        if self._win is None or self._dot is None:
            return
        current = self._dot.cget("fg")
        next_color = BG2 if current != BG2 else color
        self._dot.configure(fg=next_color)
        self._blink_job = self._root.after(550, self._blink, color)


# --------------------------------------------------------------------------- #
#  Settings window                                                             #
# --------------------------------------------------------------------------- #

class SettingsWindow:
    def __init__(self, config: dict, on_save=None):
        self.cfg = config.copy()
        self.on_save = on_save

        self.root = tk.Toplevel()
        self.root.title("freewispr — Settings")
        self.root.geometry("440x360")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        _style(self.root)

        self._build()

    def _build(self):
        pad = {"padx": 20, "pady": 6}

        ttk.Label(self.root, text="Settings", font=("Segoe UI", 13, "bold")).pack(anchor="w", **pad)

        # Hotkey
        ttk.Label(self.root, text="Dictation hotkey").pack(anchor="w", padx=20, pady=(12, 0))
        self._hotkey_var = tk.StringVar(value=self.cfg.get("hotkey", "ctrl+space"))
        ttk.Entry(self.root, textvariable=self._hotkey_var, width=30).pack(anchor="w", **pad)
        ttk.Label(self.root, text="e.g. ctrl+space, right ctrl, F9, alt+shift",
                  style="Sub.TLabel").pack(anchor="w", padx=20, pady=(0, 4))

        # Model size
        ttk.Label(self.root, text="Whisper model").pack(anchor="w", padx=20, pady=(8, 0))
        self._model_var = tk.StringVar(value=self.cfg.get("model_size", "base"))
        model_cb = ttk.Combobox(self.root, textvariable=self._model_var,
                                values=["tiny", "base", "small"], state="readonly", width=20)
        model_cb.pack(anchor="w", **pad)
        ttk.Label(self.root, text="tiny=fastest (~40MB)  base=balanced (~150MB)  small=best (~500MB)",
                  style="Sub.TLabel").pack(anchor="w", padx=20, pady=(0, 4))

        # Language
        ttk.Label(self.root, text="Language").pack(anchor="w", padx=20, pady=(8, 0))
        self._lang_var = tk.StringVar(value=self.cfg.get("language", "en"))
        ttk.Entry(self.root, textvariable=self._lang_var, width=10).pack(anchor="w", **pad)
        ttk.Label(self.root, text="ISO 639-1 code: en, es, fr, de, hi…",
                  style="Sub.TLabel").pack(anchor="w", padx=20, pady=(0, 4))

        # Filler word filter
        self._filler_var = tk.BooleanVar(value=self.cfg.get("filter_fillers", False))
        ttk.Checkbutton(
            self.root,
            text='Remove filler words ("um", "uh", "you know"…) from dictation',
            variable=self._filler_var,
        ).pack(anchor="w", padx=20, pady=(12, 2))

        # Save
        ttk.Button(self.root, text="Save", command=self._save).pack(anchor="e", padx=20, pady=16)

    def _save(self):
        self.cfg["hotkey"] = self._hotkey_var.get().strip()
        self.cfg["model_size"] = self._model_var.get()
        self.cfg["language"] = self._lang_var.get().strip()
        self.cfg["filter_fillers"] = self._filler_var.get()
        if self.on_save:
            self.on_save(self.cfg)
        self.root.destroy()
