"""Hardware detection + model-size recommendation.

The default model is ``small`` so machines without a GPU stay responsive, but a
user with a capable NVIDIA GPU can run the far more accurate ``large`` KBLab
model at low latency (``kb-whisper-large`` ≈ 5.4 % WER vs ``small`` ≈ 9 %). This
module turns detected VRAM into a recommended model size so the first-run
dialog can pre-select the best model the hardware can comfortably handle.

Detection is best-effort and never raises: torch is an optional CUDA-only
dependency, so any failure is treated as "no GPU" → ``small``.
"""
from __future__ import annotations

import logging

log = logging.getLogger("freewispr")

# (min_vram_gib, model_size), checked high → low. Thresholds are deliberately
# conservative: they include headroom for activations and for other apps using
# the GPU, so we never recommend a model that risks an OOM mid-dictation. CT2
# int8_float16 footprints are well under these, leaving room for float16 too.
_VRAM_TIERS: tuple[tuple[float, str], ...] = (
    (6.0, "large"),
    (4.0, "medium"),
)

# The safe fallback for no GPU / unknown / low VRAM.
DEFAULT_MODEL = "small"


def recommend_model_size(vram_gib: float | None) -> str:
    """Recommend a KBLab model size for the detected GPU VRAM.

    ``None`` (no CUDA GPU detected) or VRAM below the lowest tier returns the
    CPU-friendly default. Pure function — no imports, trivially testable.
    """
    if vram_gib is None:
        return DEFAULT_MODEL
    for min_gib, model in _VRAM_TIERS:
        if vram_gib >= min_gib:
            return model
    return DEFAULT_MODEL


def detect_gpu_vram_gib() -> float | None:
    """Total VRAM (GiB) of the primary CUDA device, or ``None``.

    Returns ``None`` when torch isn't installed, no CUDA device is present, or
    anything goes wrong — callers treat that as "no GPU". Never raises.
    """
    try:
        import torch
        if not torch.cuda.is_available():
            return None
        props = torch.cuda.get_device_properties(0)
        gib = props.total_memory / (1024 ** 3)
        log.info("CUDA-GPU upptäckt: %s, %.1f GiB VRAM",
                 getattr(props, "name", "?"), gib)
        return gib
    except Exception as e:
        log.debug("Ingen CUDA-GPU för modellrekommendation: %s", e)
        return None


def recommend_model() -> str:
    """Detect VRAM and return the recommended model size (convenience)."""
    return recommend_model_size(detect_gpu_vram_gib())
