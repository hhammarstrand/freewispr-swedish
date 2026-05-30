"""L5.2: remote audio compression (encode + fallback)."""
from __future__ import annotations

import importlib
import sys
import wave
from types import SimpleNamespace

import numpy as np


def test_encode_wav_default():
    rt = importlib.reload(importlib.import_module("remote_transcribe"))
    audio = np.zeros(16000, dtype=np.float32)
    data, ctype, filename, fmt = rt._encode_audio(audio, 16000, "wav")
    assert ctype == "audio/wav" and filename == "audio.wav" and fmt == "wav"
    # Valid WAV.
    import io
    with wave.open(io.BytesIO(data), "rb") as w:
        assert w.getframerate() == 16000


def test_encode_flac_falls_back_to_wav_without_soundfile(monkeypatch):
    rt = importlib.reload(importlib.import_module("remote_transcribe"))
    # Simulate soundfile being unavailable.
    monkeypatch.setitem(sys.modules, "soundfile", None)
    audio = np.zeros(8000, dtype=np.float32)
    data, ctype, filename, fmt = rt._encode_audio(audio, 16000, "flac")
    assert fmt == "wav"               # graceful fallback
    assert ctype == "audio/wav"


def test_encode_flac_uses_soundfile_when_present(monkeypatch):
    rt = importlib.reload(importlib.import_module("remote_transcribe"))

    def fake_write(buf, a, rate, format=None, subtype=None):
        buf.write(b"FAKEFLAC")

    monkeypatch.setitem(sys.modules, "soundfile",
                        SimpleNamespace(write=fake_write))
    audio = np.zeros(8000, dtype=np.float32)
    data, ctype, filename, fmt = rt._encode_audio(audio, 16000, "flac")
    assert data == b"FAKEFLAC"
    assert ctype == "audio/flac" and filename == "audio.flac" and fmt == "flac"


def test_transcribe_sends_chosen_format_filename(monkeypatch):
    rt = importlib.reload(importlib.import_module("remote_transcribe"))

    def fake_write(buf, a, rate, format=None, subtype=None):
        buf.write(b"OPUSDATA")

    monkeypatch.setitem(sys.modules, "soundfile",
                        SimpleNamespace(write=fake_write))
    captured = {}

    def fake_request(url, headers, payload=None, **kw):
        captured["body"] = payload
        return b'{"text": "hej"}'

    monkeypatch.setattr(rt.http_pool, "request", fake_request)
    audio = np.ones(8000, dtype=np.float32) * 0.2
    out = rt.transcribe(audio, 16000, provider="staik", api_key="sk",
                        model="kb-whisper-large", audio_format="opus")
    assert out == "hej"
    assert b'filename="audio.opus"' in captured["body"]
    assert b"audio/ogg" in captured["body"]
    assert b"OPUSDATA" in captured["body"]
