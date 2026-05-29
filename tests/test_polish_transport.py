"""AP1: streaming + keep-alive transport, reference block, raw-mode."""
from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

import pytest


class _FakeResp:
    def __init__(self, status=200, body=b"", lines=None, reason="OK"):
        self.status = status
        self.reason = reason
        self._body = body
        self._lines = lines or []

    def read(self):
        return self._body

    def getheaders(self):
        return []

    def __iter__(self):
        return iter(self._lines)


# --------------------------------------------------------------------------- #
#  Streaming (SSE) assembly
# --------------------------------------------------------------------------- #

def test_read_sse_assembles_deltas():
    llm = importlib.reload(importlib.import_module("llm_polish"))
    lines = [
        b'data: {"model":"m1","choices":[{"delta":{"content":"Hej"}}]}\n',
        b'data: {"choices":[{"delta":{"content":" du"}}]}\n',
        b": keep-alive comment that must be ignored\n",
        b"data: [DONE]\n",
    ]
    out = llm._read_sse(iter(lines))
    assert out["choices"][0]["message"]["content"] == "Hej du"
    assert out["model"] == "m1"


# --------------------------------------------------------------------------- #
#  _call_api payload shape (max_tokens, streaming flag, reference injection)
# --------------------------------------------------------------------------- #

def test_call_api_payload_uses_token_budget_and_stream(monkeypatch):
    llm = importlib.reload(importlib.import_module("llm_polish"))
    captured = {}

    def fake_http(url, headers, payload, method, timeout_sec, stream):
        captured["url"] = url
        captured["payload"] = json.loads(payload)
        captured["stream"] = stream
        return {"choices": [{"message": {"content": "x"}}]}

    monkeypatch.setattr(llm, "_http_request", fake_http)
    llm._call_api("k", "my-model", "hejsan",
                  provider="custom", base_url_override="https://x.example/v1",
                  context_text="REF-BLOCK")

    body = captured["payload"]
    assert body["temperature"] == 0
    assert body["stream"] is True
    assert captured["stream"] is True
    assert body["max_tokens"] == max(64, int(len("hejsan") * 1.3) + 32)
    # Reference is in its own message (static prefix stays cacheable, L3).
    assert any("REF-BLOCK" in m["content"] for m in body["messages"])
    assert captured["url"] == "https://x.example/v1/chat/completions"


def test_call_api_non_stream_for_test_connection(monkeypatch):
    llm = importlib.reload(importlib.import_module("llm_polish"))
    captured = {}

    def fake_http(url, headers, payload, method, timeout_sec, stream):
        captured["stream"] = stream
        captured["payload"] = json.loads(payload)
        return {"choices": [{"message": {"content": "x"}}]}

    monkeypatch.setattr(llm, "_http_request", fake_http)
    llm._call_api("k", "my-model", "hej",
                  provider="custom", base_url_override="https://x.example/v1",
                  stream=False)
    assert captured["stream"] is False
    assert "stream" not in captured["payload"]


# --------------------------------------------------------------------------- #
#  polish() weaves all reference inputs into the system prompt
# --------------------------------------------------------------------------- #

def test_polish_passes_full_reference_block(monkeypatch):
    llm = importlib.reload(importlib.import_module("llm_polish"))
    seen = {}

    def fake_call(*a, **kw):
        seen["context_text"] = kw.get("context_text", "")
        return {"choices": [{"message": {"content": "Utdata"}}]}

    monkeypatch.setattr(llm, "_call_api", fake_call)
    res = llm.polish("hej", "tok", model="my-model", provider="custom",
                     base_url_override="https://x.example/v1",
                     context_text="Min kontext",
                     corrections={"kammar": "Kalmar"},
                     app_profile="kod", onscreen_names="Johan")
    ref = seen["context_text"]
    assert "Min kontext" in ref
    assert "kammar → Kalmar" in ref
    assert "App-profil: kod" in ref
    assert "Johan" in ref
    assert res.text == "Utdata"


