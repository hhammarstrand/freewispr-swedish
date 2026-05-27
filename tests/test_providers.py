"""Tester för multi-provider LLM och remote transkribering."""
from __future__ import annotations

import importlib
import io
import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest


# --------------------------------------------------------------------------- #
#  llm_polish: provider-registry och nyckelhantering
# --------------------------------------------------------------------------- #

def test_llm_polish_providers_registered():
    llm_polish = importlib.reload(importlib.import_module("llm_polish"))
    labels = llm_polish.provider_labels()
    assert set(labels) >= {"github", "staik", "berget", "openai", "custom"}


def test_llm_polish_normalize_model_per_provider():
    llm = importlib.reload(importlib.import_module("llm_polish"))
    # Github-alias.
    assert llm.normalize_model("gpt-4.1-nano", "github") == "openai/gpt-4.1-nano"
    # Staik utan alias -> oförändrad.
    assert llm.normalize_model("gemma4:31b", "staik") == "gemma4:31b"
    # Tom modell faller tillbaka till providerns default.
    assert llm.normalize_model("", "berget") == llm.provider_default_model("berget")


def test_llm_polish_resolve_api_key_per_provider(monkeypatch):
    llm = importlib.reload(importlib.import_module("llm_polish"))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("STAIK_API_KEY", "sk-st-test")
    monkeypatch.setenv("BERGET_API_KEY", "berget-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")

    assert llm.resolve_api_key("", "staik") == "sk-st-test"
    assert llm.resolve_api_key("", "berget") == "berget-test"
    assert llm.resolve_api_key("", "openai") == "sk-openai"
    # Explicit nyckel vinner alltid.
    assert llm.resolve_api_key("explicit", "staik") == "explicit"
    # Custom utan miljö och utan explicit -> tom.
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert llm.resolve_api_key("", "custom") == ""


def test_llm_polish_staik_does_not_fall_back_to_gh_cli(monkeypatch):
    llm = importlib.reload(importlib.import_module("llm_polish"))
    monkeypatch.delenv("STAIK_API_KEY", raising=False)

    # Om resolve_api_key för staik försökte köra `gh auth token` vore det fel.
    def fake_run(*args, **kwargs):
        raise AssertionError("gh CLI ska inte anropas för staik")

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    assert llm.resolve_api_key("", "staik") == ""


def test_llm_polish_polish_skips_when_no_key_or_no_url(monkeypatch):
    llm = importlib.reload(importlib.import_module("llm_polish"))
    # Custom utan base_url -> returnera original utan att försöka skicka.
    called = []
    monkeypatch.setattr(llm, "_call_api", lambda *a, **kw: called.append(a))
    res = llm.polish("hej", "", provider="custom", base_url_override="")
    assert res.text == "hej"
    assert res.changed is False
    assert called == []


def test_llm_polish_polish_sends_to_custom_url(monkeypatch):
    llm = importlib.reload(importlib.import_module("llm_polish"))
    seen = {}

    def fake_call(api_key, model, user_text, timeout_sec=8.0,
                  provider="github", base_url_override=""):
        seen["url"] = f"{base_url_override.rstrip('/')}/chat/completions"
        seen["model"] = model
        return {"choices": [{"message": {"content": "Hej!"}}]}

    monkeypatch.setattr(llm, "_call_api", fake_call)
    res = llm.polish("hej", "tok", model="my-model",
                     provider="custom", base_url_override="http://localhost:1234/v1")
    assert res.text == "Hej!"
    assert res.changed is True
    assert seen["url"] == "http://localhost:1234/v1/chat/completions"
    assert seen["model"] == "my-model"


def test_llm_polish_fetch_models_falls_back_on_error(monkeypatch):
    llm = importlib.reload(importlib.import_module("llm_polish"))

    def fake_request(*args, **kwargs):
        raise RuntimeError("nope")

    monkeypatch.setattr(llm, "_request_json", fake_request)
    models = llm.fetch_models(api_key="tok", provider="staik")
    # Fallback till statiska defaults.
    assert "gemma4:31b" in models


