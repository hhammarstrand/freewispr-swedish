"""
Shared colour constants, font, and ttk style setup for freewispr-swedish UI.
"""
from tkinter import ttk

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
