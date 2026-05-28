"""Microphone recording, channel handling and resampling to 16 kHz."""
import math
import logging
import threading
import time as time_module
import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly, firwin

log = logging.getLogger("freewispr")

TARGET_RATE = 16000  # Whisper expects 16 kHz

# --- Resampler selection -------------------------------------------------
# Prefer soxr (C library, 3-4x faster than scipy polyphase) when available.
# Fall back to scipy resample_poly with a cached FIR filter so the filter
# design cost (firwin) is paid only once per (up, down) ratio.
try:
    import soxr as _soxr

    def _resample(audio: np.ndarray, orig_rate: int) -> np.ndarray:
        """Resample *audio* from *orig_rate* to 16 kHz using libsoxr."""
        if orig_rate == TARGET_RATE:
            return audio
        return _soxr.resample(audio, orig_rate, TARGET_RATE, quality="HQ")

    log.debug("Using soxr for resampling")
except ImportError:
    # Cache FIR filter coefficients keyed by (up, down) so firwin only runs
    # once per sample-rate ratio.  Dictation always resamples from the same
    # mic rate to 16 kHz, so this cache has a 100 % hit rate after the first
    # call.
    _resample_filter_cache: dict[tuple[int, int], np.ndarray] = {}

    def _resample(audio: np.ndarray, orig_rate: int) -> np.ndarray:  # type: ignore[no-redef]
        """Resample using scipy polyphase filter with a cached FIR."""
        if orig_rate == TARGET_RATE:
            return audio
        g = math.gcd(TARGET_RATE, orig_rate)
        up = TARGET_RATE // g
        down = orig_rate // g
        key = (up, down)
        h = _resample_filter_cache.get(key)
        if h is None:
            # Replicate the filter that resample_poly builds internally:
            # Kaiser-windowed sinc, length 20*max(up,down)+1.
            max_rate = max(up, down)
            f_c = 1.0 / max_rate
            half_len = 10 * max_rate
            h = firwin(2 * half_len + 1, f_c, window=("kaiser", 5.0))
            _resample_filter_cache[key] = h
        return resample_poly(audio, up, down, window=h).astype(np.float32)
    log.debug("soxr not available; using scipy resample_poly with cached FIR")

# Hard cap on a single recording. At 48 kHz mono float32 this is ~23 MB,
# at 48 kHz stereo ~46 MB. Prevents a stuck hotkey from filling RAM.
MAX_RECORD_SECONDS = 120

# Host API preference order on Windows (best first)
_API_PREF = ["WASAPI", "DirectSound", "MME"]

# Cached snapshots of sounddevice's device/host-api tables. They are static
# until the user plugs/unplugs a device, so re-querying on every keypress
# is wasted IO (sounddevice rebuilds them from PortAudio each call).
_devices_cache: list | None = None
_hostapis_cache: list | None = None


def _select_level_channel(audio: np.ndarray) -> np.ndarray:
    """Return the channel with highest RMS from mono/stereo callback data."""
    if audio.ndim <= 1 or audio.shape[1] <= 1:
        return audio.ravel()
    # Some Windows/USB devices expose a silent left channel and put the mic on
    # the right channel. Pick the loudest channel instead of assuming channel 0.
    sums = np.einsum("ij,ij->j", audio, audio)
    return audio[:, int(np.argmax(sums))]


def _to_mono(audio: np.ndarray) -> np.ndarray:
    """Convert captured audio to mono without assuming the mic is channel 0."""
    if audio.ndim <= 1 or audio.shape[1] <= 1:
        return audio.ravel()
    sums = np.einsum("ij,ij->j", audio, audio)
    loudest = int(np.argmax(sums))
    if sums[loudest] > 0 and float(np.min(sums)) <= float(sums[loudest]) * 0.01:
        return audio[:, loudest]
    return audio.mean(axis=1, dtype=np.float32)


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


