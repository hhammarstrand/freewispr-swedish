"""AP5: command mode — detection, local/LLM execution, dictation wiring."""
from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace


# --------------------------------------------------------------------------- #
#  detection
# --------------------------------------------------------------------------- #

def test_detect_command_matches_known_phrases():
    commands = importlib.reload(importlib.import_module("commands"))
    assert commands.detect_command("gör det kortare").kind == "llm"
    assert commands.detect_command("Gör det kortare.").phrase == "gör det kortare"
    assert commands.detect_command("ta bort sista meningen").kind == "local"
    # Phrase as a prefix is allowed.
    cmd = commands.detect_command("översätt till engelska, tack")
    assert cmd is not None and cmd.phrase == "översätt till engelska"


def test_detect_command_returns_none_for_normal_text():
    commands = importlib.reload(importlib.import_module("commands"))
    assert commands.detect_command("hej jag heter Anna") is None
    assert commands.detect_command("") is None


# --------------------------------------------------------------------------- #
#  execution
# --------------------------------------------------------------------------- #

def test_execute_local_remove_last_sentence():
    commands = importlib.reload(importlib.import_module("commands"))
    cmd = commands.detect_command("ta bort sista meningen")
    out = commands.execute(cmd, "Första meningen. Andra meningen.")
    assert out == "Första meningen."


def test_execute_llm_uses_transform():
    commands = importlib.reload(importlib.import_module("commands"))
    cmd = commands.detect_command("gör det kortare")
    seen = {}

    def transform(instruction, text):
        seen["instruction"] = instruction
        seen["text"] = text
        return "Kort."

    out = commands.execute(cmd, "En väldigt lång text här.", transform)
    assert out == "Kort."
    assert "kortare" in seen["instruction"]
    assert seen["text"] == "En väldigt lång text här."


def test_execute_llm_without_transform_returns_none():
    commands = importlib.reload(importlib.import_module("commands"))
    cmd = commands.detect_command("gör det kortare")
    assert commands.execute(cmd, "text", None) is None


def test_execute_empty_previous_returns_none():
    commands = importlib.reload(importlib.import_module("commands"))
    cmd = commands.detect_command("ta bort sista meningen")
    assert commands.execute(cmd, "   ") is None


# --------------------------------------------------------------------------- #
#  dictation integration: a command edits the last block in place
# --------------------------------------------------------------------------- #

def test_dictation_command_replaces_last_block(monkeypatch):
    import threading

    import numpy as np
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    monkeypatch.setitem(sys.modules, "llm_polish",
                        SimpleNamespace(instruct=lambda text, instruction, **kw: "Kort version."))
    dictation = importlib.reload(importlib.import_module("dictation"))

    pastes = []

    mode = object.__new__(dictation.DictationMode)
    mode.transcriber = SimpleNamespace(
        transcribe=lambda audio, **kw: "gör det kortare",
        llm_enabled=True,
        llm_api_key="k", llm_model="m", llm_provider="custom", llm_base_url="https://x/v1",
        last_polish_state="local",
    )
    mode._worker_stop = threading.Event()
    mode._active = True
    mode._modifier_keys = ()
    mode.hotkey = "ctrl+space"
    mode.indicator = None
    mode.on_status = lambda msg: None
    mode.command_mode_enabled = True
    mode._last_block = "En väldigt lång text som ska kortas ner."
    monkeypatch.setattr(
        dictation, "paste_text",
        lambda text, active_modifiers=(), replace_len=0: pastes.append((text, replace_len)))

    mode._transcribe(np.ones(16000, dtype=np.float32))

    assert len(pastes) == 1
    text, replace_len = pastes[0]
    assert text == "Kort version."
    # Replaces the previous block (+1 for the trailing space paste adds).
    assert replace_len == len("En väldigt lång text som ska kortas ner.") + 1
    assert mode._last_block == "Kort version."
