"""AP4: backend-aware transcription biasing (local decode + remote prompt)."""
from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture
def transcriber(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    return importlib.reload(importlib.import_module("transcriber"))


# --------------------------------------------------------------------------- #
#  local decode: configurable knobs reach faster-whisper
# --------------------------------------------------------------------------- #

def test_local_transcribe_passes_configured_decode_params(transcriber):
    captured = {}

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            captured.update(kwargs)
            return iter([SimpleNamespace(text="hej")]), SimpleNamespace()

    inst = object.__new__(transcriber.Transcriber)
    inst.language = "sv"
    inst.model = FakeModel()
    inst._model_lock = __import__("threading").RLock()
    inst.beam_size = 5
    inst.vad_filter = False
    inst.no_speech_threshold = 0.3

    out = inst._transcribe_local(np.ones(16000, dtype=np.float32))
    assert out == "Hej"
    assert captured["beam_size"] == 5
    assert captured["vad_filter"] is False          # vad disabled → single pass
    assert captured["no_speech_threshold"] == 0.3
    # L4: single-shot dictation must not condition on previous text.
    assert captured["condition_on_previous_text"] is False
    # L5.1: a scalar temperature (no fallback escalation = 1 decode pass).
    assert captured["temperature"] == 0.0
    assert isinstance(captured["temperature"], float)


def test_local_transcribe_merges_extra_hotwords(transcriber, monkeypatch):
    captured = {}

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            captured.update(kwargs)
            return iter([SimpleNamespace(text="hej")]), SimpleNamespace()

    monkeypatch.setattr(transcriber, "_get_hotwords_cached", lambda: "Kalmar")
    inst = object.__new__(transcriber.Transcriber)
    inst.language = "sv"
    inst.model = FakeModel()
    inst._model_lock = __import__("threading").RLock()

    inst._transcribe_local(np.ones(16000, dtype=np.float32),
                           extra_hotwords="Johan, Åsa")
    assert "Kalmar" in captured["hotwords"]
    assert "Johan" in captured["hotwords"]


# --------------------------------------------------------------------------- #
#  compute type override + KBLab revision fallback
# --------------------------------------------------------------------------- #

def test_compute_type_override(transcriber, monkeypatch):
    monkeypatch.setattr(transcriber, "_check_cuda", lambda: True)
    device, compute, cuda = transcriber._get_device_and_compute(True, "float16")
    assert device == "cuda"
    assert compute == "float16"
    # Empty override → CUDA default is now int8_float16 (L4).
    _, compute2, _ = transcriber._get_device_and_compute(True, "")
    assert compute2 == "int8_float16"
    # CPU default stays int8.
    _, compute3, cuda3 = transcriber._get_device_and_compute(False, "")
    assert compute3 == "int8" and cuda3 is False


def test_revision_falls_back_to_default_when_build_missing(transcriber, tmp_path,
                                                           monkeypatch):
    monkeypatch.setattr(transcriber, "MODEL_DIR", tmp_path)
    # Only the default ct2 build exists.
    default_dir = tmp_path / "kb-whisper-small-ct2"
    default_dir.mkdir()
    (default_dir / "model.bin").write_bytes(b"x")

    path = transcriber._find_local_model("KBLab/kb-whisper-small", "strict")
    assert path == str(default_dir)


def test_revision_uses_variant_build_when_present(transcriber, tmp_path,
                                                  monkeypatch):
    monkeypatch.setattr(transcriber, "MODEL_DIR", tmp_path)
    rev_dir = tmp_path / "kb-whisper-small-strict-ct2"
    rev_dir.mkdir()
    (rev_dir / "model.bin").write_bytes(b"x")

    path = transcriber._find_local_model("KBLab/kb-whisper-small", "strict")
    assert path == str(rev_dir)


# --------------------------------------------------------------------------- #
#  remote path: prompt + temperature reach the request body
# --------------------------------------------------------------------------- #

def test_remote_transcribe_sends_prompt_and_temperature(monkeypatch):
    rt = importlib.reload(importlib.import_module("remote_transcribe"))
    captured = {}

    def fake_request(url, headers, payload=None, method="POST", timeout=8.0,
                     stream=False, parse="json"):
        captured["body"] = payload
        return b'{"text": "hej"}'

    monkeypatch.setattr(rt.http_pool, "request", fake_request)

    audio = np.ones(8000, dtype=np.float32) * 0.2
    out = rt.transcribe(audio, 16000, provider="staik", api_key="sk-st",
                        model="kb-whisper-large",
                        prompt="Johan Kalmar", temperature=0.0)
    assert out == "hej"
    body = captured["body"]
    assert b'name="prompt"' in body
    assert b"Johan Kalmar" in body
    assert b'name="temperature"' in body
