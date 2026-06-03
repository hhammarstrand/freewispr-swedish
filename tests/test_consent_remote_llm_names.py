"""On-screen names reach a *remote* LLM polisher only with consent.

Mirror of the remote-STT name gate: names scraped from the focused window may
freely go to a *local* (loopback) LLM, but must not be forwarded to a remote
LLM provider unless the user explicitly accepted it.
"""
from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace


def _reload_dictation(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    return importlib.reload(importlib.import_module("dictation"))


def _mode(dictation, *, provider, base_url, consent):
    mode = object.__new__(dictation.DictationMode)
    mode.transcriber = SimpleNamespace(
        llm_provider=provider, llm_base_url=base_url)
    mode.context_to_remote_accepted = consent
    return mode


def test_remote_llm_without_consent_strips_names(monkeypatch):
    dictation = _reload_dictation(monkeypatch)
    mode = _mode(dictation, provider="github", base_url="", consent=False)
    assert mode._names_for_llm("Kalmar, Åsa") == ""


def test_remote_llm_with_consent_forwards_names(monkeypatch):
    dictation = _reload_dictation(monkeypatch)
    mode = _mode(dictation, provider="openai", base_url="", consent=True)
    assert mode._names_for_llm("Kalmar, Åsa") == "Kalmar, Åsa"


def test_local_loopback_llm_always_uses_names(monkeypatch):
    dictation = _reload_dictation(monkeypatch)
    # No consent, but a loopback custom endpoint never leaves the machine.
    mode = _mode(dictation, provider="custom",
                 base_url="http://localhost:11434/v1", consent=False)
    assert mode._names_for_llm("Kalmar, Åsa") == "Kalmar, Åsa"


def test_remote_custom_llm_without_consent_strips_names(monkeypatch):
    dictation = _reload_dictation(monkeypatch)
    # Custom but a *remote* URL → still gated.
    mode = _mode(dictation, provider="custom",
                 base_url="https://api.example.com/v1", consent=False)
    assert mode._names_for_llm("Kalmar, Åsa") == ""


def test_empty_names_short_circuit(monkeypatch):
    dictation = _reload_dictation(monkeypatch)
    mode = _mode(dictation, provider="github", base_url="", consent=True)
    assert mode._names_for_llm("") == ""
