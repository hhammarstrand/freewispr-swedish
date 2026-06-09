"""Hardware detection + model-size recommendation."""
from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest


def _hw():
    return importlib.import_module("hardware")


@pytest.mark.parametrize("vram,expected", [
    (None, "small"),    # no GPU
    (2.0, "small"),     # tiny GPU
    (3.9, "small"),     # just below medium tier
    (4.0, "medium"),    # medium tier boundary
    (5.9, "medium"),    # just below large tier
    (6.0, "large"),     # large tier boundary
    (24.0, "large"),    # big card
])
def test_recommend_model_size(vram, expected):
    assert _hw().recommend_model_size(vram) == expected


def test_detect_vram_none_without_torch(monkeypatch):
    # No torch installed → None (treated as no GPU), never raises.
    hw = _hw()
    monkeypatch.setitem(sys.modules, "torch", None)  # import torch → TypeError
    assert hw.detect_gpu_vram_gib() is None


def test_detect_vram_none_when_cuda_unavailable(monkeypatch):
    hw = _hw()
    fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert hw.detect_gpu_vram_gib() is None


def test_detect_vram_reads_device_properties(monkeypatch):
    hw = _hw()
    props = SimpleNamespace(name="RTX 4070", total_memory=12 * 1024 ** 3)
    fake_torch = SimpleNamespace(cuda=SimpleNamespace(
        is_available=lambda: True,
        get_device_properties=lambda i: props,
    ))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert hw.detect_gpu_vram_gib() == pytest.approx(12.0, abs=0.01)
    # 12 GiB → large.
    assert hw.recommend_model_size(hw.detect_gpu_vram_gib()) == "large"


def test_detect_vram_swallows_errors(monkeypatch):
    hw = _hw()
    def boom(i):
        raise RuntimeError("driver exploded")
    fake_torch = SimpleNamespace(cuda=SimpleNamespace(
        is_available=lambda: True, get_device_properties=boom))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert hw.detect_gpu_vram_gib() is None  # never raises
