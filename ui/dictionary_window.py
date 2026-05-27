"""
DictionaryWindow — manage personal word corrections (Whisper mistakes).
"""
import tkinter as tk
from tkinter import ttk, messagebox

import corrections as corr_module

from ui.styles import BG, _style
from ui._ctk import ctk, _CTK_AVAILABLE
from ui.pair_dialog import _PairDialog


class DictionaryWindow:
    """
    Hantera personliga ordkorrigeringar.
    Whispers output skannas och matchande ord ersätts automatiskt.
    T.ex. "fritspr" -> "freewispr-swedish", "prak" -> "Prakhar"
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