def test_llm_polish_fetch_models_parses_openai_list(monkeypatch):
    llm = importlib.reload(importlib.import_module("llm_polish"))

    def fake_request(url, headers, payload, method, timeout_sec):
        assert url.endswith("/models")
        assert method == "GET"
        return {"data": [
            {"id": "kb-whisper-large", "description": "Audio (sv)"},
            {"id": "gemma4:31b"},
        ]}

    monkeypatch.setattr(llm, "_request_json", fake_request)
    models = llm.fetch_models(api_key="tok", provider="staik")
    assert models["kb-whisper-large"] == "Audio (sv)"
    assert "gemma4:31b" in models


# --------------------------------------------------------------------------- #
#  remote_transcribe
# --------------------------------------------------------------------------- #

def test_remote_transcribe_providers_registered():
    rt = importlib.reload(importlib.import_module("remote_transcribe"))
    assert set(rt.provider_labels()) == {"staik", "berget", "custom"}
    assert rt.provider_default_model("staik") == "kb-whisper-large"


def test_remote_transcribe_wav_encoder_roundtrip():
    rt = importlib.reload(importlib.import_module("remote_transcribe"))
    import wave
    audio = np.array([0.0, 0.5, -0.5, 1.0, -1.0], dtype=np.float32)
    wav_bytes = rt._float_to_wav_bytes(audio, 16000)
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        assert wav.getframerate() == 16000
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getnframes() == 5


def test_remote_transcribe_empty_input_returns_empty():
    rt = importlib.reload(importlib.import_module("remote_transcribe"))
    result = rt.transcribe(np.empty(0, dtype=np.float32),
                           sample_rate=16000, provider="staik", api_key="tok")
    assert result == ""


def test_remote_transcribe_missing_key_raises():
    rt = importlib.reload(importlib.import_module("remote_transcribe"))
    audio = np.ones(1000, dtype=np.float32) * 0.1
    with pytest.raises(rt.RemoteTranscribeError):
        rt.transcribe(audio, 16000, provider="staik", api_key="")


def test_remote_transcribe_posts_multipart_and_parses_text(monkeypatch):
    rt = importlib.reload(importlib.import_module("remote_transcribe"))
    captured = {}

    class FakeResponse:
        def __init__(self, body): self._body = body
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return self._body

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["content_type"] = req.headers.get("Content-type")
        captured["auth"] = req.headers.get("Authorization")
        captured["body_prefix"] = req.data[:200]
        return FakeResponse(json.dumps({"text": "Hej världen"}).encode("utf-8"))

    monkeypatch.setattr(rt.urllib.request, "urlopen", fake_urlopen)

    audio = np.ones(8000, dtype=np.float32) * 0.2
    text = rt.transcribe(audio, 16000, provider="staik",
                         api_key="sk-st-test", model="kb-whisper-large")

    assert text == "Hej världen"
    assert captured["url"] == "https://api.staik.se/v1/audio/transcriptions"
    assert captured["method"] == "POST"
    assert captured["content_type"].startswith("multipart/form-data; boundary=")
    assert captured["auth"] == "Bearer sk-st-test"
    assert b"kb-whisper-large" in captured["body_prefix"]


def test_remote_transcribe_raises_friendly_message_on_http_error(monkeypatch):
    rt = importlib.reload(importlib.import_module("remote_transcribe"))
    audio = np.ones(1000, dtype=np.float32) * 0.1

    def fake_urlopen(req, timeout=None):
        raise rt.urllib.error.HTTPError(
            url=req.full_url, code=401, msg="unauthorized",
            hdrs=None, fp=io.BytesIO(b"bad key"),
        )

    monkeypatch.setattr(rt.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(rt.RemoteTranscribeError) as exc:
        rt.transcribe(audio, 16000, provider="berget", api_key="tok")
    assert "401" in str(exc.value)


def test_remote_transcribe_custom_requires_base_url():
    rt = importlib.reload(importlib.import_module("remote_transcribe"))
    audio = np.ones(1000, dtype=np.float32) * 0.1
    with pytest.raises(rt.RemoteTranscribeError):
        rt.transcribe(audio, 16000, provider="custom",
                      api_key="tok", model="x", base_url_override="")
