"""
Shared CustomTkinter detection for freewispr-swedish UI modules.

Modules that need ``ctk`` and ``_CTK_AVAILABLE`` import from here so the
try/except lives in exactly one place.
"""

try:
    import customtkinter as ctk
    _CTK_AVAILABLE = True
except Exception:
    ctk = None
    _CTK_AVAILABLE = False