# --------------------------------------------------------------------------- #
#  Keep-alive transport: HTTPError on 4xx, retry-once on stale connection
# --------------------------------------------------------------------------- #

def test_http_request_raises_httperror_on_4xx(monkeypatch):
    import urllib.error
    hp = importlib.reload(importlib.import_module("http_pool"))

    class Conn:
        timeout = 0

        def connect(self):
            pass

        def request(self, *a, **k):
            pass

        def getresponse(self):
            return _FakeResp(status=401, body=b"bad key", reason="Unauthorized")

        def close(self):
            pass

    monkeypatch.setattr(hp, "connection_for",
                        lambda url, timeout: (("https", "x", 443), Conn(), False))
    monkeypatch.setattr(hp, "drop_connection", lambda key: None)

    with pytest.raises(urllib.error.HTTPError) as exc:
        hp.request("https://x/v1/chat/completions", {}, b"{}", "POST", 5.0)
    assert exc.value.code == 401


def test_http_request_retries_once_on_stale_connection(monkeypatch):
    hp = importlib.reload(importlib.import_module("http_pool"))
    calls = {"n": 0}

    class Conn:
        timeout = 0

        def connect(self):
            pass

        def request(self, *a, **k):
            pass

        def getresponse(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("stale keep-alive")
            return _FakeResp(status=200,
                             body=json.dumps({"ok": 1}).encode("utf-8"))

        def close(self):
            pass

    conn = Conn()
    monkeypatch.setattr(hp, "connection_for",
                        lambda url, timeout: (("https", "x", 443), conn, True))
    monkeypatch.setattr(hp, "drop_connection", lambda key: None)

    out = hp.request("https://x/v1/chat/completions", {}, b"{}", "POST", 5.0)
    assert out == {"ok": 1}
    assert calls["n"] == 2


def test_http_pool_records_conn_reused_stats(monkeypatch):
    hp = importlib.reload(importlib.import_module("http_pool"))

    class Conn:
        timeout = 0

        def connect(self):
            pass

        def request(self, *a, **k):
            pass

        def getresponse(self):
            return _FakeResp(status=200, body=b'{"ok":1}')

        def close(self):
            pass

    # reused=True → conn_ms stays 0 and connect() is skipped.
    monkeypatch.setattr(hp, "connection_for",
                        lambda url, timeout: (("https", "x", 443), Conn(), True))
    monkeypatch.setattr(hp, "drop_connection", lambda key: None)
    hp.request("https://x/v1/chat/completions", {}, b"{}", "POST", 5.0)
    assert hp.last_stats()["conn_reused"] is True
    assert hp.last_stats()["conn_ms"] == 0.0


# --------------------------------------------------------------------------- #
#  Dictation: "rå direkt" skips polish even when LLM is enabled
# --------------------------------------------------------------------------- #

def test_dictation_raw_mode_skips_polish(monkeypatch):
    import sys
    import threading

    import numpy as np
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    dictation = importlib.reload(importlib.import_module("dictation"))

    pasted = []
    polish_called = []

    mode = object.__new__(dictation.DictationMode)
    mode.transcriber = SimpleNamespace(
        transcribe=lambda audio, **kw: "ra text",
        polish_async=lambda *a, **k: polish_called.append(1),
        last_polish_state="local",
        llm_enabled=True,
    )
    mode._worker_stop = threading.Event()
    mode._active = True
    mode._modifier_keys = ()
    mode.hotkey = "ctrl+space"
    mode.indicator = None
    mode.on_status = lambda msg: None
    mode.raw_mode = True
    monkeypatch.setattr(dictation, "paste_text",
                        lambda text, active_modifiers=(): pasted.append(text))

    mode._transcribe(np.ones(16000, dtype=np.float32))

    assert pasted == ["ra text"]
    assert polish_called == []
