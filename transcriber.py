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


def _get_device() -> tuple:
    """Check if CUDA (GPU) is available, return (device, compute_type)."""
    try:
        import torch
        if torch.cuda.is_available():
            return ("cuda", "float16")
    except ImportError:
        pass
    return ("cpu", "int8")


class Transcriber:
    def __init__(self, model_size: str = "small", language: str = "sv",
                 filter_fillers: bool = False, auto_punctuate: bool = True):
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        self.language = language
        self.filter_fillers = filter_fillers
        self.auto_punctuate = auto_punctuate
        
        # Use KBLab Swedish model if available, otherwise use standard model
        model_name = KBLAB_MODELS.get(model_size, model_size)
        device, compute_type = _get_device()
        
        print(f"Laddar Whisper '{model_size}' ({model_name}) på {device}...", flush=True)
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
