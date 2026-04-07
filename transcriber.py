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
    Returns (device, compute_type, cuda_used).
    """
    cuda_available = _check_cuda()
    
    if use_cuda and cuda_available:
        return ("cuda", "float16", True)
    elif use_cuda and not cuda_available:
        print("CUDA begärt men ingen GPU hittades. Använder CPU.", flush=True)
        return ("cpu", "int8", False)
    else:
        return ("cpu", "int8", False)


class Transcriber:
    def __init__(self, model_size: str = "small", language: str = "sv",
                 filter_fillers: bool = False, auto_punctuate: bool = True,
                 use_cuda: bool = True):
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        self.language = language
        self.filter_fillers = filter_fillers
        self.auto_punctuate = auto_punctuate
        
        # Get the KBLab model name
        model_name = KBLAB_MODELS.get(model_size, model_size)
        
        # Determine device and compute type
        device, compute_type, cuda_used = _get_device_and_compute(use_cuda)
        
        print(f"Laddar Whisper '{model_size}' ({model_name}) på {device}...", flush=True)
        if cuda_used:
            print("GPU: NVIDIA CUDA aktiverad", flush=True)
        
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
