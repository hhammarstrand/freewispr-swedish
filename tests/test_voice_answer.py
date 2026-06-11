"""KP4 voice-answer: reply to selection, result to clipboard (never pasted)."""
from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace


# --------------------------------------------------------------------------- #
#  llm_polish.answer()
# --------------------------------------------------------------------------- #

def test_answer_returns_sanitized_reply(monkeypatch):
    llm = importlib.import_module("llm_polish")
    monkeypatch.setattr(llm, "resolve_api_key", lambda key, provider: "k")
    monkeypatch.setattr(llm, "_resolve_base_url", lambda p, o: "https://api.x/v1")

    captured = {}

    def fake_http(url, headers, payload, method="POST", timeout_sec=20.0, stream=False):
        captured["url"] = url
        # Provider sneaks a control char + bidi override; sanitize must strip them.
        return {"choices": [{"message": {"content": "Hej!\x1b\u202e Tack."}}]}

    monkeypatch.setattr(llm, "_http_request", fake_http)
    out = llm.answer("Ursprungsmejl", "skriv ett svar", provider="openai", model="gpt")
    assert "\x1b" not in out and "\u202e" not in out  # neutralised (invariant 2)
    assert out.startswith("Hej!") and "Tack." in out
    assert captured["url"].endswith("/chat/completions")


def test_answer_empty_on_failure(monkeypatch):
    llm = importlib.import_module("llm_polish")
    monkeypatch.setattr(llm, "resolve_api_key", lambda key, provider: "k")
    monkeypatch.setattr(llm, "_resolve_base_url", lambda p, o: "https://api.x/v1")

    def boom(*a, **k):
        raise RuntimeError("network")

    monkeypatch.setattr(llm, "_http_request", boom)
    # On any error the answer is empty (caller shows an error; clipboard untouched).
    assert llm.answer("text", "svara", provider="openai", model="gpt") == ""


def test_answer_empty_without_instruction_or_text(monkeypatch):
    llm = importlib.import_module("llm_polish")
    assert llm.answer("", "svara") == ""
    assert llm.answer("text", "") == ""


# --------------------------------------------------------------------------- #
#  DictationMode.run_voice_answer routing
# --------------------------------------------------------------------------- #

def _mode(monkeypatch, *, llm_enabled, selection, reply):
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    dictation = importlib.reload(importlib.import_module("dictation"))

    import paste
    clip = {}
    monkeypatch.setattr(paste, "read_selection", lambda mods=(): selection)
    monkeypatch.setattr(paste, "copy_to_clipboard",
                        lambda text: (clip.__setitem__("text", text) or True))
    # paste_text must NEVER be called by voice-answer (no insertion).
    pasted = []
    monkeypatch.setattr(paste, "paste_text",
                        lambda *a, **k: pasted.append(a))

    import llm_polish
    seen = {}

    def fake_answer(text, instruction, **kw):
        seen["text"] = text
        seen["instruction"] = instruction
        return reply

    monkeypatch.setattr(llm_polish, "answer", fake_answer)

    mode = object.__new__(dictation.DictationMode)
    mode.transcriber = SimpleNamespace(
        llm_enabled=llm_enabled, llm_api_key="k", llm_model="m",
        llm_provider="github", llm_base_url="")
    mode._modifier_keys = ()
    mode.indicator = None
    mode.on_status = lambda m: None
    return mode, clip, pasted, seen, dictation


def test_voice_answer_happy_path_copies_to_clipboard(monkeypatch):
    mode, clip, pasted, seen, _ = _mode(
        monkeypatch, llm_enabled=True,
        selection="Hej, kan vi boka möte?", reply="Absolut, måndag kl 9?")
    assert mode.run_voice_answer("föreslå en tid") == "ok"
    assert clip["text"] == "Absolut, måndag kl 9?"   # reply in clipboard
    assert pasted == []                               # never pasted
    assert seen == {"text": "Hej, kan vi boka möte?", "instruction": "föreslå en tid"}


def test_voice_answer_requires_llm(monkeypatch):
    mode, clip, pasted, _, _ = _mode(
        monkeypatch, llm_enabled=False, selection="text", reply="x")
    assert mode.run_voice_answer("svara") == "failed"
    assert clip == {} and pasted == []


def test_voice_answer_no_selection(monkeypatch):
    mode, clip, _, _, _ = _mode(
        monkeypatch, llm_enabled=True, selection="", reply="x")
    assert mode.run_voice_answer("svara") == "no_selection"
    assert clip == {}


def test_voice_answer_empty_reply_does_not_touch_clipboard(monkeypatch):
    mode, clip, _, _, _ = _mode(
        monkeypatch, llm_enabled=True, selection="underlag", reply="")
    assert mode.run_voice_answer("svara") == "failed"
    assert clip == {}


def test_tagged_job_routes_to_run_voice_answer(monkeypatch):
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
        transcribe=lambda audio, capitalize=True: "skriv ett svar")
    captured = {}
    mode.run_voice_answer = lambda instr: captured.setdefault("instr", instr)

    audio = np.ones(16000, dtype=np.float32)
    mode._process_job(audio, 1, 16000, 0.5, 0.0, "voice_answer")
    assert captured["instr"] == "skriv ett svar"
