import queue
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


class MeetingRecorder:
    """Continuously records mic, emitting chunks every `chunk_sec` seconds."""

    def __init__(self, chunk_sec: int = 20):
        self.chunk_samples = int(chunk_sec * SAMPLE_RATE)
        self._buf = []
        self._buf_len = 0
        self.recording = False
        self._stream = None
        self.chunks: queue.Queue = queue.Queue()

    def start(self):
        self._buf = []
        self._buf_len = 0
        self.recording = True
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            callback=self._cb,
            blocksize=int(SAMPLE_RATE * 0.1),
        )
        self._stream.start()

    def _cb(self, indata, frames, time, status):
        if not self.recording:
            return
        self._buf.append(indata.copy())
        self._buf_len += frames
        if self._buf_len >= self.chunk_samples:
            audio = np.concatenate(self._buf, axis=0).flatten()
            self.chunks.put(audio)
            self._buf = []
            self._buf_len = 0

    def stop(self) -> np.ndarray:
        self.recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._buf:
            return np.concatenate(self._buf, axis=0).flatten()
        return np.array([], dtype=np.float32)

    def get_chunk(self, timeout: float = 1.0):
        try:
            return self.chunks.get(timeout=timeout)
        except queue.Empty:
            return None