def _try_start(device: int, rate: int, channels: int, callback) -> sd.InputStream:
    """Try to open and start a stream. Raises on failure."""
    s = sd.InputStream(samplerate=rate, channels=channels,
                       dtype="float32", device=device, callback=callback)
    s.start()
    return s


class MicRecorder:
    """Start/stop microphone recording with pre-allocated ring buffer."""

    # How much audio to keep in the prewarm rolling buffer (seconds).
    # 0.5 s covers the typical OS device-open + first-frame latency window
    # without measurably increasing RAM (0.5 s * 48 kHz * 4 B ~= 96 KB).
    PREWARM_SECONDS = 0.5

    def __init__(self, device: str | dict | None = None):
        """``device`` accepts:
          * ``None`` — auto-select first available input.
          * ``str``  — legacy: a device name substring.
          * ``dict`` — structured id ``{"name": str, "api": str, "index": int}``;
            we try the exact (api, index) first, then fall back to name match
            so reordered USB devices still work.
        """
        # Pre-allocated ring buffer — written by the audio callback, read by
        # the worker on stop. Avoids per-callback np.copy + final concat pass.
        self._buffer: np.ndarray | None = None  # shape (capacity, channels) or (capacity,)
        self._buffer_capacity = 0
        self._buffer_offset = 0
        self._buffer_channels = 1
        self._buffer_overflow = False
        self.level = 0.0  # Current RMS level for UI visualization
        # Running sum of squares — lets stop() return RMS in O(1) without
        # the caller doing another full pass over the audio buffer.
        self._sumsq = 0.0
        self._sumsq_count = 0
        self.recording = False
        self._stream: sd.InputStream | None = None
        # Optional callback fired from the audio thread with the latest RMS
        # level (float). Used by the UI to drive the equalizer without a
        # polling timer. Must be cheap + thread-safe; the indicator throttles
        # and marshals to Tk.
        self.on_level = None  # type: ignore[assignment]
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

        # Prewarm state. When ``self._prewarming`` is True the audio callback
        # writes into ``self._prewarm_buf`` (a small rolling buffer that
        # always holds the most-recent PREWARM_SECONDS of audio) and skips
        # the main capture buffer. start() can then prepend that history
        # into the main buffer to eliminate the user-perceived startup
        # latency of opening the audio device.
        #
        # Sized lazily once we know the device samplerate. Storage is a flat
        # mono float32 array; if the device runs in stereo we downmix in the
        # callback before writing so the prepend stays cheap regardless of
        # channel count.
        self._prewarming = False
        self._prewarm_buf: np.ndarray | None = None
        self._prewarm_capacity = 0
        # Write head — wraps modulo capacity. Total samples ever written is
        # tracked separately so we know how many of the buffer's slots
        # actually contain real data on the first few writes.
        self._prewarm_write = 0
        self._prewarm_written = 0
        self._prewarm_lock = threading.Lock()
        # Set by prewarm_start(); stop_fast() reads it to decide whether to
        # close the stream or just flip back into prewarming mode.
        self._prewarm_requested = False

    def start(self):
        """Start recording. Tries multiple device/channel combos until one works."""
        # Fast path: the stream is already open from prewarm_start(). Just
        # flip the flag and prepend the cached prewarm history into the
        # main buffer so the worker sees ~PREWARM_SECONDS of audio that
        # was already captured before the user pressed the hotkey.
        if self._stream is not None and self._prewarming:
            with self._prewarm_lock:
                self._prewarming = False
                self._ensure_buffer(self._rate, self._buffer_channels)
                self._buffer_offset = 0
                self._sumsq = 0.0
                self._sumsq_count = 0
                self._buffer_overflow = False
                self.recording = True
                self._prepend_prewarm_locked()
            log.debug("start(): återanvänd öppen stream + prepend %d prewarm-samples",
                      self._buffer_offset)
            return

        # Defensive: if a previous start() never reached stop() (e.g. exception
        # in the caller), close the leaked stream before opening a new one.
        if self._stream is not None:
            try:
                self._stream.abort()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        self.level = 0.0
        self._sumsq = 0.0
        self._sumsq_count = 0
        self._buffer_offset = 0
        self._buffer_overflow = False
        self.recording = True
        self._prewarming = False

        candidates = self._build_candidates()
        last_err = None

        for dev_idx, rate, ch, label in candidates:
            try:
                # Pre-allocate buffer for this (rate, channels). Reuse across
                # subsequent starts when shape matches — saves an allocation.
                self._ensure_buffer(rate, ch)
                self._stream = _try_start(dev_idx, rate, ch, self._cb)
                self._rate = rate
                log.info("Inspelning startad: %s (dev=%d, %dHz, %dch)",
                         label, dev_idx, rate, ch)
                return
            except Exception as e:
                last_err = e

        raise last_err or RuntimeError("Ingen mikrofon kunde öppnas")

    def _ensure_buffer(self, rate: int, channels: int) -> None:
        """Allocate or re-allocate the ring buffer for (rate, channels)."""
        capacity = rate * MAX_RECORD_SECONDS
        if (self._buffer is None
                or self._buffer_capacity != capacity
                or self._buffer_channels != channels):
            if channels > 1:
                self._buffer = np.empty((capacity, channels), dtype=np.float32)
            else:
                self._buffer = np.empty(capacity, dtype=np.float32)
            self._buffer_capacity = capacity
            self._buffer_channels = channels

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
                    for ch in sorted(set([1, d["max_input_channels"]])):
                        candidates.append((self._device_index, rate, ch,
                                           f"{d['name']} [{api_name}] (saved index)"))

        if self._device_name:
            # Fall back to name substring match across all APIs.
            for m in _find_device_by_name(self._device_name):
                name = devs[m["index"]]["name"]
                for ch in sorted(set([1, m["channels"]])):
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
            for ch in sorted(set([1, dev["max_input_channels"]])):
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

        # Prewarm path: write a downmixed mono copy into the rolling buffer
        # so start() can prepend it. We deliberately don't touch the level
        # callback here — it would cause the indicator equalizer to dance
        # while idle, which is misleading (nothing is being transcribed).
        if self._prewarming and self._prewarm_buf is not None:
            n = indata.shape[0]
            if n <= 0:
                return
            # Downmix to mono for compactness. The main buffer's channel
            # count may differ but the prepended history doesn't need stereo
            # — Whisper transcribes mono anyway.
            if indata.ndim > 1 and indata.shape[1] > 1:
                mono = _to_mono(indata[:n])
            else:
                mono = indata[:n].ravel() if indata.ndim > 1 else indata[:n]
            cap = self._prewarm_capacity
            w = self._prewarm_write
            # Wrap-around write. At most two contiguous slices.
            first = min(n, cap - w)
            self._prewarm_buf[w:w + first] = mono[:first]
            rest = n - first
            if rest > 0:
                self._prewarm_buf[:rest] = mono[first:first + rest]
                self._prewarm_write = rest
            else:
                self._prewarm_write = (w + n) % cap
            self._prewarm_written = min(cap, self._prewarm_written + n)
            return

        if not self.recording or self._buffer is None:
            return
        n = indata.shape[0]
        if n <= 0:
            return
        remaining = self._buffer_capacity - self._buffer_offset
        if remaining <= 0:
            if not self._buffer_overflow:
                log.warning("Inspelning nådde %d s max-cap, slutar buffra",
                            MAX_RECORD_SECONDS)
                self._buffer_overflow = True
            return
        n = min(n, remaining)
        # Copy directly into the pre-allocated arena — no per-callback
        # np.ndarray allocation, no final concat pass in stop_fast().
        if self._buffer_channels > 1:
            chunk = indata[:n]
            self._buffer[self._buffer_offset:self._buffer_offset + n] = chunk
            chunk_for_level = _select_level_channel(chunk)
        else:
            chunk_for_level = indata[:n].ravel() if indata.ndim > 1 else indata[:n]
            self._buffer[self._buffer_offset:self._buffer_offset + n] = chunk_for_level
        self._buffer_offset += n
        # Update level/RMS using the data we already have in cache.
        if chunk_for_level.size:
            ss = float(np.dot(chunk_for_level, chunk_for_level))
            self._sumsq += ss
            self._sumsq_count += chunk_for_level.size
            self.level = float(np.sqrt(ss / chunk_for_level.size))
            cb = self.on_level
            if cb is not None:
                try:
                    cb(self.level)
                except Exception:
                    # Never let a UI callback take down the audio thread.
                    pass

    def rms(self) -> float:
        """Return RMS of all captured audio so far.

        Computed from the running sum-of-squares maintained by the audio
        callback — O(1) regardless of recording length, so the caller
        avoids a second pass over the buffer.
        """
        if self._sumsq_count == 0:
            return 0.0
        return float(np.sqrt(self._sumsq / self._sumsq_count))

    def stop_fast(self) -> tuple[np.ndarray, int, int]:
        """Stop the stream cheaply and hand back the captured audio view.

        Returns ``(audio_view, channels, rate)``. ``audio_view`` is a *view*
        into the pre-allocated ring buffer — the worker must use it before
        the next ``start()`` call (which may overwrite the buffer in place).
        For dictation that's always safe because start/stop alternate with
        the worker thread consuming each buffer in order.

        Keeps the keyboard-hook thread responsive (Windows can disable a
        low-level hook that blocks > ~300 ms).

        Behaviour depends on whether prewarm mode is requested:
          * ``self._prewarm_requested`` (set by ``prewarm_start``): keep the
            stream open and flip back into prewarming so the next start()
            still benefits from the rolling history.
          * Otherwise: abort and close the stream as before.
        """
        self.recording = False
        rate = getattr(self, "_rate", TARGET_RATE)
        view_offset = self._buffer_offset
        if self._buffer is None or view_offset == 0:
            captured = np.empty(0, dtype=np.float32)
        else:
            view = self._buffer[:view_offset]
            # Copy so the worker can safely process while a new recording
            # starts. Contiguous, ~23 MB worst case (120 s @ 48 kHz mono).
            captured = view.copy()

        if self._prewarm_requested and self._stream is not None:
            # Keep stream open, drop history that overlapped with the
            # captured segment so we don't double-count it next time.
            with self._prewarm_lock:
                self._prewarming = True
                self._prewarm_write = 0
                self._prewarm_written = 0
            return captured, self._buffer_channels, rate

        # Closing path — same as before prewarm existed.
        if self._stream:
            try:
                self._stream.abort()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        return captured, self._buffer_channels, rate

    def stop(self) -> np.ndarray:
        """Backward-compatible: stop + finalize in one call.

        Prefer :py:meth:`stop_fast` + :py:func:`finalize_audio` for the
        latency-sensitive dictation path.
        """
        audio, channels, rate = self.stop_fast()
        return finalize_audio(audio, channels, rate)

    # -- prewarm ------------------------------------------------------------- #

    def prewarm_start(self) -> bool:
        """Open the audio stream now and start filling the prewarm buffer.

        Returns True on success, False if no device could be opened. Failure
        is non-fatal — the next start() call will open the stream on demand
        the old way. Used by main.py at boot and after Settings save when
        the user has opted into prewarm.
        """
        if self._stream is not None:
            # Already open. Ensure we're in the right mode.
            with self._prewarm_lock:
                self._prewarm_requested = True
                if not self.recording:
                    self._prewarming = True
                    self._prewarm_write = 0
                    self._prewarm_written = 0
            return True

        candidates = self._build_candidates()
        last_err = None
        for dev_idx, rate, ch, label in candidates:
            try:
                self._ensure_buffer(rate, ch)
                # Allocate the prewarm rolling buffer for this samplerate.
                self._prewarm_capacity = max(1, int(rate * self.PREWARM_SECONDS))
                self._prewarm_buf = np.zeros(self._prewarm_capacity,
                                             dtype=np.float32)
                self._prewarm_write = 0
                self._prewarm_written = 0
                self._prewarming = True
                self._prewarm_requested = True
                self._stream = _try_start(dev_idx, rate, ch, self._cb)
                self._rate = rate
                log.info("Prewarm-stream öppen: %s (dev=%d, %dHz, %dch, "
                         "buffer=%.0f ms)",
                         label, dev_idx, rate, ch,
                         self.PREWARM_SECONDS * 1000)
                return True
            except Exception as e:
                last_err = e

        log.warning("Kunde inte öppna prewarm-stream: %s", last_err)
        self._prewarming = False
        self._prewarm_requested = False
        return False

    def _prepend_prewarm_locked(self) -> None:
        """Copy the prewarm rolling buffer into the start of the main buffer.

        Caller must hold ``self._prewarm_lock``. Idempotent on already-
        flushed prewarm state (capacity 0 or no data written).
        """
        buf = self._prewarm_buf
        if buf is None or self._prewarm_capacity == 0 or self._prewarm_written == 0:
            return
        written = self._prewarm_written
        write = self._prewarm_write
        cap = self._prewarm_capacity
        # Read in chronological order. If we've wrapped, the oldest sample
        # is at write%cap; otherwise it's at 0.
        if written < cap:
            history = buf[:written]
        else:
            history = np.concatenate((buf[write:], buf[:write]))

        # Pre-warm is captured as mono. If the main buffer is stereo (rare
        # for laptop mics but happens on USB interfaces) we duplicate the
        # mono history into both channels — Whisper downmixes again later.
        n = len(history)
        target_remaining = self._buffer_capacity - self._buffer_offset
        n = min(n, target_remaining)
        if n <= 0:
            return
        if self._buffer_channels > 1 and self._buffer is not None and self._buffer.ndim > 1:
            self._buffer[self._buffer_offset:self._buffer_offset + n, :] = \
                history[:n, None]
        elif self._buffer is not None:
            self._buffer[self._buffer_offset:self._buffer_offset + n] = history[:n]
        self._buffer_offset += n
        # Reset the prewarm cursor — anything new from the callback after
        # start() goes into the main buffer, not the prewarm rolling area.
        self._prewarm_write = 0
        self._prewarm_written = 0

    def shutdown(self) -> None:
        """Hard-close the stream regardless of prewarm state. Call at app exit."""
        self._prewarm_requested = False
        self._prewarming = False
        self.recording = False
        if self._stream is not None:
            try:
                self._stream.abort()
                self._stream.close()
            except Exception:
                pass
            self._stream = None


