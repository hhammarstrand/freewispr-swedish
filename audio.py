"""Microphone recording, channel handling and resampling to 16 kHz."""
import math
import logging
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


def _reinit_portaudio() -> None:
    """Best-effort re-init of PortAudio so its device table + default device
    reflect the *current* OS state (mics plugged/unplugged, default switched).

    sounddevice/PortAudio snapshot the device list at init and never refresh
    it on their own, so without this the app keeps following whatever was the
    default when the process started. Teams stays current because it talks to
    the Windows audio engine directly; this is our equivalent. Private API,
    so it's guarded and a no-op when unavailable (e.g. the test stub).
    """
    try:
        if hasattr(sd, "_terminate") and hasattr(sd, "_initialize"):
            sd._terminate()
            sd._initialize()
    except Exception as e:
        log.debug("PortAudio re-init hoppades över: %s", e)


# Endpoints auto-select must never pick: the Realtek "Stereo Mix" loopback
# (records system *output*, not the mic) and nameless phantom WDM-KS endpoints
# Windows exposes as "<something> ()" — they open but deliver silence/0 samples.
_BLACKLIST_SUBSTR = ("stereo mix",)


def _is_blacklisted_input(name: str) -> bool:
    """True for input endpoints auto-select should skip (loopback/phantoms).

    Explicit user selection is *not* filtered through here — only the auto
    fallback is, so a user who deliberately picks "Stereo Mix" still gets it.
    """
    n = (name or "").strip().lower()
    if not n:
        return True
    if any(s in n for s in _BLACKLIST_SUBSTR):
        return True
    # "Mikrofonuppsättning 1 ()", "Input ()": empty device descriptor = phantom.
    if n.endswith("()"):
        return True
    return False


def _default_input_index() -> int | None:
    """Windows default INPUT device index, or None. This is what Teams follows
    so swapping the default mic (laptop ↔ Yealink ↔ AirPods) is seamless."""
    try:
        dev = sd.default.device
    except Exception:
        return None
    try:
        idx = dev[0] if isinstance(dev, (list, tuple)) else dev
    except (TypeError, IndexError):
        return None
    return idx if isinstance(idx, int) and idx >= 0 else None


def _default_input_name() -> str | None:
    """Name of the Windows default input device, or None."""
    idx = _default_input_index()
    if idx is None:
        return None
    try:
        devs = _devices()
        if 0 <= idx < len(devs):
            return devs[idx]["name"] or None
    except Exception:
        pass
    return None


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
        if _is_blacklisted_input(dev["name"]):
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
    """Try to open and start a stream. Raises on failure.

    Requests low latency from PortAudio so the OS sets up a small input
    buffer (typically 5-15 ms on Windows WDM-KS, vs the 30-80 ms default).
    Combined with the cached winning device spec, this is what makes
    start() respond fast enough that the user doesn't notice the open.
    """
    s = sd.InputStream(samplerate=rate, channels=channels,
                       dtype="float32", device=device, callback=callback,
                       latency="low")
    s.start()
    return s


