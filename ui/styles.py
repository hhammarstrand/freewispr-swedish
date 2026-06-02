"""
Shared colour constants, font, and ttk style setup for freewispr-swedish UI.
"""
import logging
import sys
from pathlib import Path
from tkinter import ttk

log = logging.getLogger(__name__)

# Resolve once at import time. The .ico lives in the repo at assets/icon.ico
# and is bundled into the frozen app under the same relative assets path.
def _resolve_icon_path() -> Path:
    return Path(__file__).resolve().parent.parent / "assets" / "icon.ico"


# Windows AppUserModelID. Without this, Windows groups our pythonw.exe
# process under Python's own AUMID and shows the Python logo in the
# taskbar regardless of which icon we set on individual windows.
# Reverse-DNS style is the Microsoft convention.
_APP_USER_MODEL_ID = "se.freewispr.swedish.app"

# Holds the PhotoImage for iconphoto() — Tk requires us to keep a strong
# reference to the image or it gets garbage-collected and the icon
# silently reverts.
_root_photo = None


def _set_app_user_model_id() -> None:
    """Tell Windows we're our own app, not pythonw.exe, so the taskbar
    icon is what we set on our root window — not the Python logo."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            _APP_USER_MODEL_ID)
    except Exception as exc:  # pragma: no cover - platform specific
        log.debug("Kunde inte sätta AppUserModelID: %s", exc)


def _load_largest_ico_frame_as_photo(root):
    """Load the largest frame in our .ico as a Tk PhotoImage.

    Windows taskbar wants a 32x32 (or larger) RGBA image. iconbitmap()
    handles .ico fine for the titlebar, but for the taskbar/Alt-Tab
    Windows uses the iconphoto() image — so we extract the biggest
    frame from the .ico via Pillow and hand it to Tk.
    """
    icon_path = _resolve_icon_path()
    if not icon_path.exists():
        return None
    try:
        from PIL import Image, ImageTk
        with Image.open(icon_path) as im:
            # .ico containers expose sizes via im.ico.entry; pick the largest.
            try:
                sizes = im.ico.sizes()
                best = max(sizes, key=lambda s: s[0] * s[1])
                im.size = best  # triggers loading that frame
            except Exception:
                # Some Pillow versions/ico files don't expose .ico; the
                # default frame is the first one which is usually small
                # but better than nothing.
                pass
            im.load()
            return ImageTk.PhotoImage(im.convert("RGBA"), master=root)
    except Exception as exc:  # pragma: no cover - depends on Pillow build
        log.debug("Kunde inte ladda .ico som PhotoImage: %s", exc)
        return None


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
    icon_path = _resolve_icon_path()
    if not icon_path.exists():
        log.debug("Ikon saknas: %s", icon_path)
        return

    path_str = str(icon_path)

    def _set_icon() -> None:
        try:
            # Per-window binding wins over the process-wide default that
            # CustomTkinter sets via wm_iconbitmap(default=...).
            window.iconbitmap(path_str)
        except Exception as exc:  # pragma: no cover - tk raises platform specific
            log.debug("iconbitmap misslyckades: %s", exc)
        # Re-apply the PhotoImage too. iconbitmap controls the titlebar;
        # iconphoto controls the taskbar / Alt-Tab on Windows.
        global _root_photo
        if _root_photo is None:
            _root_photo = _load_largest_ico_frame_as_photo(window)
        if _root_photo is not None:
            try:
                window.iconphoto(False, _root_photo)
            except Exception as exc:
                log.debug("iconphoto på Toplevel misslyckades: %s", exc)

    _set_icon()
    try:
        # CTk schedules its own icon override at ~200 ms after window init.
        # 500 ms lands well after it, before the user has time to notice.
        window.after(500, _set_icon)
    except Exception as exc:  # pragma: no cover
        log.debug("after() för ikon-reset misslyckades: %s", exc)


def apply_root_icon(root) -> None:
    """Set the process-wide default icon on the hidden tk root, plus
    register our AppUserModelID so Windows groups the taskbar entry
    under us instead of pythonw.exe.

    This bubbles down to any new Toplevel that doesn't explicitly set
    its own. We call ``apply_window_icon`` on the user-visible Toplevels
    anyway because CustomTkinter will steamroll the titlebar default,
    but the taskbar icon (which comes from iconphoto + AUMID) needs to
    be right from the start.
    """
    _set_app_user_model_id()
    icon_path = _resolve_icon_path()
    if not icon_path.exists():
        return
    try:
        root.iconbitmap(default=str(icon_path))
    except Exception as exc:  # pragma: no cover
        log.debug("Kunde inte sätta default-ikon på root: %s", exc)
    # Load PhotoImage once and stash a strong ref. Apply to root and to
    # every future Toplevel via apply_window_icon's _set_icon path.
    global _root_photo
    _root_photo = _load_largest_ico_frame_as_photo(root)
    if _root_photo is not None:
        try:
            # True = also use for all future Toplevels by default.
            root.iconphoto(True, _root_photo)
        except Exception as exc:  # pragma: no cover
            log.debug("iconphoto på root misslyckades: %s", exc)

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
