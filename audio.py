import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000


class MicRecorder:
    """Records from mic while a hotkey is held."""

    def __init__(self):
        self.frames = []
        self.recording = False
        self._stream = None

    def start(self):
        self.frames = []
        self.recording = True
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            callback=self._cb,
        )
        self._stream.start()

    def _cb(self, indata, frames, time, status):
        if self.recording:
            self.frames.append(indata.copy())

    def stop(self) -> np.ndarray:
        self.recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if not self.frames:
            return np.array([], dtype=np.float32)
        return np.concatenate(self.frames, axis=0).flatten()
