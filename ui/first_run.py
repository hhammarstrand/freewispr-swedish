"""
FirstRunDialog — welcome dialog shown when the user has no Whisper model
downloaded yet. Offers to download and convert a KBLab model in the
background and reports progress back to the user.

Public contract:
    dlg = FirstRunDialog(parent)   # blocks until closed
    if dlg.result is not None:
        # user picked dlg.result (e.g. "small") and the download completed
"""
from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import ttk

from ui.styles import BG, BG3, FG, FG2, ACC, ACC2, FONT, _style, apply_window_icon
from ui._ctk import ctk, _CTK_AVAILABLE

log = logging.getLogger("freewispr")


# Model-size catalogue shown in the picker. Keys mirror convert_model.KBLAB_MODELS.
# The label/desc pair drives both the radio button text and the description hint.
_MODEL_CHOICES: list[tuple[str, str, str]] = [
    ("tiny",   "tiny",                   "Snabbast, ~40 MB, lägre precision"),
    ("base",   "base",                   "Liten och snabb, ~150 MB"),
    ("small",  "small (rekommenderad)",  "~500 MB, bra balans"),
    ("medium", "medium",                 "~1.5 GB, hög precision"),
    ("large",  "large",                  "~3 GB, bäst kvalitet"),
]


class FirstRunDialog:
    """Modal welcome dialog. Shows download progress while convert_model
    runs in a background thread. Exposes the chosen size via ``result``
    once the download succeeds.
    """

    def __init__(self, parent):
        self._parent = parent
        self.result: str | None = None

        # Worker state
        self._worker: threading.Thread | None = None
        self._cancelled = False

        # ctk follows OS appearance; settings_window uses the same call.
        if _CTK_AVAILABLE:
            try:
                ctk.set_appearance_mode("system")
                ctk.set_default_color_theme("blue")
            except Exception:
                pass
            self.root = ctk.CTkToplevel(parent) if parent is not None else ctk.CTkToplevel()
        else:
            self.root = tk.Toplevel(parent) if parent is not None else tk.Toplevel()

        self.root.title("Välkommen till freewispr-swedish")
        self.root.geometry("520x540")
        self.root.minsize(480, 500)
        self.root.resizable(False, False)
        apply_window_icon(self.root)

        if not _CTK_AVAILABLE:
            self.root.configure(bg=BG)
            _style(self.root)

        # Selected model size — defaults to "small".
        self._size_var = tk.StringVar(value="small")
        # Status text shown next to (or above) the progress bar.
        self._status_var = tk.StringVar(value="")

        self._build()

        # Modal: block the parent window's input and wait for close.
        try:
            if parent is not None:
                self.root.transient(parent)
        except Exception:
            pass
        try:
            self.root.grab_set()
        except Exception:
            pass

        self.root.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # Block the caller until the dialog is closed. This mirrors how
        # _PairDialog and similar modal dialogs behave.
        try:
            self.root.wait_window()
        except Exception:
            # If wait_window can't run (no event loop), the caller just gets
            # whatever ``result`` happened to be set to.
            pass

    # -- widget helpers (ctk + tk fallback) ---------------------------------- #

    def _frame(self, parent, **kw):
        if _CTK_AVAILABLE:
            return ctk.CTkFrame(parent, fg_color="transparent", **kw)
        return tk.Frame(parent, bg=BG, **kw)

    def _label(self, parent, text, *, bold=False, heading=False, sub=False,
               wraplength: int | None = None):
        if _CTK_AVAILABLE:
            if heading:
                font = ctk.CTkFont(size=16, weight="bold")
                color = None
            elif bold:
                font = ctk.CTkFont(weight="bold")
                color = None
            elif sub:
                font = ctk.CTkFont(size=11)
                color = ("gray40", "gray60")
            else:
                font = ctk.CTkFont(size=12)
                color = None
            kw = {"text": text, "anchor": "w", "font": font, "justify": "left"}
            if color is not None:
                kw["text_color"] = color
            if wraplength is not None:
                kw["wraplength"] = wraplength
            return ctk.CTkLabel(parent, **kw)
        # Plain tk fallback.
        if heading:
            font = ("Segoe UI", 13, "bold")
            fg_ = FG
        elif bold:
            font = ("Segoe UI Semibold", 10)
            fg_ = FG
        elif sub:
            font = ("Segoe UI", 9)
            fg_ = FG2
        else:
            font = FONT
            fg_ = FG
        kw = {"text": text, "bg": BG, "fg": fg_, "font": font,
              "anchor": "w", "justify": "left"}
        if wraplength is not None:
            kw["wraplength"] = wraplength
        return tk.Label(parent, **kw)

    def _button(self, parent, text, command, *, primary=False):
        if _CTK_AVAILABLE:
            kw = {"text": text, "command": command}
            if not primary:
                kw["fg_color"] = "transparent"
                kw["border_width"] = 1
                kw["text_color"] = ("gray20", "gray80")
            return ctk.CTkButton(parent, **kw)
        bg = ACC if primary else BG3
        fg_ = FG if primary else FG2
        return tk.Button(parent, text=text, bg=bg, fg=fg_, relief="flat",
                         font=("Segoe UI Semibold", 10) if primary else FONT,
                         activebackground=ACC2 if primary else "#333",
                         activeforeground=FG, padx=18, pady=6, cursor="hand2",
                         command=command)

    def _progressbar(self, parent):
        if _CTK_AVAILABLE:
            # Indeterminate animation; convert_model.convert() doesn't expose
            # progress, so a busy bar is the most honest signal.
            bar = ctk.CTkProgressBar(parent, mode="indeterminate")
            return bar
        bar = ttk.Progressbar(parent, mode="indeterminate", length=320)
        return bar

    def _radio(self, parent, value, text, description):
        """Single radio-row: large button label + faint description hint."""
        row = self._frame(parent)
        if _CTK_AVAILABLE:
            rb = ctk.CTkRadioButton(
                row, text=text, variable=self._size_var, value=value,
            )
            rb.pack(anchor="w")
            desc = ctk.CTkLabel(
                row, text=description, anchor="w", justify="left",
                font=ctk.CTkFont(size=11),
                text_color=("gray40", "gray60"),
            )
            desc.pack(anchor="w", padx=(28, 0))
            self._radio_widgets.append(rb)
        else:
            rb = tk.Radiobutton(
                row, text=text, variable=self._size_var, value=value,
                bg=BG, fg=FG, font=("Segoe UI", 10),
                activebackground=BG, activeforeground=FG,
                selectcolor=BG3, anchor="w",
            )
            rb.pack(anchor="w")
            desc = tk.Label(
                row, text=description, bg=BG, fg=FG2,
                font=("Segoe UI", 9), anchor="w", justify="left",
            )
            desc.pack(anchor="w", padx=(28, 0))
            self._radio_widgets.append(rb)
        return row

    # -- build --------------------------------------------------------------- #

    def _build(self):
        outer = self._frame(self.root)
        outer.pack(fill="both", expand=True, padx=22, pady=22)

        # Heading
        self._label(outer, "Ladda ned svensk Whisper-modell",
                    heading=True).pack(anchor="w", pady=(0, 8))

        # Body explanation
        self._label(
            outer,
            "För att kunna diktera behöver appen en svensk Whisper-modell "
            "från KBLab. Välj storlek nedan — du kan byta senare i "
            "inställningarna.",
            sub=True, wraplength=460,
        ).pack(anchor="w", pady=(0, 14))

        # Radio rows
        self._radio_widgets: list = []
        radios = self._frame(outer)
        radios.pack(fill="x", anchor="w")
        for value, text, desc in _MODEL_CHOICES:
            self._radio(radios, value, text, desc).pack(
                anchor="w", fill="x", pady=(2, 6)
            )

        # Progress bar — built hidden; shown only after the user clicks Ladda ned.
        self._progress = self._progressbar(outer)
        # Don't pack yet — _start_download() does it.

        # Status label — sits above the buttons; also hidden until we have
        # something to say.
        self._status_label = self._label(outer, "", sub=True, wraplength=460)
        # Same: packed lazily.

        # Button row — packed last so the progress bar / status label
        # (added lazily on download) sit above it in natural top-down order.
        self._btn_row = self._frame(outer)
        self._btn_row.pack(fill="x", pady=(18, 0))
        self._cancel_btn = self._button(self._btn_row, "Avbryt", self._on_cancel)
        self._cancel_btn.pack(side="right", padx=(8, 0))
        self._download_btn = self._button(
            self._btn_row, "Ladda ned", self._on_download, primary=True,
        )
        self._download_btn.pack(side="right")

    # -- actions ------------------------------------------------------------- #

    def _set_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for btn in (self._download_btn, self._cancel_btn):
            try:
                btn.configure(state=state)
            except Exception:
                pass
        for rb in self._radio_widgets:
            try:
                rb.configure(state=state)
            except Exception:
                pass

    def _show_status(self, text: str) -> None:
        """Set status text and make sure the label is visible."""
        self._status_var.set(text)
        try:
            self._status_label.configure(text=text)
        except Exception:
            pass
        if not self._status_label.winfo_ismapped():
            self._status_label.pack(anchor="w", pady=(12, 0), before=self._btn_row)

    def _show_progress(self) -> None:
        if not self._progress.winfo_ismapped():
            self._progress.pack(fill="x", pady=(12, 0),
                                before=self._status_label if self._status_label.winfo_ismapped()
                                else self._btn_row)
        try:
            if _CTK_AVAILABLE:
                self._progress.configure(mode="indeterminate")
                self._progress.start()
            else:
                self._progress.configure(mode="indeterminate")
                self._progress.start(12)
        except Exception:
            pass

    def _stop_progress(self) -> None:
        try:
            self._progress.stop()
        except Exception:
            pass
        try:
            if self._progress.winfo_ismapped():
                self._progress.pack_forget()
        except Exception:
            pass

    def _on_download(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        size = self._size_var.get() or "small"
        log.info("FirstRunDialog: användaren valde modell '%s'", size)
        self._set_buttons_enabled(False)
        self._show_progress()
        self._show_status(
            "Laddar ned och konverterar modellen — det här kan ta några minuter..."
        )

        def _run():
            try:
                # convert_model.convert() is idempotent and writes to
                # ~/.freewispr-swedish/models/kb-whisper-{size}-ct2/
                import convert_model
                convert_model.convert(size)
            except BaseException as err:  # noqa: BLE001 — surface everything to UI
                log.error("Modell-nedladdning misslyckades: %s", err, exc_info=True)
                err_msg = str(err) or err.__class__.__name__
                self._schedule(lambda msg=err_msg: self._on_failure(msg))
                return
            self._schedule(lambda: self._on_success(size))

        self._worker = threading.Thread(
            target=_run, name="first-run-download", daemon=True,
        )
        self._worker.start()

    def _schedule(self, fn) -> None:
        """Marshal a callback onto the Tk main thread."""
        try:
            self.root.after(0, fn)
        except Exception:
            # Window already destroyed; the user cancelled and we can't
            # update anything meaningful. Just drop the callback.
            pass

    def _on_success(self, size: str) -> None:
        self._stop_progress()
        self._show_status("Klar! Du kan börja diktera nu.")
        self.result = size
        # Close after a short pause so the user sees the success message.
        try:
            self.root.after(2000, self._destroy_safely)
        except Exception:
            self._destroy_safely()

    def _on_failure(self, msg: str) -> None:
        self._stop_progress()
        self._show_status(
            f"Det gick inte att ladda ned modellen: {msg}\n"
            "Försök igen eller avbryt och installera modellen manuellt med "
            "'python convert_model.py {size}'.".replace(
                "{size}", self._size_var.get() or "small"
            )
        )
        self._set_buttons_enabled(True)

    def _on_cancel(self) -> None:
        # If a download is mid-flight we can't actually stop convert_model
        # (it's blocking C code), so just detach from the worker and close.
        # The thread is a daemon and will die with the process.
        self._cancelled = True
        log.info("FirstRunDialog: avbruten av användaren")
        self._destroy_safely()

    def _destroy_safely(self) -> None:
        try:
            self.root.grab_release()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
