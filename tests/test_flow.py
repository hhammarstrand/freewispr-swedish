"""AP6: flow mode — silence segmentation, toggle, local-only guard."""
from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture
def flow(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper",
                        SimpleNamespace(WhisperModel=object))
    return importlib.reload(importlib.import_module("flow"))


# --------------------------------------------------------------------------- #
#  split_on_silence
# --------------------------------------------------------------------------- #

def test_split_on_silence_separates_two_utterances(flow):
    rate = 16000
    speech = np.ones(rate, dtype=np.float32) * 0.2          # 1 s voiced
    silence = np.zeros(int(rate * 1.0), dtype=np.float32)   # 1 s silence
    audio = np.concatenate([speech, silence, speech])
    chunks = flow.split_on_silence(audio, rate)
    assert len(chunks) == 2


def test_split_on_silence_keeps_short_pauses_together(flow):
    rate = 16000
    speech = np.ones(rate, dtype=np.float32) * 0.2
    short_gap = np.zeros(int(rate * 0.2), dtype=np.float32)  # < min_silence
    audio = np.concatenate([speech, short_gap, speech])
    chunks = flow.split_on_silence(audio, rate)
    assert len(chunks) == 1


def test_split_on_silence_empty(flow):
    assert flow.split_on_silence(np.empty(0, dtype=np.float32), 16000) == []
    assert flow.split_on_silence(np.zeros(16000, dtype=np.float32), 16000) == []


# --------------------------------------------------------------------------- #
#  toggle + local-only guard
# --------------------------------------------------------------------------- #

def test_flow_refuses_remote_provider(flow, monkeypatch):
    monkeypatch.setattr(flow, "MicRecorder", lambda device=None: SimpleNamespace())
    status = []
    fm = flow.FlowMode(
        transcriber=SimpleNamespace(transcription_provider="staik"),
        on_status=status.append)
    fm.start()
    assert fm.active is False
    assert any("lokal" in s for s in status)


def test_flow_toggle_starts_and_stops(flow, monkeypatch):
    monkeypatch.setattr(flow, "MicRecorder",
                        lambda device=None: SimpleNamespace(shutdown=lambda: None))
    fm = flow.FlowMode(
        transcriber=SimpleNamespace(transcription_provider="local"))
    # Don't run the real audio loop.
    monkeypatch.setattr(fm, "_loop", lambda: None)

    assert fm.toggle() is True
    assert fm.active is True
    assert fm.toggle() is False
    assert fm.active is False


# --------------------------------------------------------------------------- #
#  _process_audio transcribes chunks and pastes them
# --------------------------------------------------------------------------- #

def test_process_audio_transcribes_and_pastes(flow, monkeypatch):
    monkeypatch.setattr(flow, "MicRecorder", lambda device=None: SimpleNamespace())
    monkeypatch.setattr(flow, "finalize_audio",
                        lambda audio, ch, rate: audio.astype(np.float32))
    monkeypatch.setattr(flow, "split_on_silence",
                        lambda audio, rate, min_rms=0.003: [audio])
    pasted = []
    monkeypatch.setattr(flow, "paste_text", lambda text: pasted.append(text))

    fm = flow.FlowMode(
        transcriber=SimpleNamespace(
            transcription_provider="local",
            transcribe=lambda chunk: "hej flow"))
    fm._active = True
    fm._process_audio(np.ones(16000, dtype=np.float32), 1, 16000)
    assert pasted == ["hej flow"]
