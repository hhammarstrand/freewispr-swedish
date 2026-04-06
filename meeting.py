import threading
import datetime
from pathlib import Path

import numpy as np

from audio import MeetingRecorder
from transcriber import Transcriber

TRANSCRIPTS_DIR = Path.home() / ".freewispr" / "transcripts"


def _fmt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class MeetingMode:
    def __init__(self, transcriber: Transcriber, on_line=None, on_status=None):
        self.transcriber = transcriber
        self.recorder = MeetingRecorder(chunk_sec=20)
        self.on_line = on_line or (lambda line: None)
        self.on_status = on_status or (lambda msg: None)

        self._active = False
        self._lines = []
        self._time_offset = 0.0   # cumulative seconds of audio processed
        self._session_file: Path | None = None
        self._worker: threading.Thread | None = None

    # ------------------------------------------------------------------ public

    def start(self):
        TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        self._active = True
        self._lines = []
        self._time_offset = 0.0
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._session_file = TRANSCRIPTS_DIR / f"meeting_{ts}.txt"
        self._write_header()

        self.recorder.start()
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()
        if self.recorder.has_system_audio:
            self.on_status("Recording mic + system audio")
        else:
            self.on_status("Recording mic only")

    def stop(self) -> str:
        """Stop recording and return the path to the saved transcript."""
        self._active = False
        remaining = self.recorder.stop()
        if len(remaining) > 3200:
            self._process(remaining)
        self.on_status("Meeting ended")
        return str(self._session_file) if self._session_file else ""

    def get_transcript(self) -> str:
        return "\n".join(self._lines)

    # ----------------------------------------------------------------- private

    def _loop(self):
        while self._active:
            chunk = self.recorder.get_chunk(timeout=1.0)
            if chunk is not None:
                self._process(chunk)

    def _process(self, audio: np.ndarray):
        self.on_status("Transcribing…")
        chunk_duration = len(audio) / 16000
        segs = self.transcriber.transcribe_segments(audio, time_offset=self._time_offset)
        self._time_offset += chunk_duration
        for start, end, text in segs:
            if not text:
                continue
            line = f"[{_fmt(start)}] {text}"
            self._lines.append(line)
            self.on_line(line)
            self._append(line)
        status = "Recording mic + system audio" if self.recorder.has_system_audio else "Recording mic only"
        self.on_status(status)

    def _write_header(self):
        if self._session_file:
            with open(self._session_file, "w", encoding="utf-8") as f:
                f.write(f"freewispr Meeting Transcript\n")
                f.write(f"Started: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 50 + "\n\n")

    def _append(self, line: str):
        if self._session_file:
            with open(self._session_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
