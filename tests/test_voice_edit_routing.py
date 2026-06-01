"""KP3: DictationMode.run_voice_edit routing (selection → LLM → paste)."""
from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace


def _mode(monkeypatch, *, llm_enabled, selection, instruct_result):
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    dictation = importlib.reload(importlib.import_module("dictation"))

    import paste
    pasted = []
    monkeypatch.setattr(paste, "read_selection", lambda mods=(): selection)
    monkeypatch.setattr(paste, "paste_text",
                        lambda text, active_modifiers=(), replace_len=0:
                        pasted.append((text, replace_len)))

    import llm_polish
    seen = {}

    def fake_instruct(text, instruction, **kw):
        seen["text"] = text
        seen["instruction"] = instruction
        return instruct_result

    monkeypatch.setattr(llm_polish, "instruct", fake_instruct)

    mode = object.__new__(dictation.DictationMode)
    mode.transcriber = SimpleNamespace(
        llm_enabled=llm_enabled, llm_api_key="k", llm_model="m",
        llm_provider="github", llm_base_url="")
    mode._modifier_keys = ()
    mode.indicator = None
    mode.on_status = lambda m: None
    return mode, pasted, seen, dictation


def test_voice_edit_happy_path(monkeypatch):
    mode, pasted, seen, dictation = _mode(
        monkeypatch, llm_enabled=True,
        selection="tja läget", instruct_result="God dag.")
    import voice_edit
    assert mode.run_voice_edit("gör det formellt") == voice_edit.OK
    assert pasted == [("God dag.", 0)]
    assert seen == {"text": "tja läget", "instruction": "gör det formellt"}


def test_voice_edit_requires_llm(monkeypatch):
    mode, pasted, _, _ = _mode(
        monkeypatch, llm_enabled=False,
        selection="text", instruct_result="x")
    import voice_edit
    assert mode.run_voice_edit("kortare") == voice_edit.FAILED
    assert pasted == []


def test_voice_edit_no_selection(monkeypatch):
    mode, pasted, _, _ = _mode(
        monkeypatch, llm_enabled=True,
        selection="", instruct_result="x")
    import voice_edit
    assert mode.run_voice_edit("kortare") == voice_edit.NO_SELECTION
    assert pasted == []


def test_voice_edit_unchanged_does_not_paste(monkeypatch):
    mode, pasted, _, _ = _mode(
        monkeypatch, llm_enabled=True,
        selection="samma", instruct_result="samma")
    import voice_edit
    assert mode.run_voice_edit("gör inget") == voice_edit.UNCHANGED
    assert pasted == []


def test_tagged_job_routes_to_run_voice_edit(monkeypatch):
    # A 6-tuple job tagged "voice_edit" must transcribe the instruction and
    # call run_voice_edit(), never the dictation paste path.
    import numpy as np
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    dictation = importlib.reload(importlib.import_module("dictation"))

    monkeypatch.setattr(dictation, "finalize_audio",
                        lambda a, c, r: np.ones(16000, dtype=np.float32))
    monkeypatch.setattr(dictation, "MIN_AUDIO_SAMPLES", 1)

    mode = object.__new__(dictation.DictationMode)
    mode.min_rms = 0.0
    mode.indicator = None
    mode.on_status = lambda m: None
    mode.transcriber = SimpleNamespace(
        transcribe=lambda audio, capitalize=True: "gör det formellt")
    captured = {}
    mode.run_voice_edit = lambda instr: captured.setdefault("instr", instr)

    audio = np.ones(16000, dtype=np.float32)
    mode._process_job(audio, 1, 16000, 0.5, 0.0, "voice_edit")
    assert captured["instr"] == "gör det formellt"