def finalize_audio(audio: np.ndarray, channels: int, orig_rate: int) -> np.ndarray:
    """Downmix to mono and resample to 16 kHz.

    Pulled out of ``MicRecorder.stop`` so the keyboard-hook thread can hand
    raw audio to a worker thread for processing. On a 30 s recording at
    48 kHz this work takes ~20-80 ms and must not block the hook callback.

    Accepts either a 1-D mono buffer or a 2-D ``(samples, channels)`` array;
    multi-channel input is converted to mono by selecting a lone active
    channel (common with USB mics) or averaging balanced stereo channels.
    """
    if audio is None or audio.size == 0:
        return np.array([], dtype=np.float32)

    if audio.ndim > 1 and audio.shape[1] > 1:
        mono = np.ascontiguousarray(_to_mono(audio))
    else:
        mono = audio.ravel()

    log.info("Rå audio: shape=%s, dtype=%s, rate=%d, peak=%.4f",
             mono.shape, mono.dtype, orig_rate,
             max(abs(float(mono.min())), abs(float(mono.max()))) if mono.size else 0.0)
    resampled = _resample(mono, orig_rate)
    log.info("Resamplerad: %d -> %d samples (%d->%dHz), peak=%.4f",
             len(mono), len(resampled), orig_rate, TARGET_RATE,
             max(abs(float(resampled.min())), abs(float(resampled.max()))) if resampled.size else 0.0)
    return resampled
