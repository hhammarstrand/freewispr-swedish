"""
Tkinter-based windows for freewispr-swedish.
- FloatingIndicator : small always-on-top pill (recording / transcribing state)
- SnippetsWindow    : manage trigger -> expansion pairs
- DictionaryWindow  : manage word corrections (Whisper mistakes)
- SettingsWindow    : hotkey, model, mic, GPU toggle
"""

from ui.styles import _style
from ui.indicator import FloatingIndicator
from ui.snippets_window import SnippetsWindow
from ui.dictionary_window import DictionaryWindow
from ui.settings_window import SettingsWindow

__all__ = [
    "FloatingIndicator",
    "SettingsWindow",
    "SnippetsWindow",
    "DictionaryWindow",
    "_style",
]
