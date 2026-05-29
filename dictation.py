"""Push-to-talk dictation: hotkey -> record -> transcribe -> paste."""
import logging
import queue
import threading
import time
import keyboard
import numpy as np

from audio import MicRecorder, finalize_audio
from transcriber import Transcriber
from paste import paste_text
from modifiers import normalize_all, is_modifier
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
                 min_rms: float = DEFAULT_MIN_RMS,
                 raw_mode: bool = False,
                 llm_timeout_sec: float = 15.0,
                 context_awareness: bool = True,
                 learning_enabled: bool = True,
                 app_profiles: dict | None = None):
        self.transcriber = transcriber
        self.hotkey = hotkey
        # MicRecorder accepts str (legacy), dict (structured), or None.
        self.recorder = MicRecorder(device=mic_device)
        self.on_status = on_status or (lambda msg: None)
        self.indicator = indicator
        self.min_rms = min_rms
        # "Rå direkt": when True, paste the raw transcript and skip LLM polish
        # even if the transcriber has LLM enabled. May be overridden per app
        # profile (AP3) once context awareness resolves a "kod"-style profile.
        self.raw_mode = raw_mode
        # Watchdog threshold for the wait-mode polish fallback (configurable).
        self.llm_timeout_sec = llm_timeout_sec
        self.context_awareness = context_awareness
        self.learning_enabled = learning_enabled
        self.app_profiles = app_profiles or {}
        self._active = False
        self._recording = False
        self._t_press = 0.0
        # AP2 learning loop: remember the last pasted text and read the focused
        # field's value before the next dictation to learn manual corrections.
        # The reader is context_win.get_focused_text (best-effort) and only
        # wired when both context awareness and learning are on.
        self._last_pasted = ""
        self._field_reader = (
            self._read_focused_text
            if (context_awareness and learning_enabled) else None
        )
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
        # Close the audio stream — for the prewarm path it was being kept
        # open between hotkey presses.
        try:
            self.recorder.shutdown()
        except Exception:
            log.debug("recorder.shutdown() under stop misslyckades", exc_info=True)

    # ----------------------------------------------------------------- private

    @staticmethod
    def _read_focused_text() -> str:
        """Best-effort read of the focused field (AP3 → AP2 learning)."""
        try:
            import context_win
            return context_win.get_focused_text()
        except Exception:
            return ""

    def _resolve_context(self):
        """AP3: resolve active-app profile + on-screen names. Best-effort."""
        try:
            import context_win
            return context_win.get_context(getattr(self, "app_profiles", None))
        except Exception as e:
            log.debug("Kontextmedvetenhet misslyckades: %s", e)
            return None

    def _observe_corrections(self) -> None:
        """AP2: compare the previously pasted text against the focused field now.

        Best-effort and silent on any failure — never blocks dictation. Reads
        the field via the pluggable ``_field_reader`` (wired to context_win in
        AP3); a no-op when learning is off or nothing was pasted yet.
        """
        if not getattr(self, "learning_enabled", True):
            return
        reader = getattr(self, "_field_reader", None)
        last = getattr(self, "_last_pasted", "")
        if reader is None or not last:
            return
        self._last_pasted = ""
        try:
            observed = reader() or ""
        except Exception as e:
            log.debug("Kunde inte läsa målfält för inlärning: %s", e)
            return
        if not observed:
            return
        try:
            from learning import learn_from_observation
            learn_from_observation(last, observed)
        except Exception as e:
            log.debug("Inlärning misslyckades: %s", e)

    @staticmethod
    def _log_latency(record_ms: float, transcribe_ms: float,
                     llm_ms: float, paste_ms: float) -> None:
        """Log the per-step latency breakdown for the hot path (AP1)."""
        pipeline = transcribe_ms + llm_ms + paste_ms
        log.info(
            "Latens: record=%.0fms transcribe=%.0fms llm=%.0fms paste=%.0fms "
            "(pipeline efter release=%.0fms)",
            record_ms, transcribe_ms, llm_ms, paste_ms, pipeline,
        )

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
                self._t_press = time.monotonic()
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

        # Recording duration (press → release) — first leg of the latency
        # breakdown logged in _transcribe.
        record_ms = (time.monotonic() - self._t_press) * 1000 if self._t_press else 0.0

        # Reuse the running RMS maintained by the recorder — O(1).
        rms = self.recorder.rms()

        # Enqueue for the worker. Bounded queue: if full (previous job(s)
        # still being transcribed/polished), drop and tell the user.
        try:
            self._jobs.put_nowait((audio, channels, rate, rms, record_ms))
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
                     rate: int, rms: float, record_ms: float = 0.0):
        n_raw = audio_raw.shape[0] if audio_raw.ndim >= 1 else 0
        log.info("Audio: %d raw samples, RMS=%.5f", n_raw, rms)

        # AP2: learn from any manual edits the user made to the last paste
        # before starting this new dictation (best-effort, never blocks).
        self._observe_corrections()

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

        self._transcribe(audio, record_ms)

    def _transcribe(self, audio: np.ndarray, record_ms: float = 0.0):
        try:
            if self._worker_stop.is_set() or not self._active:
                log.info("Hoppar över stale transkribering efter stopp")
                return
            log.info("Transkriberar %d samples...", len(audio))
            # "Rå direkt" disables polish even when the transcriber has LLM on.
            llm_enabled = (
                getattr(self.transcriber, "llm_enabled", False)
                and not getattr(self, "raw_mode", False)
            )

            # AP3 context awareness: resolve app profile + on-screen names.
            # A "code"-style profile disables polish and capitalisation; names
            # bias the local decoder and (only when polishing) the LLM prompt.
            profile_desc = ""
            onscreen_names = ""
            capitalize = True
            if getattr(self, "context_awareness", False):
                ctx = self._resolve_context()
                if ctx is not None:
                    profile_desc = ctx.profile_description
                    onscreen_names = ctx.onscreen_names
                    capitalize = ctx.capitalize
                    if not ctx.polish:
                        llm_enabled = False

            t_tx0 = time.monotonic()
            # The status message shown while transcription runs reflects
            # whether the user opted into a remote provider. Saying "lokalt"
            # when the audio is being shipped to e.g. KBLab's API is both
            # wrong and erodes trust about where the data is going. Show
            # the remote status even when LLM is off — the user needs
            # transparency that audio is leaving the machine, regardless
            # of whether LLM polish is enabled.
            tr_provider = getattr(self.transcriber, "transcription_provider", "local")
            tr_label = "lokalt" if tr_provider == "local" else f"via {tr_provider}"
            if llm_enabled or tr_provider != "local":
                self.on_status(f"Transkriberar {tr_label}…")
                if self.indicator:
                    self.indicator.show(f"Transkriberar {tr_label}…", state="transcribe")
            text = self.transcriber.transcribe(
                audio, capitalize=capitalize, extra_hotwords=onscreen_names)
            transcribe_ms = (time.monotonic() - t_tx0) * 1000
            log.info("Resultat klart (%s)", _text_meta(text))
            if text.strip():
                if self._worker_stop.is_set() or not self._active:
                    log.info("Hoppar över paste från stale transkribering")
                    return

                if llm_enabled:
                    # Wait-mode: don't paste the raw transcript. Run LLM polish
                    # first and paste the polished result in one step. This
                    # avoids the paste-twice problem where the user has
                    # already sent the raw text (Enter, Tab, …) before the
                    # LLM update lands on the clipboard.
                    #
                    # Trade-off: the user waits 1-3s longer before *any* text
                    # appears, but they get exactly one paste of the final
                    # text. Watchdog falls back to pasting the raw transcript
                    # if polish hangs past 15s.
                    self.on_status("LLM-granskar…")
                    if self.indicator:
                        self.indicator.show("LLM-granskar…", state="transcribe")

                    polish_lock = threading.Lock()
                    polish_completed = {"done": False}
                    t_llm0 = time.monotonic()

                    def _paste_and_finalize(final_text: str, polished_label: bool) -> None:
                        """Paste once and update indicator. Must be called under lock."""
                        if self._worker_stop.is_set() or not self._active:
                            log.info("Hoppar över paste efter stopp")
                            return
                        llm_ms = (time.monotonic() - t_llm0) * 1000
                        t_p0 = time.monotonic()
                        paste_text(final_text, active_modifiers=self._modifier_keys)
                        self._last_pasted = final_text
                        self._log_latency(record_ms, transcribe_ms, llm_ms,
                                          (time.monotonic() - t_p0) * 1000)
                        if polished_label:
                            state = getattr(self.transcriber, "last_polish_state", "local")
                            if state == "llm_changed":
                                msg = "Klistrad (LLM-polerad)"
                            elif state == "llm_unchanged":
                                msg = "Klistrad (LLM-granskad)"
                            else:
                                msg = "Klistrad (rå)"
                        else:
                            msg = "Klistrad (rå — LLM-timeout)"
                        self.on_status(f"{msg} — håll {self.hotkey.upper()} igen")
                        if self.indicator:
                            self.indicator.show(msg, state="done")
                            self.indicator.hide(delay_ms=1800)

                    def _watchdog_fallback() -> None:
                        with polish_lock:
                            if polish_completed["done"]:
                                return
                            polish_completed["done"] = True
                        log.warning(
                            "LLM-polish svarade inte inom 15 s — "
                            "klistrar rå transkribering som fallback"
                        )
                        _paste_and_finalize(text, polished_label=False)

                    watchdog = threading.Timer(
                        getattr(self, "llm_timeout_sec", 15.0),
                        _watchdog_fallback)
                    watchdog.daemon = True
                    watchdog.name = "llm-polish-watchdog"

                    def _on_polish_done(original: str, polished: str):
                        with polish_lock:
                            if polish_completed["done"]:
                                return
                            polish_completed["done"] = True
                        watchdog.cancel()
                        # If polish returned (text, text) on failure, we still
                        # have something usable; paste it as the raw transcript.
                        # Otherwise paste the polished version directly.
                        _paste_and_finalize(polished, polished_label=True)

                    # on_stage callback is now a no-op: we've already set the
                    # status above before kicking polish off. Passing None
                    # keeps the transcriber's per-job slot clean.
                    watchdog.start()
                    try:
                        self.transcriber.polish_async(
                            text, _on_polish_done, on_stage=None,
                            app_profile=profile_desc,
                            onscreen_names=onscreen_names)
                    except Exception as e:
                        log.error("polish_async kraschade synkront: %s",
                                  e, exc_info=True)
                        watchdog.cancel()
                        _watchdog_fallback()
                else:
                    # No LLM — paste immediately, this is the fast path.
                    t_p0 = time.monotonic()
                    paste_text(text, active_modifiers=self._modifier_keys)
                    self._last_pasted = text
                    self._log_latency(record_ms, transcribe_ms, 0.0,
                                      (time.monotonic() - t_p0) * 1000)
                    message = "Klistrad"
                    self.on_status(f"{message} — håll {self.hotkey.upper()} igen")
                    if self.indicator:
                        self.indicator.show(message, state="done")
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
