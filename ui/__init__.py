"""
Tkinter-based windows for freewispr-swedish.
- FloatingIndicator : small always-on-top pill (recording / transcribing state)
- SettingsWindow    : hotkey, mic, model, LLM, kontext och transkribering
- FirstRunDialog    : welcome dialog offering to download the Whisper model
"""

from ui.styles import _style
from ui.indicator import FloatingIndicator

__all__ = [
    "FloatingIndicator",
    "SettingsWindow",
    "FirstRunDialog",
    "_style",
]


def __getattr__(name):
    if name == "SettingsWindow":
        from ui.settings_window import SettingsWindow
        return SettingsWindow
    if name == "FirstRunDialog":
        from ui.first_run import FirstRunDialog
        return FirstRunDialog
    raise AttributeError(f"module 'ui' has no attribute {name!r}")
