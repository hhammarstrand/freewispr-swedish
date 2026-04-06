import re
from pathlib import Path
import numpy as np
from faster_whisper import WhisperModel

MODEL_DIR = Path.home() / ".freewispr" / "models"

# Common filler words / phrases to strip when filter_fillers=True
_FILLERS = re.compile(
    r'\b(um+|uh+|er+|ah+|hmm+|mhm|you know|i mean|'
    r'so um|so uh|well uh|basically|literally|right\?|okay so|'
    r'kind of|sort of)\b[,.]?',
    re.IGNORECASE,
)


class Transcriber:
    def __init__(self, model_size: str = "base", language: str = "en",
                 filter_fillers: bool = False):
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        self.language = language
        self.filter_fillers = filter_fillers
        self.model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
            download_root=str(MODEL_DIR),
        )

    def _clean(self, text: str) -> str:
        if not self.filter_fillers:
            return text.strip()
        cleaned = _FILLERS.sub("", text)
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
        return self._clean(" ".join(s.text.strip() for s in segments))
