"""
_HotkeyCapture widget — clickable frame that captures key combinations.
"""
import tkinter as tk

from ui.styles import BG3, FG, FG2, ACC

# Tk keysym -> human-readable name mapping for hotkey capture.
# Only keysyms whose lowercase form differs from the wanted display name
# are listed here; everything else falls through to ``event.keysym.lower()``.
_KEY_NAMES = {
    "Control_L": "ctrl", "Control_R": "right ctrl",
    "Alt_L": "alt", "Alt_R": "right alt",
    "Shift_L": "shift", "Shift_R": "right shift",
    "Return": "enter", "Escape": "esc",
    "BackSpace": "backspace",
}


class _HotkeyCapture(tk.Frame):
    """A clickable widget that captures key combinations."""

    def __init__(self, parent, variable: tk.StringVar, **kw):
        super().__init__(parent, bg=BG3, highlightthickness=1,
                         highlightbackground=FG2, highlightcolor=ACC,
                         padx=12, pady=8, cursor="hand2")
        self._var = variable
        self._capturing = False
        self._held: dict[str, str] = {}  # keysym -> display name

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
        self._display.configure(text=val if val else "…")
        if not self._capturing:
            self._hint.configure(text="klicka för att ändra")

    def _start_capture(self, _=None):
        self._capturing = True
        self._held.clear()
        self.configure(highlightbackground=ACC, highlightcolor=ACC)
        self._display.configure(text="…", fg=ACC)
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
