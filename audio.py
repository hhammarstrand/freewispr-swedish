import math
import logging
import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly

log = logging.getLogger("freewispr")

TARGET_RATE = 16000  # Whisper expects 16 kHz

# Host API preference order on Windows (best first)
_API_PREF = ["WASAPI", "DirectSound", "MME"]


def _api_priority() -> dict[int, int]:
    """Map host-api index -> priority (lower = better)."""
    prio = {}
    for rank, pref in enumerate(_API_PREF):
        for i, api in enumerate(sd.query_hostapis()):
            if pref in api["name"]:
                prio[i] = rank
    return prio


def list_input_devices() -> list[dict]:
    """Return deduplicated input devices sorted by API preference for the UI."""
    prio = _api_priority()
    apis = {i: api["name"] for i, api in enumerate(sd.query_hostapis())}

    devices = []
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] < 1:
            continue
        devices.append({
            "index": i,
            "name": dev["name"],
            "api": apis.get(dev["hostapi"], "?"),
            "rate": int(dev["default_samplerate"]),
            "channels": dev["max_input_channels"],
            "_rank": prio.get(dev["hostapi"], 99),
        })

    devices.sort(key=lambda d: d["_rank"])
    seen = set()
    unique = []
    for d in devices:
        if d["name"] not in seen:
            seen.add(d["name"])
            unique.append(d)
    return unique


def _find_device_by_name(name: str) -> list[dict]:
    """Find all device entries matching a name, sorted by API preference."""
    prio = _api_priority()
    apis = {i: api["name"] for i, api in enumerate(sd.query_hostapis())}
    matches = []
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] < 1:
            continue
        if name in dev["name"]:
            matches.append({
                "index": i,
                "rate": int(dev["default_samplerate"]),
                "channels": dev["max_input_channels"],
                "api": apis.get(dev["hostapi"], "?"),
                "_rank": prio.get(dev["hostapi"], 99),
            })
    matches.sort(key=lambda d: d["_rank"])
    return matches


def _resample(audio: np.ndarray, orig_rate: int) -> np.ndarray:
    """Resample audio from orig_rate to 16 kHz using polyphase filter.

    Uses scipy.signal.resample_poly which applies a proper anti-alias
    FIR filter before decimation — critical for Whisper accuracy.
    Linear interpolation causes aliasing artefacts that ruin transcription.
    """
    if orig_rate == TARGET_RATE:
        return audio
    # Find the simplest up/down ratio
    g = math.gcd(TARGET_RATE, orig_rate)
    up = TARGET_RATE // g
    down = orig_rate // g
    return resample_poly(audio, up, down).astype(np.float32)


def _try_start(device: int, rate: int, channels: int, callback) -> sd.InputStream:
    """Try to open and start a stream. Raises on failure."""
    s = sd.InputStream(samplerate=rate, channels=channels,
                       dtype="float32", device=device, callback=callback)
    s.start()
    return s


class MicRecorder:
    """Records from mic while a hotkey is held."""

    def __init__(self, device_name: str | None = None):
        self.frames: list[np.ndarray] = []
        self.recording = False
        self._stream: sd.InputStream | None = None
        self._device_name = device_name

    def start(self):
        """Start recording. Tries multiple device/channel combos until one works."""
        self.frames = []
        self.recording = True

        candidates = self._build_candidates()
        last_err = None

        for dev_idx, rate, ch, label in candidates:
            try:
                self._stream = _try_start(dev_idx, rate, ch, self._cb)
                self._rate = rate
                log.info("Inspelning startad: %s (dev=%d, %dHz, %dch)",
                         label, dev_idx, rate, ch)
                return
            except Exception as e:
                last_err = e

        raise last_err or RuntimeError("Ingen mikrofon kunde oppnas")

    def _build_candidates(self) -> list[tuple[int, int, int, str]]:
        """Build ordered list of (device_idx, rate, channels, label) to try."""
        candidates = []

        if self._device_name:
            # User picked a specific device — try all APIs for it
            for m in _find_device_by_name(self._device_name):
                name = sd.query_devices(m["index"])["name"]
                for ch in [1, m["channels"]]:
                    candidates.append((m["index"], m["rate"], ch,
                                       f"{name} [{m['api']}]"))

        # Then try all input devices sorted by API preference
        prio = _api_priority()
        all_devs = []
        for i, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] < 1:
                continue
            rank = prio.get(dev["hostapi"], 99)
            all_devs.append((rank, i, dev))
        all_devs.sort()

        for _, i, dev in all_devs:
            rate = int(dev["default_samplerate"])
            for ch in [1, dev["max_input_channels"]]:
                label = f"{dev['name']} (auto)"
                entry = (i, rate, ch, label)
                if entry not in candidates:
                    candidates.append(entry)

        return candidates

    def _cb(self, indata, frames, time, status):
        if self.recording:
            self.frames.append(indata.copy())

    def stop(self) -> np.ndarray:
        self.recording = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if not self.frames:
            return np.array([], dtype=np.float32)
        audio = np.concatenate(self.frames, axis=0)
        orig_rate = getattr(self, "_rate", TARGET_RATE)
        log.info("Rå audio: shape=%s, dtype=%s, rate=%d, peak=%.4f",
                 audio.shape, audio.dtype, orig_rate, np.abs(audio).max())
        if audio.ndim > 1 and audio.shape[1] > 1:
            audio = audio.mean(axis=1)
        audio = audio.flatten()
        resampled = _resample(audio, orig_rate)
        log.info("Resamplerad: %d → %d samples (%d→%dHz), peak=%.4f",
                 len(audio), len(resampled), orig_rate, TARGET_RATE,
                 np.abs(resampled).max())
        return resampled
