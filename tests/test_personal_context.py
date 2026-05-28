"""Tests for the personal_context module and the one-shot migration.

These avoid touching the real ~/.freewispr-swedish/ directory by
monkeypatching the module-level _PATH / source paths to a tmp_path,
then reloading the module so JsonCache picks up the new path.
"""
import importlib
import json
from pathlib import Path

import pytest


# --------------------------------------------------------------------------- #
# personal_context
# --------------------------------------------------------------------------- #

def _reload_personal_context(tmp_path: Path):
    """Reload personal_context with its store pointed at tmp_path."""
    import personal_context
    pc = importlib.reload(personal_context)
    pc._PATH = tmp_path / "personal_context.json"
    from json_store import JsonCache
    pc._store = JsonCache(pc._PATH, default={"text": ""})
    return pc


def test_load_returns_empty_string_when_file_missing(tmp_path):
    pc = _reload_personal_context(tmp_path)
    assert pc.load() == ""
    assert pc.exists_and_nonempty() is False


def test_save_then_load_roundtrip(tmp_path):
    pc = _reload_personal_context(tmp_path)
    pc.save("Jag heter Patrik och jobbar med molnplattformar.")
    assert pc.load() == "Jag heter Patrik och jobbar med molnplattformar."
    assert pc.exists_and_nonempty() is True


def test_save_truncates_to_max_length(tmp_path):
    pc = _reload_personal_context(tmp_path)
    huge = "a" * (pc.MAX_LENGTH + 5000)
    pc.save(huge)
    assert len(pc.load()) == pc.MAX_LENGTH


def test_save_non_string_coerced_to_empty(tmp_path):
    pc = _reload_personal_context(tmp_path)
    pc.save(None)  # type: ignore[arg-type]
    assert pc.load() == ""


def test_exists_and_nonempty_treats_whitespace_as_empty(tmp_path):
    pc = _reload_personal_context(tmp_path)
    pc.save("   \n\t  ")
    assert pc.exists_and_nonempty() is False


# --------------------------------------------------------------------------- #
# llm_polish system-prompt injection
# --------------------------------------------------------------------------- #

def test_build_system_prompt_without_context_returns_base():
    import llm_polish
    base = llm_polish._SYSTEM_PROMPT
    assert llm_polish._build_system_prompt("") == base
    assert llm_polish._build_system_prompt("   \n  ") == base
    assert llm_polish._build_system_prompt(None) == base  # type: ignore[arg-type]


def test_build_system_prompt_with_context_wraps_in_delimiters():
    import llm_polish
    prompt = llm_polish._build_system_prompt("Jag heter Patrik.")
    # The base must still be present so the model knows its primary job.
    assert llm_polish._SYSTEM_PROMPT in prompt
    # The context body must appear between the --- delimiters and be
    # introduced as reference material, not new content to insert.
    assert "Jag heter Patrik." in prompt
    assert "---" in prompt
    assert "kontext" in prompt.lower()
    assert "lägg" in prompt.lower() and "inte" in prompt.lower()


# --------------------------------------------------------------------------- #
# migrate_context
# --------------------------------------------------------------------------- #

def _setup_migration(tmp_path: Path):
    """Reload migrate_context + personal_context with paths in tmp_path."""
    pc = _reload_personal_context(tmp_path)
    import migrate_context
    mc = importlib.reload(migrate_context)
    mc._DIR = tmp_path
    mc._SNIPPETS_PATH = tmp_path / "snippets.json"
    mc._CORRECTIONS_PATH = tmp_path / "corrections.json"
    return pc, mc


def test_migration_noop_when_no_source_files(tmp_path):
    pc, mc = _setup_migration(tmp_path)
    assert mc.migrate_if_needed() is False
    assert not pc._PATH.exists()


def test_migration_noop_when_personal_context_already_exists(tmp_path):
    pc, mc = _setup_migration(tmp_path)
    pc.save("Redan skriven kontext.")
    (tmp_path / "snippets.json").write_text(
        json.dumps({"mvb": "Med vänliga hälsningar"}), encoding="utf-8")
    assert mc.migrate_if_needed() is False
    # Existing context untouched.
    assert pc.load() == "Redan skriven kontext."


def test_migration_writes_snippets_and_corrections_in_swedish(tmp_path):
    pc, mc = _setup_migration(tmp_path)
    (tmp_path / "snippets.json").write_text(
        json.dumps({"mvb": "Med vänliga hälsningar", "vh": "Vänliga hälsningar"}),
        encoding="utf-8")
    (tmp_path / "corrections.json").write_text(
        json.dumps({"kammar": "Kalmar", "tjabbis": "Joakim"}),
        encoding="utf-8")
    assert mc.migrate_if_needed() is True
    text = pc.load()
    assert "Vanliga fraser jag dikterar:" in text
    assert '"mvb" betyder "Med vänliga hälsningar"' in text
    assert "Korrekt stavning av ord jag ofta säger:" in text
    assert "kammar -> Kalmar" in text


def test_migration_handles_only_snippets(tmp_path):
    pc, mc = _setup_migration(tmp_path)
    (tmp_path / "snippets.json").write_text(
        json.dumps({"mvb": "Med vänliga hälsningar"}), encoding="utf-8")
    assert mc.migrate_if_needed() is True
    text = pc.load()
    assert "Vanliga fraser" in text
    assert "stavning" not in text  # corrections header must be absent


def test_migration_skips_when_source_files_are_empty(tmp_path):
    pc, mc = _setup_migration(tmp_path)
    (tmp_path / "snippets.json").write_text("{}", encoding="utf-8")
    (tmp_path / "corrections.json").write_text("{}", encoding="utf-8")
    assert mc.migrate_if_needed() is False
    assert not pc._PATH.exists()


def test_migration_filters_non_string_values(tmp_path):
    pc, mc = _setup_migration(tmp_path)
    (tmp_path / "snippets.json").write_text(
        json.dumps({"valid": "fine", "bad": 123, "": "no key"}),
        encoding="utf-8")
    assert mc.migrate_if_needed() is True
    text = pc.load()
    assert '"valid"' in text
    assert "bad" not in text
    assert "no key" not in text


def test_migration_is_idempotent(tmp_path):
    pc, mc = _setup_migration(tmp_path)
    (tmp_path / "snippets.json").write_text(
        json.dumps({"mvb": "Med vänliga hälsningar"}), encoding="utf-8")
    assert mc.migrate_if_needed() is True
    first = pc.load()
    # Second call must not change anything.
    assert mc.migrate_if_needed() is False
    assert pc.load() == first
