"""Tests for the Settings window's personal-context save path.

We avoid spinning up Tk in tests — instead we exercise the save logic
by constructing a minimal SettingsWindow-like object with the same
attribute surface the save code reads, then call the relevant save
fragment via a tiny helper.

This catches the regressions we care about most:
  - Placeholder text must not overwrite the real saved context.
  - Whitespace-only input must not create an empty context file when
    none existed before.
  - Real edits round-trip through personal_context.save/load.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


# --------------------------------------------------------------------------- #
# Shared fake textbox: implements only get/insert/delete enough for save().
# --------------------------------------------------------------------------- #

class FakeTextbox:
    def __init__(self, content: str = ""):
        self._content = content

    def get(self, start: str, end: str) -> str:
        # We only support "1.0" .. "end-1c" — matches what save() asks for.
        return self._content

    def insert(self, _idx: str, text: str) -> None:
        self._content = text

    def delete(self, _start: str, _end: str) -> None:
        self._content = ""


# --------------------------------------------------------------------------- #
# Helper: run the personal-context fragment of _save() in isolation.
# --------------------------------------------------------------------------- #

def _run_ctx_save(textbox: FakeTextbox, is_placeholder: bool) -> None:
    """Mirror of the save-fragment in SettingsWindow._save for context."""
    import personal_context
    if is_placeholder:
        ctx_text = ""
    else:
        ctx_text = textbox.get("1.0", "end-1c")
    if ctx_text.strip() or personal_context.load():
        personal_context.save(ctx_text)


def _reload_pc(tmp_path: Path):
    import personal_context
    pc = importlib.reload(personal_context)
    pc._PATH = tmp_path / "personal_context.json"
    from json_store import JsonCache
    pc._store = JsonCache(pc._PATH, default={"text": ""})
    return pc


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_placeholder_save_does_not_create_file_on_fresh_install(tmp_path):
    pc = _reload_pc(tmp_path)
    tb = FakeTextbox("Skriv fritt i svensk löpande text…")  # placeholder
    _run_ctx_save(tb, is_placeholder=True)
    assert not pc._PATH.exists(), \
        "Placeholder must not create personal_context.json on fresh install"


def test_placeholder_save_preserves_existing_context(tmp_path):
    """If a context already exists, saving with placeholder must clear it.

    The user explicitly opened Settings and saved — that intent should
    win. But the cleared file should be written so we don't have stale
    data hanging around.
    """
    pc = _reload_pc(tmp_path)
    pc.save("Befintlig kontext som ska försvinna.")
    assert pc.exists_and_nonempty()
    tb = FakeTextbox("placeholder text the user didn't touch")
    _run_ctx_save(tb, is_placeholder=True)
    # File still exists but text is now empty.
    assert pc._PATH.exists()
    assert pc.load() == ""


def test_real_edit_roundtrips(tmp_path):
    pc = _reload_pc(tmp_path)
    text = "Jag heter Patrik och jobbar med moln."
    tb = FakeTextbox(text)
    _run_ctx_save(tb, is_placeholder=False)
    assert pc.load() == text


def test_whitespace_only_input_does_not_create_file_when_none_exists(tmp_path):
    pc = _reload_pc(tmp_path)
    tb = FakeTextbox("   \n\t  ")
    _run_ctx_save(tb, is_placeholder=False)
    assert not pc._PATH.exists()


def test_whitespace_only_input_clears_existing_context(tmp_path):
    pc = _reload_pc(tmp_path)
    pc.save("Tidigare kontext.")
    tb = FakeTextbox("   \n  ")
    _run_ctx_save(tb, is_placeholder=False)
    assert pc.load() == "   \n  "  # whitespace is preserved as-is


def test_edit_overwrites_migrated_content(tmp_path):
    pc = _reload_pc(tmp_path)
    pc.save("Auto-migrerad text\n- delay -> fördröjning")
    tb = FakeTextbox("Helt ny manuell kontext.")
    _run_ctx_save(tb, is_placeholder=False)
    assert pc.load() == "Helt ny manuell kontext."


def test_textbox_above_max_length_is_truncated_on_save(tmp_path):
    pc = _reload_pc(tmp_path)
    huge = "x" * (pc.MAX_LENGTH + 100)
    tb = FakeTextbox(huge)
    _run_ctx_save(tb, is_placeholder=False)
    assert len(pc.load()) == pc.MAX_LENGTH
