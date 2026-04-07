import re
from pathlib import Path
import numpy as np
from faster_whisper import WhisperModel

import corrections as corr_module

MODEL_DIR = Path.home() / ".freewispr-swedish" / "models"

# KBLab model mapping for Swedish Whisper
KBLAB_MODELS = {
    "tiny": "KBLab/kb-whisper-tiny",
    "base": "KBLab/kb-whisper-base",
    "small": "KBLab/kb-whisper-small",
    "medium": "KBLab/kb-whisper-medium",
    "large": "KBLab/kb-whisper-large",
}

# Model tiers - select best model based on hardware
MODEL_TIERS = {
    "compact": "tiny",     # CPU: fast, lower quality
    "normal": "small",     # CPU: balanced
    "advanced": "medium",  # GPU: best quality
}

# Common filler words / phrases to strip when filter_fillers=True (English)
_FILLERS_EN = re.compile(
    r'\b(um+|uh+|er+|ah+|hmm+|mhm|you know|i mean|'
    r'so um|so uh|well uh|basically|literally|right\?|okay so|'
    r'kind of|sort of)\b[,.]?',
    re.IGNORECASE,
)

# Swedish filler words / phrases
_FILLERS_SV = re.compile(
    r'\b(eh|em|öh|öhm|äh|ahm|liksom|typ|ba|bara|alltså|'
    r'liknande|sådär|kanske|ju|nog|väl|mm|mhm|aa|såhär)\b[,.]?',
    re.IGNORECASE | re.UNICODE,
)


def _punctuate(text: str) -> str:
    """Capitalize first letter and ensure terminal punctuation."""
    if not text:
        return text
    text = text[0].upper() + text[1:]
    if text[-1] not in '.?!':
        text += '.'
    return text


def _check_cuda() -> bool:
    """Check if CUDA (GPU) is available."""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def _get_device_and_compute(use_cuda: bool) -> tuple:
    """
    Determine device and compute type based on CUDA setting.
    Returns (device, compute_type, cuda_available).
    """
    cuda_available = _check_cuda()
    
    if use_cuda and cuda_available:
        return ("cuda", "float16", True)
    elif use_cuda and not cuda_available:
        print("CUDA begärt men ingen GPU hittades. Använder CPU.", flush=True)
        return ("cpu", "int8", False)
    else:
        return ("cpu", "int8", False)


def _select_model(model_tier: str, use_cuda: bool) -> str:
    """
    Select best model based on tier and CUDA availability.
    CPU users get smaller models for speed.
    GPU users get larger models for better quality.
    """
    base_model = MODEL_TIERS.get(model_tier, "small")
    
    if use_cuda and _check_cuda():
        # GPU available - use larger models
        if model_tier == "compact":
            return "base"  # Upgrade from tiny
        elif model_tier == "normal":
            return "small"  # Keep normal
        elif model_tier == "advanced":
            return "large"  # GPU can handle large
    else:
        # CPU - use smaller models for speed
        if model_tier == "advanced":
            return "small"  # Downgrade from large for CPU
        return base_model


class Transcriber:
    def __init__(self, model_size: str = "small", language: str = "sv",
                 filter_fillers: bool = False, auto_punctuate: bool = True,
                 use_cuda: bool = True, model_tier: str = "normal"):
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        self.language = language
        self.filter_fillers = filter_fillers
        self.auto_punctuate = auto_punctuate
        
        # Determine actual model to use based on tier and CUDA
        actual_model = _select_model(model_tier, use_cuda)
        device, compute_type, cuda_used = _get_device_and_compute(use_cuda)
        
        model_name = KBLAB_MODELS.get(actual_model, actual_model)
        
        print(f"Laddar Whisper '{actual_model}' ({model_name}) på {device}...", flush=True)
        if device == "cuda":
            print("GPU-detektion: Aktiv", flush=True)
        
        self.model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root=str(MODEL_DIR),
        )

    def _clean(self, text: str) -> str:
        if not self.filter_fillers:
            return text.strip()
        # Use Swedish fillers if language is Swedish, otherwise English
        if self.language == "sv":
            cleaned = _FILLERS_SV.sub("", text)
        else:
            cleaned = _FILLERS_EN.sub("", text)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        return cleaned.strip(" ,.")

    def transcribe(self, audio: np.ndarray) -> str:
        segments, _ = self.model.transcribe(
            audio,
            language=self.language,
            beam_size=1,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
        )
        text = self._clean(" ".join(s.text.strip() for s in segments))
        text = corr_module.apply(text)
        if self.auto_punctuate and text:
            text = _punctuate(text)
        return text
