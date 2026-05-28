"""
Shared colour constants, font, and ttk style setup for freewispr-swedish UI.
"""
import logging
from pathlib import Path
from tkinter import ttk

log = logging.getLogger(__name__)

# Resolve once at import time. The .ico lives in the repo at assets/icon.ico
# and is bundled into the frozen app under the same relative assets path.
_ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"


def apply_window_icon(window) -> None:
    """Set the taskbar / titlebar icon on a Toplevel window.

    Tkinter defaults to the Python interpreter's icon and CustomTkinter's
    ``CTkToplevel`` actively overrides it with its own blue rounded-square
    after a ~200 ms ``after()`` callback. We need to win that race.

    Strategy:
      1. Set the icon immediately (covers plain tk.Toplevel).
      2. Re-set it at 500 ms — comfortably after CustomTkinter's 200 ms
         override has fired — to take the final word on CTk windows.
      3. Both calls use the per-window form ``iconbitmap(path)`` (not the
         ``default=`` form, which only acts as a process-wide fallback that
         CTk happily overwrites again).

    Failures are logged at debug level and never raised — a wrong icon
    must not break the UI.
    """
    if not _ICON_PATH.exists():
        log.debug("Ikon saknas: %s", _ICON_PATH)
        return

    path_str = str(_ICON_PATH)

    def _set_icon() -> None:
        try:
            # Per-window binding wins over the process-wide default that
            # CustomTkinter sets via wm_iconbitmap(default=...).
            window.iconbitmap(path_str)
        except Exception as exc:  # pragma: no cover - tk raises platform specific
            log.debug("iconbitmap misslyckades: %s", exc)

    _set_icon()
    try:
        # CTk schedules its own icon override at ~200 ms after window init.
        # 500 ms lands well after it, before the user has time to notice.
        window.after(500, _set_icon)
    except Exception as exc:  # pragma: no cover
        log.debug("after() för ikon-reset misslyckades: %s", exc)


def apply_root_icon(root) -> None:
    """Set the process-wide default icon on the hidden tk root.

    This bubbles down to any new Toplevel that doesn't explicitly set its
    own. We call ``apply_window_icon`` on the user-visible Toplevels
    anyway because CustomTkinter will steamroll this default, but having
    it on the root covers any window we don't manually decorate.
    """
    if not _ICON_PATH.exists():
        return
    try:
        root.iconbitmap(default=str(_ICON_PATH))
    except Exception as exc:  # pragma: no cover
        log.debug("Kunde inte sätta default-ikon på root: %s", exc)

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
