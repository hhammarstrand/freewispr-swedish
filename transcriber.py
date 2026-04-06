from pathlib import Path
import numpy as np
from faster_whisper import WhisperModel

MODEL_DIR = Path.home() / ".freewispr" / "models"


class Transcriber:
    def __init__(self, model_size: str = "tiny", language: str = "en"):
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        self.language = language
        self.model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",       # fastest on CPU
            download_root=str(MODEL_DIR),
        )

    def transcribe(self, audio: np.ndarray) -> str:
        """Quick transcription — for dictation mode."""
        segments, _ = self.model.transcribe(
            audio,
            language=self.language,
            beam_size=1,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
        )
        return " ".join(s.text.strip() for s in segments)

    def transcribe_segments(self, audio: np.ndarray, time_offset: float = 0.0):
        """Returns list of (start, end, text) tuples — for meeting mode."""
        segments, _ = self.model.transcribe(
            audio,
            language=self.language,
            beam_size=2,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        result = []
        for s in segments:
            result.append((s.start + time_offset, s.end + time_offset, s.text.strip()))
        return result
