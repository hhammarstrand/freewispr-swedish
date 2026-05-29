"""AP2: learning loop — diff heuristic, persistence, polish injection."""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest


@pytest.fixture
def learning(tmp_path, monkeypatch):
    mod = importlib.reload(importlib.import_module("learning"))
    monkeypatch.setattr(mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(mod, "CORRECTIONS_PATH", tmp_path / "corrections.json")
    monkeypatch.setattr(mod, "HOTWORDS_PATH", tmp_path / "hotwords.txt")
    # Rebind the module-level cache to the temp path.
    from json_store import JsonCache
    monkeypatch.setattr(mod, "_store",
                        JsonCache(tmp_path / "corrections.json", default={}))
    return mod


# --------------------------------------------------------------------------- #
#  diff heuristic
# --------------------------------------------------------------------------- #

def test_diff_pairs_detects_single_word_correction(learning):
    pairs = learning.diff_pairs("jag åkte till kammar", "jag åkte till Kalmar")
    assert pairs == [("kammar", "Kalmar")]


def test_diff_pairs_detects_capitalization_name_fix(learning):
    pairs = learning.diff_pairs("hej johan", "hej Johan")
    assert pairs == [("johan", "Johan")]


def test_diff_pairs_ignores_unrelated_rewrite(learning):
    # "bra" → "dålig" is a content edit, not a transcription correction.
    assert learning.diff_pairs("det var bra", "det var dålig") == []


def test_diff_pairs_ignores_identical_and_empty(learning):
    assert learning.diff_pairs("samma text", "samma text") == []
    assert learning.diff_pairs("", "nåt") == []
    assert learning.diff_pairs("nåt", "") == []


def test_diff_pairs_ignores_wholesale_rewrite(learning):
    # Many simultaneous swaps → user rewrote the whole thing, learn nothing.
    pasted = "aaa bbb ccc ddd eee fff"
    observed = "aab bbc ccd dde eef ffg"
    assert learning.diff_pairs(pasted, observed) == []


# --------------------------------------------------------------------------- #
#  persistence
# --------------------------------------------------------------------------- #

def test_learn_from_observation_persists_correction_and_hotword(learning):
    pairs = learning.learn_from_observation("möte i kammar", "möte i Kalmar")
    assert pairs == [("kammar", "Kalmar")]

    # corrections.json contains the pair
    assert learning.load_corrections()["kammar"] == "Kalmar"
    # hotwords.txt gained the *correct* term
    hot = learning.HOTWORDS_PATH.read_text(encoding="utf-8")
    assert "Kalmar" in hot


def test_clear_learned_empties_corrections(learning):
    learning.learn_from_observation("möte i kammar", "möte i Kalmar")
    assert learning.load_corrections()
    learning.clear_learned()
    assert learning.load_corrections() == {}


def test_add_hotwords_deduplicates(learning):
    learning.add_hotwords(["Kalmar", "Johan"])
    learning.add_hotwords(["Kalmar", "Stockholm"])
    lines = [ln.strip() for ln in
             learning.HOTWORDS_PATH.read_text(encoding="utf-8").splitlines()
             if ln.strip()]
    assert lines.count("Kalmar") == 1
    assert "Johan" in lines and "Stockholm" in lines


# --------------------------------------------------------------------------- #
#  polish injection via transcriber
# --------------------------------------------------------------------------- #

def test_polish_async_injects_learned_corrections(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    transcriber = importlib.reload(importlib.import_module("transcriber"))
    captured = {}

    def fake_polish(text, api_key, **kw):
        captured.update(kw)
        return SimpleNamespace(text="ok", model="m", latency_ms=1, changed=True)

    monkeypatch.setitem(
        __import__("sys").modules, "llm_polish",
        SimpleNamespace(polish=fake_polish))
    monkeypatch.setitem(
        __import__("sys").modules, "learning",
        SimpleNamespace(load_corrections=lambda: {"kammar": "Kalmar"}))
    monkeypatch.setitem(
        __import__("sys").modules, "personal_context",
        SimpleNamespace(load=lambda: "min kontext"))

    t = object.__new__(transcriber.Transcriber)
    t.llm_api_key = "k"
    t.llm_model = "m"
    t.llm_provider = "custom"
    t.llm_base_url = "https://x/v1"
    t.last_polish_state = "local"
    t.on_stage = None

    done = []
    t.polish_async("hej", lambda o, p: done.append((o, p)),
                   app_profile="formell e-post", onscreen_names="Johan")

    import time
    for _ in range(50):
        if done:
            break
        time.sleep(0.02)

    assert captured["corrections"] == {"kammar": "Kalmar"}
    assert captured["app_profile"] == "formell e-post"
    assert captured["onscreen_names"] == "Johan"
    assert captured["context_text"] == "min kontext"
