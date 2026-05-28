"""
Tkinter-based windows for freewispr-swedish.
- FloatingIndicator : small always-on-top pill (recording / transcribing state)
- SnippetsWindow    : manage trigger -> expansion pairs
- DictionaryWindow  : manage word corrections (Whisper mistakes)
- SettingsWindow    : hotkey, mic, model, LLM och transkribering
- FirstRunDialog    : welcome dialog offering to download the Whisper model
"""

from ui.styles import _style
from ui.indicator import FloatingIndicator

__all__ = [
    "FloatingIndicator",
    "SettingsWindow",
    "SnippetsWindow",
    "DictionaryWindow",
    "FirstRunDialog",
    "_style",
]


def __getattr__(name):
    if name == "SettingsWindow":
        from ui.settings_window import SettingsWindow
        return SettingsWindow
    if name == "SnippetsWindow":
        from ui.snippets_window import SnippetsWindow
        return SnippetsWindow
    if name == "DictionaryWindow":
        from ui.dictionary_window import DictionaryWindow
        return DictionaryWindow
    if name == "FirstRunDialog":
        from ui.first_run import FirstRunDialog
        return FirstRunDialog
    raise AttributeError(f"module 'ui' has no attribute {name!r}")
