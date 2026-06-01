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
#  Provider tuple consistency (config.py vs actual modules)
# --------------------------------------------------------------------------- #

def test_config_llm_providers_match_llm_polish():
    """_LLM_PROVIDERS in config.py must list exactly the same keys as
    llm_polish.PROVIDERS. If this fails, a provider was added/removed in
    llm_polish.py without updating the hardcoded tuple in config.py."""
    config = importlib.reload(importlib.import_module("config"))
    llm_polish = importlib.reload(importlib.import_module("llm_polish"))
    assert set(config._LLM_PROVIDERS) == set(llm_polish.PROVIDERS.keys())


def test_config_tr_providers_match_remote_transcribe():
    """_TR_PROVIDERS in config.py must list exactly the same keys as
    remote_transcribe.PROVIDERS. If this fails, a provider was added/removed
    in remote_transcribe.py without updating the hardcoded tuple in config.py."""
    config = importlib.reload(importlib.import_module("config"))
    rt = importlib.reload(importlib.import_module("remote_transcribe"))
    assert set(config._TR_PROVIDERS) == set(rt.PROVIDERS.keys())


def test_config_validate_providers_logs_warning_on_mismatch(caplog, monkeypatch):
    """_validate_providers() must log a warning when the tuples diverge."""
    config = importlib.reload(importlib.import_module("config"))
    # Reset the guard so validation runs again.
    config._providers_validated = False
    # Inject a fake llm_polish with an extra provider.
    fake_llm = SimpleNamespace(PROVIDERS={"github": None, "staik": None,
                                          "berget": None, "openai": None,
                                          "custom": None, "extra": None})
    monkeypatch.setitem(sys.modules, "llm_polish", fake_llm)
    import logging
    with caplog.at_level(logging.WARNING):
        config._validate_providers()
    assert "config._LLM_PROVIDERS" in caplog.text
    assert "extra" in caplog.text


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
                  provider="github", base_url_override="", context_text=""):
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


def test_llm_polish_fetch_models_keeps_provider_fallbacks(monkeypatch):
    llm = importlib.reload(importlib.import_module("llm_polish"))

    def fake_request(url, headers, payload, method, timeout_sec):
        assert url.endswith("/models")
        return {"data": [
            {"id": "gemma4:31b"},
            {"id": "remote-only-model", "description": "Only in API"},
        ]}

    monkeypatch.setattr(llm, "_request_json", fake_request)
    models = llm.fetch_models(api_key="tok", provider="staik")
    assert "remote-only-model" in models
    assert "qwen3.6:35b-a3b" in models
    assert "qwen3.5:9b" in models


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


# --------------------------------------------------------------------------- #
#  Server-error visibility (regression: HTTP 502 showed "Inget hördes")
# --------------------------------------------------------------------------- #

def test_transcriber_remote_reraises_server_error(monkeypatch):
    """A failing remote request must propagate the error, NOT return "".

    Regression: a 502 used to be swallowed into an empty string, which the
    dictation layer rendered as "Inget hördes" — falsely telling the user the
    mic was silent when it was actually a server failure.

    Calls the unbound ``_transcribe_remote`` against a lightweight stand-in to
    avoid constructing the full Transcriber (which imports torch).
    """
    transcriber = importlib.import_module("transcriber")
    rt = importlib.import_module("remote_transcribe")

    def boom(*a, **k):
        raise rt.RemoteTranscribeError("Serverfel (HTTP 502)")

    monkeypatch.setattr(rt, "transcribe", boom)

    stub = SimpleNamespace(
        transcription_provider="staik",
        transcription_api_key="tok",
        transcription_model="kb-whisper-large",
        transcription_base_url="",
        language="sv",
        on_stage=None,
    )

    audio = np.ones(8000, dtype=np.float32) * 0.2
    with pytest.raises(rt.RemoteTranscribeError) as exc:
        transcriber.Transcriber._transcribe_remote(stub, audio)
    assert "502" in str(exc.value)


def test_friendly_error_surfaces_server_error_not_silence():
    """_friendly_transcribe_error must report a server error verbatim, never
    map it to a silence/"Inget hördes" style message."""
    dictation = importlib.import_module("dictation")
    rt = importlib.import_module("remote_transcribe")

    msg = dictation._friendly_transcribe_error(
        rt.RemoteTranscribeError("Serverfel (HTTP 502)"))
    assert "Serverfel" in msg
    assert "HTTP 502" in msg
    assert "hörde" not in msg.lower()


# --------------------------------------------------------------------------- #
#  Retry on transient 5xx (502/503/504)
# --------------------------------------------------------------------------- #

def _http_error(rt, code):
    return rt.urllib.error.HTTPError(
        url="https://api.staik.se/v1/audio/transcriptions",
        code=code, msg="x", hdrs=None, fp=io.BytesIO(b""),
    )


class _FakeResp:
    def __init__(self, body): self._body = body
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return self._body


def test_retry_recovers_after_transient_502(monkeypatch):
    """Two 502s followed by a 200 must succeed transparently after retries."""
    rt = importlib.reload(importlib.import_module("remote_transcribe"))
    monkeypatch.setattr(rt.time, "sleep", lambda *_: None)

    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _http_error(rt, 502)
        return _FakeResp(json.dumps({"text": "Hej"}).encode("utf-8"))

    monkeypatch.setattr(rt.urllib.request, "urlopen", fake_urlopen)

    audio = np.ones(8000, dtype=np.float32) * 0.2
    text = rt.transcribe(audio, 16000, provider="staik", api_key="tok")

    assert text == "Hej"
    assert calls["n"] == 3


def test_retry_exhausts_and_raises_on_persistent_503(monkeypatch):
    """Persistent 503 must retry up to the cap, then raise."""
    rt = importlib.reload(importlib.import_module("remote_transcribe"))
    monkeypatch.setattr(rt.time, "sleep", lambda *_: None)

    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        raise _http_error(rt, 503)

    monkeypatch.setattr(rt.urllib.request, "urlopen", fake_urlopen)

    audio = np.ones(8000, dtype=np.float32) * 0.2
    with pytest.raises(rt.RemoteTranscribeError) as exc:
        rt.transcribe(audio, 16000, provider="staik", api_key="tok")

    assert calls["n"] == rt._MAX_ATTEMPTS
    assert "503" in str(exc.value)


def test_no_retry_on_client_error_401(monkeypatch):
    """A 401 must fail immediately without burning retry attempts."""
    rt = importlib.reload(importlib.import_module("remote_transcribe"))
    monkeypatch.setattr(rt.time, "sleep", lambda *_: None)

    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        raise _http_error(rt, 401)

    monkeypatch.setattr(rt.urllib.request, "urlopen", fake_urlopen)

    audio = np.ones(8000, dtype=np.float32) * 0.2
    with pytest.raises(rt.RemoteTranscribeError) as exc:
        rt.transcribe(audio, 16000, provider="staik", api_key="tok")

    assert calls["n"] == 1
    assert "401" in str(exc.value)
