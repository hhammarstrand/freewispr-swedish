"""L5.3: warm the remote transcription connection at start."""
from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace


def test_warm_pings_models_over_pool(monkeypatch):
    rt = importlib.reload(importlib.import_module("remote_transcribe"))
    seen = {}

    def fake_request(url, headers, payload=None, method="POST", **kw):
        seen["url"] = url
        seen["method"] = method
        seen["auth"] = headers.get("Authorization")
        return b"{}"

    monkeypatch.setattr(rt.http_pool, "request", fake_request)
    assert rt.warm("staik", api_key="sk-st") is True
    assert seen["url"] == "https://api.staik.se/v1/models"
    assert seen["method"] == "GET"
    assert seen["auth"] == "Bearer sk-st"


def test_warm_returns_false_without_key(monkeypatch):
    rt = importlib.reload(importlib.import_module("remote_transcribe"))
    monkeypatch.delenv("STAIK_API_KEY", raising=False)
    assert rt.warm("staik", api_key="") is False


def test_transcriber_starts_transcribe_warmer_for_remote(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    transcriber = importlib.reload(importlib.import_module("transcriber"))
    started = []
    monkeypatch.setattr(transcriber.Transcriber, "_start_transcribe_warmer",
                        lambda self: started.append(1))
    transcriber.Transcriber(
        transcription_provider="staik",
        transcription_api_key="sk", transcription_model="kb-whisper-large")
    assert started == [1]


def test_transcriber_no_transcribe_warmer_for_local(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    transcriber = importlib.reload(importlib.import_module("transcriber"))
    started = []
    monkeypatch.setattr(transcriber.Transcriber, "_start_transcribe_warmer",
                        lambda self: started.append(1))
    # Local model load will fail (no model on disk) — that's fine, we only
    # assert the warmer wasn't scheduled before the local path.
    try:
        transcriber.Transcriber(transcription_provider="local", model_size="tiny")
    except Exception:
        pass
    assert started == []
