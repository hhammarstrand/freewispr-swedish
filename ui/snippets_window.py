"""
SnippetsWindow — manage trigger -> expansion pairs.
"""
import tkinter as tk
from tkinter import ttk, messagebox

import snippets as snippet_module

from ui.styles import BG, _style
from ui._ctk import ctk, _CTK_AVAILABLE
from ui.pair_dialog import _PairDialog


class SnippetsWindow:
    """
    Hantera snippet-bibliotek.
    Säg en trigger exakt -> den ersätts med fulltext.
    T.ex. "min adress" -> "Exempelvägen 123, 123 45 Staden"
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
