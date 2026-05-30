"""L3: polish warm-up, cacheable prefix split, raw→replace mode."""
from __future__ import annotations

import importlib
import json
import sys
import threading
from types import SimpleNamespace

import numpy as np


# --------------------------------------------------------------------------- #
#  warm()
# --------------------------------------------------------------------------- #

def test_warm_sends_minimal_request(monkeypatch):
    llm = importlib.reload(importlib.import_module("llm_polish"))
    seen = {}

    def fake_http(url, headers, payload, method, timeout_sec, stream):
        seen["url"] = url
        seen["body"] = json.loads(payload)
        return {"choices": [{"message": {"content": ""}}]}

    monkeypatch.setattr(llm, "_http_request", fake_http)
    ok = llm.warm("tok", model="my-model", provider="custom",
                  base_url_override="https://x.example/v1")
    assert ok is True
    assert seen["url"].endswith("/chat/completions")
    assert seen["body"]["max_tokens"] == 1


def test_warm_no_key_returns_false(monkeypatch):
    llm = importlib.reload(importlib.import_module("llm_polish"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # openai provider, no key anywhere → no request attempted.
    assert llm.warm("", provider="openai") is False


# --------------------------------------------------------------------------- #
#  cacheable prefix split
# --------------------------------------------------------------------------- #

def test_chat_messages_keep_static_prefix_separate():
    llm = importlib.reload(importlib.import_module("llm_polish"))
    msgs = llm._chat_messages("REF-BLOCK", "hej")
    # First message is the stable, cacheable prefix (no dynamic reference).
    assert msgs[0]["role"] == "system"
    assert "REF-BLOCK" not in msgs[0]["content"]
    assert msgs[0]["content"] == llm._STATIC_PREFIX
    # Reference lives in its own message; user text last.
    assert any("REF-BLOCK" in m["content"] for m in msgs)
    assert msgs[-1] == {"role": "user", "content": "hej"}


def test_chat_messages_omit_reference_when_empty():
    llm = importlib.reload(importlib.import_module("llm_polish"))
    msgs = llm._chat_messages("", "hej")
    assert len(msgs) == 2
    assert msgs[0]["content"] == llm._STATIC_PREFIX
    assert msgs[1] == {"role": "user", "content": "hej"}


# --------------------------------------------------------------------------- #
#  raw → replace mode
# --------------------------------------------------------------------------- #

def test_replace_mode_pastes_raw_then_polished(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    dictation = importlib.reload(importlib.import_module("dictation"))

    pastes = []

    def fake_polish_async(text, callback, on_stage=None, **kw):
        threading.Thread(target=lambda: callback(text, "Polerad text."),
                         daemon=True).start()

    mode = object.__new__(dictation.DictationMode)
    mode.transcriber = SimpleNamespace(
        transcribe=lambda a, **kw: "ra text",
        polish_async=fake_polish_async,
        llm_enabled=True, last_polish_state="llm_changed")
    mode._worker_stop = threading.Event()
    mode._active = True
    mode._modifier_keys = ()
    mode.hotkey = "ctrl+space"
    mode.indicator = None
    mode.on_status = lambda m: None
    mode.raw_mode = False
    mode.llm_replace_mode = True
    mode.context_awareness = False
    mode.command_mode_enabled = False
    mode.polish_skip_trivial = False
    monkeypatch.setattr(
        dictation, "paste_text",
        lambda text, active_modifiers=(), replace_len=0: pastes.append((text, replace_len)))

    mode._transcribe(np.ones(16000, dtype=np.float32))

    import time
    for _ in range(50):
        if len(pastes) >= 2:
            break
        time.sleep(0.02)

    # First paste is the raw transcript (no replace), second replaces it.
    assert pastes[0] == ("ra text", 0)
    assert pastes[1][0] == "Polerad text."
    assert pastes[1][1] == len("ra text") + 1
    assert mode._last_block == "Polerad text."