class MicRecorder:
    """Start/stop microphone recording with pre-allocated ring buffer."""

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

        # Cache of the device spec that successfully opened last time.
        # _build_candidates() probes 4-8 (device, rate, channel) combos until
        # one works — typically 100-200 ms on first call. Caching the winner
        # lets the second-onwards start() skip the probe loop entirely so the
        # open is dominated by PortAudio's own latency (5-15 ms with
        # latency='low'), without keeping the stream open between recordings
        # (which would put Windows into communications mode and degrade
        # audio quality / duck other apps).
        self._cached_spec: tuple[int, int, int, str] | None = None  # (dev, rate, ch, label)
        # Windows default-input index we last resolved against (auto mode only).
        # When the OS default changes between recordings we drop the cached spec
        # and re-probe so dictation follows the new mic, the way Teams does.
        self._auto_default_index: int | None = None

    def start(self):
        """Start recording. Tries multiple device/channel combos until one works.

        On the *second* and subsequent calls the device spec that worked
        last time is tried first (and exclusively if it still works), so
        the open path is dominated by PortAudio's own low-latency startup
        (5-15 ms) instead of our 4-8 attempt probe loop (100-200 ms).
        """
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

        # Auto mode: follow the OS default input device. If Windows' default
        # changed since the last recording, drop the cached spec so we re-probe
        # and pick up the new mic (laptop ↔ Yealink ↔ AirPods) like Teams.
        auto_mode = self._device_name is None and self._device_index is None
        if auto_mode:
            cur_default = _default_input_index()
            if (self._auto_default_index is not None
                    and cur_default != self._auto_default_index
                    and self._cached_spec is not None):
                log.info("Standard-mik bytt (idx %s → %s) — väljer om enhet",
                         self._auto_default_index, cur_default)
                self._cached_spec = None

        # Fast path: try the cached winning spec first. If the device was
        # unplugged or the driver state changed we fall through to the full
        # probe loop below.
        if self._cached_spec is not None:
            dev_idx, rate, ch, label = self._cached_spec
            try:
                self._ensure_buffer(rate, ch)
                self._stream = _try_start(dev_idx, rate, ch, self._cb)
                self._rate = rate
                log.debug("Inspelning startad (cached spec): %s (dev=%d, %dHz, %dch)",
                          label, dev_idx, rate, ch)
                return
            except Exception as e:
                log.info("Cachad device-spec funkade inte längre (%s), "
                         "kör ny probe", e)
                self._cached_spec = None

        # Fresh probe: refresh PortAudio's snapshot so we see the current OS
        # default + any plugged/unplugged mics. Only on the slow path, so
        # cached repeats stay fast and this stays off the transcribe→paste hot
        # path (it runs at record *start*, while the user is still pressing).
        if auto_mode:
            _reinit_portaudio()
            invalidate_device_cache()

        candidates = self._build_candidates()
        last_err = None

        for dev_idx, rate, ch, label in candidates:
            try:
                # Pre-allocate buffer for this (rate, channels). Reuse across
                # subsequent starts when shape matches — saves an allocation.
                self._ensure_buffer(rate, ch)
                self._stream = _try_start(dev_idx, rate, ch, self._cb)
                self._rate = rate
                # Cache the winning spec so the next start() skips the probe.
                self._cached_spec = (dev_idx, rate, ch, label)
                if auto_mode:
                    # Record the (possibly re-indexed) default we resolved
                    # against so the next start compares against a stable value.
                    self._auto_default_index = _default_input_index()
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

        # Then try all input devices sorted by API preference, but follow the
        # Windows default input device first (like Teams) and skip loopback /
        # phantom endpoints so auto never lands on something silent.
        default_name = None
        if self._device_name is None and self._device_index is None:
            default_name = _default_input_name()

        prio = _api_priority()
        all_devs = []
        for i, dev in enumerate(devs):
            if dev["max_input_channels"] < 1:
                continue
            if _is_blacklisted_input(dev["name"]):
                continue
            rank = prio.get(dev["hostapi"], 99)
            # 0 = this is the OS default input device → try its endpoints first.
            is_default = 0 if (default_name and dev["name"] == default_name) else 1
            all_devs.append((is_default, rank, i, dev))
        all_devs.sort(key=lambda x: (x[0], x[1], x[2]))

        for _is_default, _rank, i, dev in all_devs:
            rate = int(dev["default_samplerate"])
            for ch in sorted(set([1, dev["max_input_channels"]])):
                label = f"{dev['name']} (auto)"
                entry = (i, rate, ch, label)
                if entry not in candidates:
                    candidates.append(entry)

        # L5.4: try 16 kHz mono first for each device so finalize_audio can skip
        # the resample/downmix entirely. Drivers that reject it fall through to
        # the native-rate candidates that follow.
        preferred: list[tuple[int, int, int, str]] = []
        seen_idx: set[int] = set()
        for (i, _rate, _ch, label) in candidates:
            if i not in seen_idx:
                seen_idx.add(i)
                preferred.append((i, TARGET_RATE, 1, f"{label} @16k"))

        result: list[tuple[int, int, int, str]] = []
        for entry in preferred + candidates:
            if entry not in result:
                result.append(entry)
        return result

    def _cb(self, indata, frames, time, status):
        if status:
            now = time_module.monotonic()
            if now - self._last_status_log > 5.0:
                log.warning("Audio callback-status: %s", status)
                self._last_status_log = now

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

        Returns ``(audio_view, channels, rate)``. ``audio_view`` is a copy
        of the relevant slice of the pre-allocated ring buffer so the
        worker can process it while a new recording starts.

        Keeps the keyboard-hook thread responsive (Windows can disable a
        low-level hook that blocks > ~300 ms).

        The stream is always closed — we deliberately don't keep it open
        between recordings. Holding an input stream open puts Windows into
        "communications" mode (AGC, echo cancellation, other-app ducking
        via the Sounds > Communications policy), which degrades both our
        own audio quality and the rest of the user's system audio.
        """
        self.recording = False
        if self._stream is not None:
            try:
                self._stream.abort()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        rate = getattr(self, "_rate", TARGET_RATE)
        if self._buffer is None or self._buffer_offset == 0:
            return np.empty(0, dtype=np.float32), self._buffer_channels, rate
        view = self._buffer[:self._buffer_offset]
        # Copy so the worker can safely process while a new recording starts.
        # The copy is contiguous and ~23 MB worst case (120 s @ 48 kHz mono).
        captured = view.copy()
        return captured, self._buffer_channels, rate

    def snapshot(self) -> tuple[np.ndarray, int, int]:
        """Return a copy of the audio captured *so far* without stopping (L5.7).

        Used by live transcription to decode completed chunks while recording
        continues. Best-effort: reads the current offset and copies that slice;
        a concurrent callback only ever appends past it, so the copy is safe.
        """
        rate = getattr(self, "_rate", TARGET_RATE)
        if self._buffer is None or self._buffer_offset == 0:
            return np.empty(0, dtype=np.float32), self._buffer_channels, rate
        return self._buffer[:self._buffer_offset].copy(), self._buffer_channels, rate

    def stop(self) -> np.ndarray:
        """Backward-compatible: stop + finalize in one call.

        Prefer :py:meth:`stop_fast` + :py:func:`finalize_audio` for the
        latency-sensitive dictation path.
        """
        audio, channels, rate = self.stop_fast()
        return finalize_audio(audio, channels, rate)

    def shutdown(self) -> None:
        """Hard-close the stream. Call at app exit / dictation restart."""
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
    # L5.4: when capture is already 16 kHz the resample is a no-op (skipped).
    t0 = time_module.monotonic()
    resampled = _resample(mono, orig_rate)
    resample_ms = (time_module.monotonic() - t0) * 1000
    skipped = " (överhoppad)" if orig_rate == TARGET_RATE else ""
    log.info("Resamplerad: %d -> %d samples (%d->%dHz), resample_ms=%.1f%s",
             len(mono), len(resampled), orig_rate, TARGET_RATE,
             resample_ms, skipped)
    return resampled
