import queue
import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000


def _resample(audio: np.ndarray, orig_sr: int) -> np.ndarray:
    """Resample audio to SAMPLE_RATE using linear interpolation."""
    if orig_sr == SAMPLE_RATE:
        return audio
    n_out = int(len(audio) * SAMPLE_RATE / orig_sr)
    return np.interp(
        np.linspace(0, len(audio) - 1, n_out),
        np.arange(len(audio)),
        audio,
    ).astype(np.float32)


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
    """
    Continuously records mic + system audio (WASAPI loopback), mixing both.
    Falls back to mic-only if loopback is unavailable.
    Emits mixed chunks every `chunk_sec` seconds via self.chunks queue.
    """

    def __init__(self, chunk_sec: int = 20):
        self.chunk_samples = int(chunk_sec * SAMPLE_RATE)
        self._mic_buf: list = []
        self._sys_buf: list = []
        self._mic_len: int = 0
        self._sys_native_sr: int = SAMPLE_RATE
        self.recording = False
        self._mic_stream = None
        self._sys_stream = None
        self.has_system_audio = False
        self.chunks: queue.Queue = queue.Queue()

    # ------------------------------------------------------------------ public

    def start(self):
        self._mic_buf = []
        self._sys_buf = []
        self._mic_len = 0
        self.recording = True
        self.has_system_audio = False

        # Mic stream
        self._mic_stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            callback=self._mic_cb,
            blocksize=int(SAMPLE_RATE * 0.1),
        )
        self._mic_stream.start()

        # System loopback stream (WASAPI)
        try:
            out_idx = sd.default.device[1]
            dev_info = sd.query_devices(out_idx)
            native_sr = int(dev_info["default_samplerate"])
            native_ch = min(int(dev_info["max_output_channels"]), 2)
            self._sys_native_sr = native_sr

            wasapi = sd.WasapiSettings(loopback=True)
            self._sys_stream = sd.InputStream(
                device=out_idx,
                samplerate=native_sr,
                channels=native_ch,
                dtype="float32",
                extra_settings=wasapi,
                callback=self._sys_cb,
                blocksize=int(native_sr * 0.1),
            )
            self._sys_stream.start()
            self.has_system_audio = True
            print("System audio (loopback) active — capturing mic + speakers", flush=True)
        except Exception as e:
            print(f"System audio unavailable, mic only: {e}", flush=True)
            self._sys_stream = None

    def stop(self) -> np.ndarray:
        self.recording = False
        if self._mic_stream:
            self._mic_stream.stop()
            self._mic_stream.close()
            self._mic_stream = None
        if self._sys_stream:
            self._sys_stream.stop()
            self._sys_stream.close()
            self._sys_stream = None
        return self._mix_remaining()

    def get_chunk(self, timeout: float = 1.0):
        try:
            return self.chunks.get(timeout=timeout)
        except queue.Empty:
            return None

    # ----------------------------------------------------------------- private

    def _mic_cb(self, indata, frames, time, status):
        if not self.recording:
            return
        self._mic_buf.append(indata.copy())
        self._mic_len += frames
        if self._mic_len >= self.chunk_samples:
            self._emit_chunk()

    def _sys_cb(self, indata, frames, time, status):
        if not self.recording:
            return
        # Convert stereo → mono if needed
        mono = indata.mean(axis=1, keepdims=True) if indata.shape[1] > 1 else indata.copy()
        self._sys_buf.append(mono)

    def _emit_chunk(self):
        mic = np.concatenate(self._mic_buf, axis=0).flatten()
        self._mic_buf = []
        self._mic_len = 0
        mixed = self._mix(mic, self._sys_buf, clear_sys=True)
        self.chunks.put(mixed)

    def _mix_remaining(self) -> np.ndarray:
        if not self._mic_buf:
            return np.array([], dtype=np.float32)
        mic = np.concatenate(self._mic_buf, axis=0).flatten()
        self._mic_buf = []
        return self._mix(mic, self._sys_buf, clear_sys=True)

    def _mix(self, mic: np.ndarray, sys_buf: list, clear_sys: bool = False) -> np.ndarray:
        if not self.has_system_audio or not sys_buf:
            return mic
        sys_raw = np.concatenate(sys_buf, axis=0).flatten()
        if clear_sys:
            self._sys_buf = []
        sys_resampled = _resample(sys_raw, self._sys_native_sr)
        # Match lengths
        n = min(len(mic), len(sys_resampled))
        mixed = (mic[:n] * 0.6 + sys_resampled[:n] * 0.8)
        # Normalise to prevent clipping
        peak = np.abs(mixed).max()
        if peak > 1.0:
            mixed = mixed / peak
        return mixed.astype(np.float32)
