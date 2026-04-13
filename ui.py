"""
Tkinter-based windows for freewispr-swedish.
- FloatingIndicator : small always-on-top pill (recording / transcribing state)
- SnippetsWindow    : manage trigger → expansion pairs
- DictionaryWindow  : manage word corrections (Whisper mistakes)
- SettingsWindow    : hotkey, model, mic, GPU toggle
"""
import tkinter as tk
from tkinter import ttk, messagebox

import snippets as snippet_module
import corrections as corr_module
from audio import list_input_devices


BG = "#0f0f0f"
BG2 = "#1a1a1a"
ACC = "#7c5cfc"
ACC2 = "#5a3fd4"
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
    _COLORS = {
        "listen":      "#7c5cfc",
        "transcribe":  "#f39c12",
        "done":        "#27ae60",
        "error":       "#e74c3c",
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
        self.root = tk.Toplevel()
        self.root.title("freewispr-swedish — Snippets")
        self.root.geometry("640x420")
        self.root.configure(bg=BG)
        _style(self.root)
        self._build()
        self._load()

    def _build(self):
        # Header
        hdr = tk.Frame(self.root, bg=BG)
        hdr.pack(fill="x", padx=16, pady=(16, 4))
        ttk.Label(hdr, text="Snippets", font=("Segoe UI", 13, "bold")).pack(side="left")

        ttk.Label(
            self.root,
            text="Säg en trigger exakt vid diktering — den expanderar till fulltext.",
            style="Sub.TLabel",
        ).pack(anchor="w", padx=16, pady=(0, 10))

        # Treeview
        cols = ("trigger", "expansion")
        self._tree = ttk.Treeview(self.root, columns=cols, show="headings",
                                  selectmode="browse")
        self._tree.heading("trigger",   text="Trigger")
        self._tree.heading("expansion", text="Ersätter med")
        self._tree.column("trigger",   width=160, minwidth=100, stretch=False)
        self._tree.column("expansion", width=420, minwidth=200)
        self._tree.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        sb = ttk.Scrollbar(self.root, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)

        # Buttons
        btn_row = ttk.Frame(self.root)
        btn_row.pack(fill="x", padx=16, pady=(0, 16))
        ttk.Button(btn_row, text="Lägg till",    command=self._add).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Redigera",   command=self._edit).pack(side="left", padx=(0, 8))
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
        self.root = tk.Toplevel()
        self.root.title("freewispr-swedish — Personlig ordlista")
        self.root.geometry("580x400")
        self.root.configure(bg=BG)
        _style(self.root)
        self._build()
        self._load()

    def _build(self):
        hdr = tk.Frame(self.root, bg=BG)
        hdr.pack(fill="x", padx=16, pady=(16, 4))
        ttk.Label(hdr, text="Personlig ordlista", font=("Segoe UI", 13, "bold")).pack(side="left")

        ttk.Label(
            self.root,
            text="Ord som Whisper missförstår ersätts automatiskt efter transkribering.",
            style="Sub.TLabel",
        ).pack(anchor="w", padx=16, pady=(0, 10))

        cols = ("wrong", "right")
        self._tree = ttk.Treeview(self.root, columns=cols, show="headings",
                                  selectmode="browse")
        self._tree.heading("wrong", text="Whisper hör")
        self._tree.heading("right", text="Ersätt med")
        self._tree.column("wrong", width=230, minwidth=100, stretch=False)
        self._tree.column("right", width=310, minwidth=150)
        self._tree.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        sb = ttk.Scrollbar(self.root, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)

        btn_row = ttk.Frame(self.root)
        btn_row.pack(fill="x", padx=16, pady=(0, 16))
        ttk.Button(btn_row, text="Lägg till",    command=self._add).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Redigera",   command=self._edit).pack(side="left", padx=(0, 8))
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

# Tk keysym → human-readable name mapping for hotkey capture
_KEY_NAMES = {
    "Control_L": "ctrl", "Control_R": "right ctrl",
    "Alt_L": "alt", "Alt_R": "right alt",
    "Shift_L": "shift", "Shift_R": "right shift",
    "space": "space", "Return": "enter", "Escape": "esc",
    "Tab": "tab", "BackSpace": "backspace", "Delete": "delete",
    "Up": "up", "Down": "down", "Left": "left", "Right": "right",
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


class SettingsWindow:
    # Model descriptions shown when selecting
    _MODEL_INFO = {
        "tiny":   "Snabbast, lagst kvalitet (~40 MB)",
        "base":   "Snabb, grundlaggande kvalitet (~150 MB)",
        "small":  "Bra balans mellan hastighet och kvalitet (~500 MB)",
        "medium": "Hog kvalitet, langsammare (~1.5 GB)",
        "large":  "Basta kvalitet, krav mer minne (~3 GB)",
    }

    def __init__(self, config: dict, on_save=None):
        self.cfg = config.copy()
        self.on_save = on_save

        self.root = tk.Toplevel()
        self.root.title("freewispr-swedish \u2014 Installningar")
        self.root.geometry("500x520")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        _style(self.root)

        self._build()

    # -- helpers ------------------------------------------------------------- #

    def _card(self, parent) -> tk.Frame:
        """Card with a subtle left accent border."""
        wrapper = tk.Frame(parent, bg=ACC, padx=0, pady=0)
        wrapper.pack(fill="x", padx=24, pady=(0, 14))

        # 3px accent stripe on the left
        inner = tk.Frame(wrapper, bg=BG2, padx=18, pady=14)
        inner.pack(fill="both", expand=True, padx=(3, 0))
        return inner

    def _section_label(self, parent, text):
        lbl = tk.Label(parent, text=text, bg=BG2, fg=ACC,
                       font=("Segoe UI Semibold", 10))
        lbl.pack(anchor="w")

    def _hint(self, parent, text):
        lbl = tk.Label(parent, text=text, bg=BG2, fg=FG2,
                       font=("Segoe UI", 9))
        lbl.pack(anchor="w", pady=(2, 0))

    def _toggle(self, parent, text, variable):
        """Custom styled toggle row — cleaner than ttk.Checkbutton."""
        row = tk.Frame(parent, bg=BG2, cursor="hand2")
        row.pack(fill="x", pady=(8, 0))

        indicator = tk.Label(row, bg=BG2, fg=FG2,
                             font=("Segoe UI", 11), width=2, anchor="center")
        indicator.pack(side="left")

        label = tk.Label(row, text=text, bg=BG2, fg=FG,
                         font=("Segoe UI", 10), anchor="w")
        label.pack(side="left", fill="x", expand=True)

        def _update_look(*_):
            if variable.get():
                indicator.configure(text="\u25c9", fg=ACC)  # ◉
            else:
                indicator.configure(text="\u25cb", fg=FG2)  # ○

        def _click(_=None):
            variable.set(not variable.get())

        _update_look()
        variable.trace_add("write", _update_look)
        for w in (row, indicator, label):
            w.bind("<Button-1>", _click)

        return row

    # -- build --------------------------------------------------------------- #

    def _build(self):
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True)

        # Title bar
        hdr = tk.Frame(outer, bg=BG)
        hdr.pack(fill="x", padx=24, pady=(22, 18))
        tk.Label(hdr, text="Installningar", bg=BG, fg=FG,
                 font=("Segoe UI", 15, "bold")).pack(side="left")
        tk.Label(hdr, text="freewispr-swedish", bg=BG, fg=FG2,
                 font=("Segoe UI", 9)).pack(side="right", pady=(5, 0))

        # -- Card: Dikteringstangent ---------------------------------------- #
        card = self._card(outer)
        self._section_label(card, "Dikteringstangent")
        self._hint(card, "Klicka och tryck onskad tangentkombination")

        self._hotkey_var = tk.StringVar(value=self.cfg.get("hotkey", "ctrl+space"))
        hk = _HotkeyCapture(card, self._hotkey_var)
        hk.pack(fill="x", pady=(8, 0))

        # -- Card: Mikrofon ------------------------------------------------- #
        card = self._card(outer)
        self._section_label(card, "Mikrofon")

        self._mic_devices = list_input_devices()
        mic_names = ["Auto"] + [d["name"] for d in self._mic_devices]
        saved_mic = self.cfg.get("mic_device") or ""

        self._mic_var = tk.StringVar(value=saved_mic if saved_mic else "Auto")
        mic_combo = ttk.Combobox(card, textvariable=self._mic_var,
                                 values=mic_names, state="readonly", width=48)
        mic_combo.pack(fill="x", pady=(8, 0))

        self._mic_info = tk.Label(card, text="", bg=BG2, fg=FG2,
                                  font=("Segoe UI", 8))
        self._mic_info.pack(anchor="w", pady=(3, 0))
        mic_combo.bind("<<ComboboxSelected>>", self._on_mic_change)
        self._on_mic_change()

        # -- Card: Modell & GPU --------------------------------------------- #
        card = self._card(outer)
        self._section_label(card, "Whisper-modell")

        # Model selector
        model_row = tk.Frame(card, bg=BG2)
        model_row.pack(fill="x", pady=(8, 0))

        self._model_var = tk.StringVar(value=self.cfg.get("model_size", "small"))
        combo = ttk.Combobox(model_row, textvariable=self._model_var,
                             values=["tiny", "base", "small", "medium", "large"],
                             state="readonly", width=14)
        combo.pack(side="left")

        self._model_desc = tk.Label(model_row, text="", bg=BG2, fg=FG2,
                                    font=("Segoe UI", 9))
        self._model_desc.pack(side="left", padx=(12, 0))
        combo.bind("<<ComboboxSelected>>", self._on_model_change)
        self._on_model_change()

        # GPU toggle
        self._cuda_var = tk.BooleanVar(value=self.cfg.get("use_cuda", True))
        self._toggle(card, "Anvand GPU/CUDA (snabbare med NVIDIA)", self._cuda_var)

        # -- Buttons -------------------------------------------------------- #
        btn_frame = tk.Frame(outer, bg=BG)
        btn_frame.pack(fill="x", padx=24, pady=(8, 22))

        save_btn = tk.Button(
            btn_frame, text="Spara", bg=ACC, fg=FG,
            font=("Segoe UI Semibold", 10), relief="flat",
            activebackground=ACC2, activeforeground=FG,
            padx=24, pady=6, cursor="hand2",
            command=self._save,
        )
        save_btn.pack(side="right")

        cancel_btn = tk.Button(
            btn_frame, text="Avbryt", bg=BG3, fg=FG2,
            font=("Segoe UI", 10), relief="flat",
            activebackground="#333", activeforeground=FG,
            padx=18, pady=6, cursor="hand2",
            command=self.root.destroy,
        )
        cancel_btn.pack(side="right", padx=(0, 10))

    def _on_model_change(self, _=None):
        model = self._model_var.get()
        desc = self._MODEL_INFO.get(model, "")
        self._model_desc.configure(text=desc)

    def _on_mic_change(self, _=None):
        name = self._mic_var.get()
        if name == "Auto":
            self._mic_info.configure(text="Valjer basta tillgangliga mikrofon automatiskt")
            return
        for d in self._mic_devices:
            if d["name"] == name:
                self._mic_info.configure(
                    text=f"{d['api']}  \u2502  {d['rate']} Hz  \u2502  {d['channels']} ch"
                )
                return
        self._mic_info.configure(text="")

    def _save(self):
        self.cfg["hotkey"] = self._hotkey_var.get().strip()
        self.cfg["model_size"] = self._model_var.get()
        self.cfg["use_cuda"] = self._cuda_var.get()
        mic = self._mic_var.get()
        self.cfg["mic_device"] = None if mic == "Auto" else mic
        # Clean out removed keys from old configs
        self.cfg.pop("filter_fillers", None)
        self.cfg.pop("auto_punctuate", None)
        self.cfg.pop("language", None)
        if self.on_save:
            self.on_save(self.cfg)
        self.root.destroy()
