"""
Shared colour constants, font, and ttk style setup for freewispr-swedish UI.
"""
from tkinter import ttk

BG = "#111318"
BG2 = "#1a1d24"
BG3 = "#24272e"
ACC = "#006aa7"
ACC2 = "#0080cc"
FG = "#eaedf2"
FG2 = "#8891a0"
FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI Semibold", 10)
FONT_SMALL = ("Segoe UI", 9)
RADIUS = 8


def _style(root):
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure("TButton", background=ACC, foreground=FG, font=FONT_BOLD,
                relief="flat", padding=(16, 8))
    s.map("TButton", background=[("active", ACC2)])
    s.configure("Danger.TButton", background="#c0392b", foreground=FG,
                font=FONT_BOLD, relief="flat", padding=(16, 8))
    s.map("Danger.TButton", background=[("active", "#e74c3c")])
    s.configure("TLabel", background=BG, foreground=FG, font=FONT)
    s.configure("Sub.TLabel", background=BG, foreground=FG2, font=FONT_SMALL)
    s.configure("Card.TLabel", background=BG2, foreground=FG, font=FONT)
    s.configure("CardSub.TLabel", background=BG2, foreground=FG2, font=FONT_SMALL)
    s.configure("CardHead.TLabel", background=BG2, foreground=ACC,
                font=("Segoe UI Semibold", 10))
    s.configure("TFrame", background=BG)
    s.configure("Card.TFrame", background=BG2)
    s.configure("TEntry", fieldbackground=BG3, foreground=FG, font=FONT,
                insertcolor=FG, borderwidth=1, relief="flat")
    s.map("TEntry",
          fieldbackground=[("focus", BG3), ("!focus", BG3)],
          foreground=[("focus", FG), ("!focus", FG)],
          bordercolor=[("focus", ACC), ("!focus", "#3a3f4a")])
    s.configure("TCombobox", fieldbackground=BG3, foreground=FG, font=FONT,
                borderwidth=1, relief="flat")
    s.map("TCombobox",
          fieldbackground=[("readonly", BG3)],
          foreground=[("readonly", FG)],
          bordercolor=[("focus", ACC), ("!focus", "#3a3f4a")])
    s.configure("TCheckbutton", background=BG2, foreground=FG, font=FONT)
    s.map("TCheckbutton", background=[("active", BG2)])
    s.configure("Treeview",
                background=BG2, foreground=FG,
                fieldbackground=BG2, font=FONT,
                rowheight=32, borderwidth=0, relief="flat")
    s.configure("Treeview.Heading",
                background=BG, foreground=FG2,
                font=FONT_SMALL, relief="flat")
    s.map("Treeview",
          background=[("selected", ACC)],
          foreground=[("selected", FG)])

    root.option_add("*TCombobox*Listbox.background", BG3)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACC)
    root.option_add("*TCombobox*Listbox.selectForeground", FG)
