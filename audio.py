import math
import logging
import time as time_module
import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly

log = logging.getLogger("freewispr")

TARGET_RATE = 16000  # Whisper expects 16 kHz

# Host API preference order on Windows (best first)
_API_PREF = ["WASAPI", "DirectSound", "MME"]

# Cached snapshots of sounddevice's device/host-api tables. They are static
# until the user plugs/unplugs a device, so re-querying on every keypress
# is wasted IO (sounddevice rebuilds them from PortAudio each call).
_devices_cache: list | None = None
_hostapis_cache: list | None = None


def _devices() -> list:
    global _devices_cache
    if _devices_cache is None:
        _devices_cache = list(sd.query_devices())
    return _devices_cache


def _hostapis() -> list:
    global _hostapis_cache
    if _hostapis_cache is None:
        _hostapis_cache = list(sd.query_hostapis())
    return _hostapis_cache


def invalidate_device_cache() -> None:
    """Clear cached device/host-api tables. Call after a device change."""
    global _devices_cache, _hostapis_cache
    _devices_cache = None
    _hostapis_cache = None


def _api_priority() -> dict[int, int]:
    """Map host-api index -> priority (lower = better)."""
    prio = {}
    for rank, pref in enumerate(_API_PREF):
        for i, api in enumerate(_hostapis()):
            if pref in api["name"]:
                prio[i] = rank
    return prio


def list_input_devices() -> list[dict]:
    """Return deduplicated input devices sorted by API preference for the UI."""
    prio = _api_priority()
    apis = {i: api["name"] for i, api in enumerate(_hostapis())}

    devices = []
    for i, dev in enumerate(_devices()):
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
    apis = {i: api["name"] for i, api in enumerate(_hostapis())}
    matches = []
    for i, dev in enumerate(_devices()):
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

    def __init__(self, device: str | dict | None = None):
        """``device`` accepts:
          * ``None`` — auto-select first available input.
          * ``str``  — legacy: a device name substring.
          * ``dict`` — structured id ``{"name": str, "api": str, "index": int}``;
            we try the exact (api, index) first, then fall back to name match
            so reordered USB devices still work.
        """
        self.frames: list[np.ndarray] = []
        self._total_samples = 0  # Track total for pre-allocated concat
        self.level = 0.0  # Current RMS level for UI visualization
        # Running sum of squares — lets stop() return RMS in O(1) without
        # the caller doing another full pass over the audio buffer.
        self._sumsq = 0.0
        self._sumsq_count = 0
        self.recording = False
        self._stream: sd.InputStream | None = None
        # Normalise to (name, api, index) tuple regardless of input shape.
        if isinstance(device, dict):
            self._device_name = device.get("name") or None
            self._device_api = device.get("api") or None
            self._device_index = device.get("index")
            if not isinstance(self._device_index, int):
                self._device_index = None
        else:
            self._device_name = device  # str | None
            self._device_api = None
            self._device_index = None
        self._last_status_log = 0.0

    def start(self):
        """Start recording. Tries multiple device/channel combos until one works."""
        self.frames = []
        self._total_samples = 0
        self.level = 0.0
        self._sumsq = 0.0
        self._sumsq_count = 0
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
        devs = _devices()
        apis = {i: api["name"] for i, api in enumerate(_hostapis())}

        # Highest priority: exact (api, index) match from a structured config.
        # This survives the device being renamed but not reordered.
        if self._device_index is not None and 0 <= self._device_index < len(devs):
            d = devs[self._device_index]
            if d["max_input_channels"] >= 1:
                api_name = apis.get(d["hostapi"], "?")
                if not self._device_api or api_name == self._device_api:
                    rate = int(d["default_samplerate"])
                    for ch in [1, d["max_input_channels"]]:
                        candidates.append((self._device_index, rate, ch,
                                           f"{d['name']} [{api_name}] (saved index)"))

        if self._device_name:
            # Fall back to name substring match across all APIs.
            for m in _find_device_by_name(self._device_name):
                name = devs[m["index"]]["name"]
                for ch in [1, m["channels"]]:
                    entry = (m["index"], m["rate"], ch,
                             f"{name} [{m['api']}]")
                    if entry not in candidates:
                        candidates.append(entry)

        # Then try all input devices sorted by API preference
        prio = _api_priority()
        all_devs = []
        for i, dev in enumerate(devs):
            if dev["max_input_channels"] < 1:
                continue
            rank = prio.get(dev["hostapi"], 99)
            all_devs.append((rank, i, dev))
        all_devs.sort(key=lambda x: x[0])

        for _, i, dev in all_devs:
            rate = int(dev["default_samplerate"])
            for ch in [1, dev["max_input_channels"]]:
                label = f"{dev['name']} (auto)"
                entry = (i, rate, ch, label)
                if entry not in candidates:
                    candidates.append(entry)

        return candidates

    def _cb(self, indata, frames, time, status):
        if status:
            now = time_module.monotonic()
            if now - self._last_status_log > 5.0:
                log.warning("Audio callback-status: %s", status)
                self._last_status_log = now
        if self.recording:
            chunk = indata.copy()
            self.frames.append(chunk)
            self._total_samples += chunk.shape[0]
            # Update level for UI visualization (fast: np.dot on small chunk)
            flat = chunk.ravel()
            n = len(flat)
            if n:
                ss = float(np.dot(flat, flat))
                self._sumsq += ss
                self._sumsq_count += n
                self.level = float(np.sqrt(ss / n))

    def rms(self) -> float:
        """Return RMS of all captured audio so far.

        Computed from the running sum-of-squares maintained by the audio
        callback — O(1) regardless of recording length, so the caller
        avoids a second pass over the buffer.
        """
        if self._sumsq_count == 0:
            return 0.0
        return float(np.sqrt(self._sumsq / self._sumsq_count))

    def stop_fast(self) -> tuple[list, int, int]:
        """Stop the stream cheaply and hand back raw frames.

        Returns ``(frames, total_samples, rate)`` without doing any concat or
        resample work — that runs in the transcription worker via
        :py:func:`finalize_audio`. Keeps the keyboard-hook thread responsive
        (Windows can disable a low-level hook that blocks > ~300 ms).
        """
        self.recording = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        frames = self.frames
        total = self._total_samples
        rate = getattr(self, "_rate", TARGET_RATE)
        # Detach so a subsequent start() doesn't share state with the worker.
        self.frames = []
        self._total_samples = 0
        return frames, total, rate

    def stop(self) -> np.ndarray:
        """Backward-compatible: stop + finalize in one call.

        Prefer :py:meth:`stop_fast` + :py:func:`finalize_audio` for the
        latency-sensitive dictation path.
        """
        frames, total, rate = self.stop_fast()
        return finalize_audio(frames, total, rate)


