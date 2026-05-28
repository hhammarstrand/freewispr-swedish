"""Push-to-talk dictation: hotkey -> record -> transcribe -> paste."""
import logging
import queue
import threading
import keyboard
import numpy as np

from audio import MicRecorder, finalize_audio
from transcriber import Transcriber
from paste import paste_text
from modifiers import normalize_all, is_modifier
import snippets as snippet_module
import sounds

log = logging.getLogger("freewispr")


def _text_meta(text: str) -> str:
    words = len(text.split())
    return f"chars={len(text)}, words={words}"


MIN_AUDIO_SAMPLES = 3200   # 0.2 s at 16 kHz — ignore accidental taps
# Default RMS gate. Audio quieter than this is treated as silence and dropped
# without invoking Whisper (saves ~1 s of CPU per phantom press).
#
# Derivation: with int16 → float32 normalisation the noise floor of a typical
# USB headset in a quiet room measures RMS ≈ 0.0005-0.001. A whispered word
# sits around 0.005-0.01, normal speech 0.02-0.1. 0.003 leaves comfortable
# headroom above silence while still letting through quiet speech.
# Overridable via DictationMode(min_rms=...) — surfaced in Settings as
# "Lägsta inspelningsnivå".
DEFAULT_MIN_RMS = 0.003

# Bounded queue prevents memory blow-up if the user spams the hotkey while
# transcriptions stall (e.g. LLM-polish round-trip). Beyond this depth we
# drop new presses and show "Upptagen" instead.
_QUEUE_MAX = 2


def _friendly_mic_error(exc: Exception) -> str:
    """Convert raw exception to a user-friendly Swedish message."""
    msg = str(exc).lower()
    if "device unavailable" in msg or "no device" in msg or "ingen mikrofon" in msg:
        return "Ingen mikrofon hittades — kolla att din mikrofon är ansluten"
    if "permission" in msg or "access" in msg or "behörighet" in msg:
        return "Mikrofonen är blockerad — godkänn åtkomst i Inställningar → Sekretess"
    if "in use" in msg or "busy" in msg or "upptagen" in msg:
        return "Mikrofonen används av en annan app"
    if "format" in msg or "rate" in msg or "samplerate" in msg:
        return "Mikrofonen stöder inte detta format — välj en annan i Inställningar"
    return "Mikrofonfel — se loggen för detaljer"


def _friendly_transcribe_error(exc: Exception) -> str:
    """Convert raw transcription exception to a user-friendly Swedish message."""
    raw = str(exc)
    msg = raw.lower()
    # If the transcriber already raised a Swedish, user-facing message
    # (e.g. CUDA OOM recovery or corrupt-model detection), pass it through
    # verbatim instead of overwriting it with a generic one.
    if (
        "gpu-minne slut" in msg
        or "modellen verkar korrupt" in msg
    ):
        return raw
    if "out of memory" in msg or "cuda" in msg and "memory" in msg:
        return "GPU-minne slut — byt till en mindre modell i Inställningar"
    if "no module named" in msg:
        return "Modul saknas — kör 'pip install -r requirements.txt'"
    if "filenotfound" in msg or "no such file" in msg:
        return "Modellfil saknas — ladda ner via Inställningar"
    if "network" in msg or "timeout" in msg or "connection" in msg or "nätverk" in msg:
        return "Nätverksfel — kontrollera anslutningen"
    if "401" in msg or "unauthorized" in msg or "ogiltig api-nyckel" in msg:
        return "Ogiltig API-nyckel — kolla Inställningar → LLM"
    if "429" in msg or "rate limit" in msg:
        return "För många anrop — vänta en stund"
    return "Transkriberingsfel — se loggen för detaljer"


def _parse_hotkey(hotkey: str) -> tuple[str, tuple[str, ...]]:
    """Split a hotkey string into (trigger, canonical_modifiers).

    Falls back to naive ``+`` splitting. Modifier names are normalised via
    :py:mod:`modifiers` so ``cmd``, ``win``, ``windows`` all map to the
    same canonical ``windows`` token used by the paste layer.
    """
    parts = [p.strip().lower() for p in hotkey.split("+") if p.strip()]
    if not parts:
        return hotkey.strip().lower(), ()
    trigger = parts[-1]
    raw_modifiers = parts[:-1]
    modifiers = normalize_all(raw_modifiers)
    # Preserve unknown non-modifier prefixes so the held-check still gates
    # on them (rare; e.g. user types ``foo+bar`` deliberately).
    if not modifiers and len(raw_modifiers) > 0 and not any(is_modifier(m) for m in raw_modifiers):
        modifiers = tuple(raw_modifiers)
    return trigger, modifiers


