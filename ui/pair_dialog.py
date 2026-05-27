"""
_PairDialog — modal dialog with two fields (trigger/key + longer value).
"""
import tkinter as tk
from tkinter import ttk, messagebox

from ui.styles import BG, BG2, FG, FG2, ACC, FONT, _style


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