def finalize_audio(frames: list, total_samples: int, orig_rate: int) -> np.ndarray:
    """Concat frames, downmix to mono, and resample to 16 kHz.

    Pulled out of ``MicRecorder.stop`` so the keyboard-hook thread can hand
    raw frames to a worker thread for processing. On a 30 s recording at
    48 kHz this work takes ~20-80 ms and must not block the hook callback.
    """
    if not frames:
        return np.array([], dtype=np.float32)

    # Pre-allocated buffer concatenation (WhisperFlow pattern):
    # allocate once and copy — avoids repeated np.concatenate allocations.
    channels = frames[0].shape[1] if frames[0].ndim > 1 else 1
    if channels > 1:
        # Multi-channel: take first channel only (cheaper than mean and
        # equivalent for dictation; mics that need mixing are rare and
        # the first channel usually carries the primary signal).
        audio = np.empty(total_samples, dtype=np.float32)
        offset = 0
        for chunk in frames:
            n = chunk.shape[0]
            audio[offset:offset + n] = chunk[:, 0]
            offset += n
    else:
        audio = np.empty(total_samples, dtype=np.float32)
        offset = 0
        for chunk in frames:
            flat = chunk.ravel()  # ravel() avoids copy for contiguous arrays
            n = len(flat)
            audio[offset:offset + n] = flat
            offset += n

    log.info("Rå audio: shape=%s, dtype=%s, rate=%d, peak=%.4f",
             audio.shape, audio.dtype, orig_rate,
             float(np.abs(audio).max()) if audio.size else 0.0)
    resampled = _resample(audio, orig_rate)
    log.info("Resamplerad: %d → %d samples (%d→%dHz), peak=%.4f",
             len(audio), len(resampled), orig_rate, TARGET_RATE,
             float(np.abs(resampled).max()) if resampled.size else 0.0)
    return resampled