class DictationMode:
    def __init__(self, transcriber: Transcriber, hotkey: str = "ctrl+space",
                 on_status=None, indicator=None,
                 mic_device: str | dict | None = None,
                 min_rms: float = DEFAULT_MIN_RMS):
        self.transcriber = transcriber
        self.hotkey = hotkey
        # MicRecorder accepts str (legacy), dict (structured), or None.
        self.recorder = MicRecorder(device=mic_device)
        self.on_status = on_status or (lambda msg: None)
        self.indicator = indicator
        self.min_rms = min_rms
        self._active = False
        self._recording = False
        self._hook_handles: list = []

        # Bounded queue + dedicated worker thread. Replaces the old single-slot
        # lock that *dropped* recordings — instead we queue up to _QUEUE_MAX
        # and only drop if the queue is full.
        self._jobs: queue.Queue = queue.Queue(maxsize=_QUEUE_MAX)
        self._worker_stop = threading.Event()
        self._worker_thread: threading.Thread | None = None

        self._trigger_key, self._modifiers = _parse_hotkey(hotkey)
        # Cached tuple passed to paste_text — lets the paste layer release
        # only the modifiers from this hotkey (not all of them — releasing
        # an unheld Win key opens the Start menu on Windows).
        self._modifier_keys: tuple[str, ...] = self._modifiers

    # ------------------------------------------------------------------ public

    def start(self):
        self._active = True
        log.info("Hotkey: trigger='%s', modifiers=%s",
                 self._trigger_key, list(self._modifiers))
        # Start the transcription worker before installing hooks so the very
        # first press has a consumer ready.
        self._worker_stop.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop, name="dictation-worker", daemon=True)
        self._worker_thread.start()
        # Track our own handles so stop() can detach cleanly without nuking
        # keyboard hooks installed by other parts of the app (or tests).
        self._hook_handles = [
            keyboard.on_press_key(self._trigger_key, self._on_press, suppress=False),
            keyboard.on_release_key(self._trigger_key, self._on_release, suppress=False),
        ]
        self.on_status(f"Klar — håll {self.hotkey.upper()} för att prata")

    def stop(self, wait: bool = True):
        self._active = False
        for handle in self._hook_handles:
            try:
                keyboard.unhook(handle)
            except Exception:
                pass
        self._hook_handles = []
        # Signal worker to exit after it drains current job. Sentinel = None.
        self._worker_stop.set()
        # Drop stale queued recordings and guarantee the sentinel is delivered
        # even when the bounded queue is full.
        while True:
            try:
                self._jobs.get_nowait()
            except queue.Empty:
                break
        try:
            self._jobs.put_nowait(None)
        except queue.Full:
            # Should not happen after draining, but do not block shutdown.
            log.debug("Kunde inte lägga stoppsentinel i transkriberingskö")
        worker = self._worker_thread
        if wait and worker and worker.is_alive():
            worker.join(timeout=5.0)
            self._worker_thread = None

    # ----------------------------------------------------------------- private

    def _modifier_held(self) -> bool:
        """All required modifiers must be physically held right now."""
        if not self._modifiers:
            return True
        try:
            return all(keyboard.is_pressed(m) for m in self._modifiers)
        except Exception:
            return False

    def _on_press(self, _):
        if self._active and not self._recording and self._modifier_held():
            try:
                self._recording = True
                # Wire the audio thread to push RMS levels directly to the
                # UI indicator — replaces the 50 ms polling timer with an
                # event-driven path. Cleared in _on_release.
                if self.indicator is not None:
                    self.recorder.on_level = self.indicator.push_level
                else:
                    self.recorder.on_level = None
                self.recorder.start()
                sounds.play_start()
                self.on_status("Lyssnar…")
                if self.indicator:
                    self.indicator.show("Lyssnar…", state="listen",
                                        level_source=lambda: self.recorder.level)
            except Exception as e:
                self._recording = False
                log.error("Mic start error: %s", e, exc_info=True)
                sounds.play_error()
                if self.indicator:
                    msg = _friendly_mic_error(e)
                    self.indicator.show(msg, state="error")
                    self.indicator.hide(delay_ms=4000)

    def _on_release(self, _):
        if not (self._active and self._recording):
            return
        self._recording = False
        # Detach the UI push callback before stop_fast so a late audio
        # callback can't redraw bars after we've switched to transcribe.
        self.recorder.on_level = None
        # Stop the stream cheaply and hand back the captured audio. Downmix
        # and resample happen in the worker — keeping this hook callback
        # under ~10 ms so Windows doesn't disable the low-level hook.
        try:
            audio, channels, rate = self.recorder.stop_fast()
        except Exception as e:
            log.error("Audio stop error: %s", e, exc_info=True)
            sounds.play_error()
            if self.indicator:
                self.indicator.show("Mikrofonfel", state="error")
                self.indicator.hide(delay_ms=2500)
            self.on_status(f"Klar — håll {self.hotkey.upper()}")
            return

        sounds.play_stop()

        # Reuse the running RMS maintained by the recorder — O(1).
        rms = self.recorder.rms()

        # Enqueue for the worker. Bounded queue: if full (previous job(s)
        # still being transcribed/polished), drop and tell the user.
        try:
            self._jobs.put_nowait((audio, channels, rate, rms))
        except queue.Full:
            log.warning("Transkriberingskö full — hoppar över denna")
            self.on_status("Upptagen — vänta…")
            if self.indicator:
                self.indicator.show("Upptagen", state="error")
                self.indicator.hide(delay_ms=1500)
            return

        self.on_status("Transkriberar…")
        if self.indicator:
            self.indicator.show("Transkriberar…", state="transcribe")

    def _worker_loop(self):
        """Drain the job queue: finalize audio → transcribe → paste."""
        while not self._worker_stop.is_set():
            try:
                job = self._jobs.get(timeout=0.5)
            except queue.Empty:
                continue
            if job is None:  # sentinel
                break
            try:
                self._process_job(*job)
            except Exception as e:
                log.error("Worker exception: %s", e, exc_info=True)

    def _process_job(self, audio_raw: np.ndarray, channels: int,
                     rate: int, rms: float):
        n_raw = audio_raw.shape[0] if audio_raw.ndim >= 1 else 0
        log.info("Audio: %d raw samples, RMS=%.5f", n_raw, rms)

        if rms < self.min_rms:
            log.info("Inspelning för tyst (RMS=%.5f < %.5f), ignorerar",
                     rms, self.min_rms)
            self.on_status(f"Inget hördes — håll {self.hotkey.upper()}")
            if self.indicator:
                self.indicator.show("Inget hördes", state="error")
                self.indicator.hide(delay_ms=1500)
            return

        audio = finalize_audio(audio_raw, channels, rate)
        n = len(audio)

        if n < MIN_AUDIO_SAMPLES:
            log.info("Inspelning för kort (%d samples), ignorerar", n)
            self.on_status(f"Klar — håll {self.hotkey.upper()}")
            if self.indicator:
                self.indicator.hide(delay_ms=0)
            return

        self._transcribe(audio)

    def _transcribe(self, audio: np.ndarray):
        try:
            if self._worker_stop.is_set() or not self._active:
                log.info("Hoppar över stale transkribering efter stopp")
                return
            log.info("Transkriberar %d samples...", len(audio))
            llm_enabled = getattr(self.transcriber, "llm_enabled", False)
            if llm_enabled:
                self.on_status("Transkriberar lokalt…")
                if self.indicator:
                    self.indicator.show("Transkriberar lokalt…", state="transcribe")
            text = self.transcriber.transcribe(audio)
            # Apply snippet expansion — if full text is a trigger, replace it
            text = snippet_module.expand(text)
            log.info("Resultat klart (%s)", _text_meta(text))
            if text.strip():
                if self._worker_stop.is_set() or not self._active:
                    log.info("Hoppar över paste från stale transkribering")
                    return
                # Paste the local result immediately — user gets text without
                # waiting for the LLM round-trip.
                paste_text(text, active_modifiers=self._modifier_keys)
                message = "Klistrad (lokal)"
                self.on_status(f"{message} — håll {self.hotkey.upper()} igen")
                if self.indicator:
                    self.indicator.show(message, state="done")

                if llm_enabled:
                    # Per-job stage callback. Passed as a parameter to
                    # polish_async so two overlapping jobs don't trample
                    # each other's callbacks via a shared attribute.
                    def _on_stage(stage: str):
                        if stage == "llm_reviewing":
                            self.on_status("LLM-granskar…")
                            if self.indicator:
                                self.indicator.show("LLM-granskar…", state="transcribe")

                    # Watchdog: if the LLM polish callback fails to fire
                    # within 15 s (network hang, thread died, …) we force
                    # the indicator back to a final state so the user
                    # isn't left staring at "LLM-granskar…" forever. The
                    # _polish_completed flag is the single source of truth
                    # for "callback already ran"; both paths use it under
                    # the lock so we never run the cleanup twice.
                    polish_lock = threading.Lock()
                    polish_completed = {"done": False}

                    def _finalize_local_fallback() -> None:
                        """Run from the watchdog timer when polish hangs."""
                        with polish_lock:
                            if polish_completed["done"]:
                                return
                            polish_completed["done"] = True
                        log.warning(
                            "LLM-polish svarade inte inom 15 s — "
                            "tvingar indikatorn till 'Klistrad (lokal)'"
                        )
                        if self._worker_stop.is_set() or not self._active:
                            return
                        self.on_status(
                            f"Klistrad (lokal) — håll {self.hotkey.upper()} igen"
                        )
                        if self.indicator:
                            self.indicator.show("Klistrad (lokal)", state="done")
                            self.indicator.hide(delay_ms=1800)

                    watchdog = threading.Timer(15.0, _finalize_local_fallback)
                    watchdog.daemon = True
                    watchdog.name = "llm-polish-watchdog"

                    def _on_polish_done(original: str, polished: str):
                        # First-come-first-served vs. the watchdog. If the
                        # watchdog already fired we silently no-op so we
                        # don't yank the indicator back to a stale state.
                        with polish_lock:
                            if polish_completed["done"]:
                                return
                            polish_completed["done"] = True
                        watchdog.cancel()
                        if self._worker_stop.is_set() or not self._active:
                            log.info("Hoppar över LLM-uppdatering efter stopp")
                            return
                        if polished != original:
                            # Update the clipboard with the polished text so
                            # the user can Ctrl+V again to get the improved
                            # version. The already-pasted local text stays in
                            # the document.
                            import pyperclip
                            pyperclip.copy(polished + " ")
                            msg = "Klistrad (LLM-polerad)"
                        else:
                            state = getattr(self.transcriber, "last_polish_state", "local")
                            if state == "llm_unchanged":
                                msg = "Klistrad (LLM-granskad)"
                            else:
                                # polish failed or returned local
                                msg = "Klistrad (lokal)"
                        self.on_status(f"{msg} — håll {self.hotkey.upper()} igen")
                        if self.indicator:
                            self.indicator.show(msg, state="done")
                            self.indicator.hide(delay_ms=1800)

                    # Start the watchdog *before* kicking off polish — if
                    # polish_async raises synchronously we want the timer
                    # to still cover us, and the cancel() above remains
                    # cheap even if the timer hasn't started ticking yet.
                    watchdog.start()
                    try:
                        self.transcriber.polish_async(text, _on_polish_done,
                                                      on_stage=_on_stage)
                    except Exception as e:
                        log.error("polish_async kraschade synkront: %s",
                                  e, exc_info=True)
                        watchdog.cancel()
                        _finalize_local_fallback()
                else:
                    # No LLM — hide the indicator after a short delay.
                    if self.indicator:
                        self.indicator.hide(delay_ms=1800)
            else:
                self.on_status(f"Inget hördes — håll {self.hotkey.upper()}")
                if self.indicator:
                    self.indicator.show("Inget hördes", state="error")
                    self.indicator.hide(delay_ms=1500)
        except Exception as e:
            log.error("Transkribering misslyckades: %s", e, exc_info=True)
            self.on_status(f"Fel — håll {self.hotkey.upper()}")
            if self.indicator:
                self.indicator.show(_friendly_transcribe_error(e), state="error")
                self.indicator.hide(delay_ms=5000)
