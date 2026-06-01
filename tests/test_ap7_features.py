"""AP7.5/7.6/7.7: english-terms bias, snippets, corrections editor + undo."""
from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import numpy as np


# --------------------------------------------------------------------------- #
#  AP7.5 — expect_english_terms
# --------------------------------------------------------------------------- #

def test_polish_adds_english_directive_when_enabled(monkeypatch):
    llm = importlib.reload(importlib.import_module("llm_polish"))
    seen = {}
    monkeypatch.setattr(llm, "_call_api",
                        lambda *a, **kw: seen.update(kw) or
                        {"choices": [{"message": {"content": "ut"}}]})
    llm.polish("hej", "tok", model="m", provider="custom",
               base_url_override="https://x/v1", expect_english_terms=True)
    ref = seen["context_text"]
    assert "engelska facktermer" in ref.lower()


def test_local_transcribe_adds_english_hotwords(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    transcriber = importlib.reload(importlib.import_module("transcriber"))
    captured = {}

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            captured.update(kwargs)
            return iter([SimpleNamespace(text="hej")]), SimpleNamespace()

    inst = object.__new__(transcriber.Transcriber)
    inst.language = "sv"
    inst.model = FakeModel()
    inst._model_lock = __import__("threading").RLock()
    inst.expect_english_terms = True
    inst._transcribe_local(np.ones(16000, dtype=np.float32))
    assert "deploy" in (captured["hotwords"] or "")


# --------------------------------------------------------------------------- #
#  AP7.6 — snippets
# --------------------------------------------------------------------------- #

def test_snippet_exact_expansion():
    s = importlib.reload(importlib.import_module("snippets"))
    snips = {"min signatur": "Med vänliga hälsningar\nPatrik"}
    assert s.expand("min signatur", snips) == "Med vänliga hälsningar\nPatrik"
    # Case/punctuation-insensitive on the leading phrase.
    assert s.expand("Min signatur.", snips).startswith("Med vänliga")


def test_snippet_prefix_keeps_remainder():
    s = importlib.reload(importlib.import_module("snippets"))
    snips = {"adress": "Storgatan 1"}
    assert s.expand("adress tack", snips) == "Storgatan 1 tack"


def test_snippet_no_match_returns_unchanged():
    s = importlib.reload(importlib.import_module("snippets"))
    assert s.expand("vanlig text", {"trigger": "x"}) == "vanlig text"
    assert s.expand("nåt", {}) == "nåt"


def test_snippet_save_load_roundtrip(tmp_path, monkeypatch):
    s = importlib.reload(importlib.import_module("snippets"))
    from json_store import JsonCache
    monkeypatch.setattr(s, "_store", JsonCache(tmp_path / "snippets.json", default={}))
    s.save({"mvh": "Med vänliga hälsningar", "  ": "skip", "x": ""})
    loaded = s.load()
    assert loaded == {"mvh": "Med vänliga hälsningar"}   # empties dropped


def test_dictation_snippet_expands_and_skips_polish(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    monkeypatch.setitem(sys.modules, "snippets",
                        SimpleNamespace(expand=lambda t: "EXPANDERAT" if t == "sig" else t))
    import threading
    dictation = importlib.reload(importlib.import_module("dictation"))
    pasted = []
    polished = []
    mode = object.__new__(dictation.DictationMode)
    mode.transcriber = SimpleNamespace(
        transcribe=lambda a, **kw: "sig", llm_enabled=True,
        polish_async=lambda *a, **k: polished.append(1), last_polish_state="local")
    mode._worker_stop = threading.Event()
    mode._active = True
    mode._modifier_keys = ()
    mode.hotkey = "ctrl+space"
    mode.indicator = None
    mode.on_status = lambda m: None
    mode.context_awareness = False
    mode.command_mode_enabled = False
    mode.snippets_enabled = True
    monkeypatch.setattr(dictation, "paste_text",
                        lambda text, active_modifiers=(), replace_len=0: pasted.append(text))
    mode._transcribe(np.ones(16000, dtype=np.float32))
    assert pasted == ["EXPANDERAT"]
    assert polished == []                 # canned expansion bypasses polish


# --------------------------------------------------------------------------- #
#  AP7.7 — corrections editor data path + undo
# --------------------------------------------------------------------------- #

def test_set_corrections_overwrites(tmp_path, monkeypatch):
    learning = importlib.reload(importlib.import_module("learning"))
    from json_store import JsonCache
    monkeypatch.setattr(learning, "_store",
                        JsonCache(tmp_path / "corrections.json", default={}))
    learning.set_corrections({"kammar": "Kalmar", "x": "", "  ": "y"})
    assert learning.load_corrections() == {"kammar": "Kalmar"}
    # Editing to empty removes everything.
    learning.set_corrections({})
    assert learning.load_corrections() == {}


def test_undo_last_erases_block(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    dictation = importlib.reload(importlib.import_module("dictation"))
    erased = []
    import paste
    monkeypatch.setattr(paste, "erase_last", lambda n: erased.append(n))
    mode = object.__new__(dictation.DictationMode)
    mode._last_block = "hej du"
    mode._last_pasted = "hej du"
    mode.indicator = None
    mode.on_status = lambda m: None
    assert mode.undo_last() is True
    assert erased == [len("hej du") + 1]    # +1 trailing space
    assert mode._last_block == ""
    # Nothing to undo now.
    assert mode.undo_last() is False
