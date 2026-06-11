"""Push-to-talk dictation: hotkey -> record -> transcribe -> paste."""
import collections
import logging
import queue
import re
import threading
import time
import keyboard
import numpy as np

from audio import MicRecorder, finalize_audio
from paste import paste_text, replace_len_for
from modifiers import normalize_all, is_modifier
from transcriber import Transcriber
import sounds

log = logging.getLogger("freewispr")


# Rolling latency window for p50/p95 summaries (L0 measurability).
_LAT_WINDOW = 50
_latency_samples: collections.deque = collections.deque(maxlen=_LAT_WINDOW)
_LAT_KEYS = ("transcribe_ms", "llm_ms", "paste_ms", "context_hotpath_ms", "conn_ms")


# L5.6: disfluency / self-correction markers. Their presence forces polish so a
# self-correction ("…fem, nej förresten sex") is never left unresolved.
_DISFLUENCY_RE = re.compile(
    r"\b(öh+|eh+|öhm|ehm|hmm+|hrm|förresten|jag menar|nej nej|alltså nej)\b",
    re.IGNORECASE,
)


def _is_trivial(text: str, max_words: int = 6) -> bool:
    """L5.6: True when the transcript is short and has no disfluency/self-
    correction markers, so polish can be safely skipped. Conservative."""
    t = (text or "").strip()
    if not t:
        return False
    if len(t.split()) > max_words:
        return False
    if _DISFLUENCY_RE.search(t):
        return False
    return True


def _trim_silence(audio: np.ndarray, rate: int, threshold: float,
                  win_ms: int = 30, pad_ms: int = 120) -> np.ndarray:
    """L5.5: trim leading/trailing silence using RMS, with padding.

    Cheap alternative to VAD — fewer samples reach Whisper. Conservative:
    keeps a pad around the voiced region so word edges aren't clipped, and
    returns the input unchanged if nothing crosses the threshold.
    """
    if audio is None or audio.size == 0:
        return audio
    win = max(1, int(rate * win_ms / 1000))
    n = audio.size
    first = last = None
    for start in range(0, n, win):
        seg = audio[start:start + win]
        if seg.size and float(np.sqrt(np.mean(seg * seg))) >= threshold:
            if first is None:
                first = start
            last = start
    if first is None:
        return audio
    pad = int(rate * pad_ms / 1000)
    s = max(0, first - pad)
    e = min(n, last + win + pad)
    if s == 0 and e == n:
        return audio
    return audio[s:e]


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile (no numpy dependency on the hot path)."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def _record_latency_sample(sample: dict) -> None:
    """Append a per-dictation sample and log a rolling p50/p95 summary."""
    _latency_samples.append(sample)
    if len(_latency_samples) < 3:
        return
    parts = []
    for k in _LAT_KEYS:
        vals = [s[k] for s in _latency_samples if k in s]
        if vals:
            parts.append(f"{k} p50={_percentile(vals, 50):.0f} "
                         f"p95={_percentile(vals, 95):.0f}")
    log.info("Latens p50/p95 (n=%d): %s", len(_latency_samples), " | ".join(parts))


def _text_meta(text: str) -> str:
    words = len(text.split())
    return f"chars={len(text)}, words={words}"


# Short, human-friendly names for the status pill. The provider ids stored in
# config (``staik``, ``github``, …) are fine for code but look unpolished in the
# UI. We keep these short — the full labels in llm_polish/remote_transcribe
# (e.g. "staik.se (SE)") are too long for a compact pill.
_PROVIDER_DISPLAY_NAMES = {
    "github": "GitHub Models",
    "staik":  "Staik",
    "berget": "Berget AI",
    "openai": "OpenAI",
    "custom": "egen server",
}


def _provider_status_label(provider: str) -> str:
    """Return the suffix shown after Transkriberar/Polerar for a provider.

    ``local`` becomes "lokalt" (nothing leaves the machine); every remote
    provider becomes "via <Namn>" so the user always sees where the text/audio
    is going.
    """
    if provider == "local":
        return "lokalt"
    name = _PROVIDER_DISPLAY_NAMES.get(provider, provider)
    return f"via {name}"


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

# How long the worker waits for the press-time context resolution to finish
# (L1). It runs during recording, so this wait is normally ~0; the bound just
# protects against a pathological/hung UIA provider.
_CTX_JOIN_TIMEOUT = 0.2

# Max tecken av föregående fälttext som skickas som Whisper-initial_prompt.
# Whisper-prompten budgeterar ~224 tokens och delas med hotwords; ~120 tecken
# ≈ en mening räcker för stil-/versaliseringskontinuitet.
_CTX_TAIL_MAX_CHARS = 120

# L5.7: how often the live-transcription loop snapshots the buffer while
# recording, decoding completed (silence-delimited) chunks ahead of release.
_LIVE_POLL_S = 0.4

# Sentinel: distinguishes "_transcribe called without a context arg" (legacy /
# tests → resolve synchronously) from "context explicitly passed as None".
_NO_CTX = object()


class _ContextHolder:
    """A one-shot slot for the press-time context resolution (L1)."""

    __slots__ = ("event", "ctx")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.ctx = None


class _PressState:
    """Per-press context + live-transcribe state, bound to a single job.

    Holding these here (rather than in shared DictationMode attributes) keeps
    a fast second key-press from overwriting the first job's context / live
    partials while that job is still queued in the worker (_QUEUE_MAX=2). The
    object travels through the job queue so the worker reads exactly the state
    that belongs to the audio it's processing.
    """

    __slots__ = ("ctx_holder", "live_active", "live_thread",
                 "live_parts", "live_consumed")

    def __init__(self) -> None:
        self.ctx_holder = None
        self.live_active = False
        self.live_thread = None
        self.live_parts: list = []
        self.live_consumed = 0


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
    # Remote-provider errors already carry a short, user-facing Swedish
    # message (e.g. "Serverfel (HTTP 502)", "Ogiltig API-nyckel (HTTP 401)",
    # "Nätverksfel: ..."). Pass these through verbatim so the user sees the
    # real cause instead of a misleading "Inget hördes".
    if (
        "serverfel" in msg
        or "servern tillfälligt otillgänglig" in msg
        or "rate limit" in msg
        or "åtkomst nekad" in msg
        or "modellen finns inte" in msg
        or "ljudfilen är för stor" in msg
        or "filformatet stöds inte" in msg
        or raw.startswith("Nätverksfel")
    ):
        return raw
    if "out of memory" in msg or ("cuda" in msg and "memory" in msg):
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


# Right/left-hand modifier variants the capture widget can emit. They map to a
# canonical modifier for the held-check but keep their sided name for hooking.
_SIDED_MODIFIERS = {
    "right ctrl": "ctrl", "right alt": "alt", "right shift": "shift",
    "left ctrl": "ctrl", "left alt": "alt", "left shift": "shift",
}


def _is_modifier_only_hotkey(hotkey: str) -> bool:
    """True if *every* part of the hotkey is a modifier key (no character).

    Such a hotkey (e.g. ``ctrl+alt`` or ``right ctrl``) is the only kind safe
    for voice-edit: it never types a character into the user's selection. The
    ``keyboard`` library treats ``right ctrl``/``right alt`` as modifier
    variants too, so we accept those explicitly.
    """
    parts = [p.strip().lower() for p in hotkey.split("+") if p.strip()]
    if not parts:
        return False
    return all(is_modifier(p) or p in _SIDED_MODIFIERS for p in parts)


def _parse_hotkey(hotkey: str) -> tuple[str, tuple[str, ...]]:
    """Split a hotkey string into (trigger, canonical_modifiers).

    Falls back to naive ``+`` splitting. Modifier names are normalised via
    :py:mod:`modifiers` so ``cmd``, ``win``, ``windows`` all map to the
    same canonical ``windows`` token used by the paste layer.

    A *modifier-only* hotkey (every part is a modifier, e.g. ``ctrl+alt`` or
    ``right ctrl``) returns an **empty trigger** and all parts as modifiers, so
    the caller can hook the modifier key itself instead of a character key.
    """
    parts = [p.strip().lower() for p in hotkey.split("+") if p.strip()]
    if not parts:
        return hotkey.strip().lower(), ()
    if _is_modifier_only_hotkey(hotkey):
        # No character trigger — normalise every part (sided variants collapse
        # to their canonical modifier) so the held-check works.
        mods = normalize_all(
            _SIDED_MODIFIERS.get(p, p) for p in parts)
        return "", mods
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
                 app_profiles: dict | None = None,
                 command_mode_enabled: bool = True,
                 llm_replace_mode: bool = False,
                 context_to_remote_accepted: bool = False,
                 cancel_hotkey: str = "esc",
                 snippets_enabled: bool = True,
                 silence_trim_enabled: bool = True,
                 polish_skip_trivial: bool = True,
                 polish_skip_max_words: int = 6,
                 live_transcribe_enabled: bool = False,
                 voice_edit_hotkey: str = "",
                 voice_answer_hotkey: str = ""):
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
        # "Rå → ersätt" (L3): paste raw first, replace with polished when ready.
        self.llm_replace_mode = llm_replace_mode
        # Watchdog threshold for the wait-mode polish fallback (configurable).
        self.llm_timeout_sec = llm_timeout_sec
        self.context_awareness = context_awareness
        self.learning_enabled = learning_enabled
        self.app_profiles = app_profiles or {}
        self.command_mode_enabled = command_mode_enabled
        # Privacy: on-screen names (AP3) are scraped from the screen and may
        # contain data from other apps. They are a separate consent category
        # from the audio (transcription_privacy_accepted). When False, names are
        # never forwarded to a *remote* STT provider as a biasing prompt; the
        # local decoder always receives them (nothing leaves the machine).
        self.context_to_remote_accepted = context_to_remote_accepted
        # AP7.2 cancel key (only active while recording); AP7.3 pause (session
        # state, not persisted — hotkey becomes a no-op while paused).
        self.cancel_hotkey = cancel_hotkey
        self._cancel_trigger, _ = _parse_hotkey(cancel_hotkey)
        # KP3 voice-edit: separate hotkey to record an instruction for the
        # current selection. Empty = off. Parsed like the main hotkey so it can
        # carry its own modifiers; kept fully separate from the dictation
        # press/release path so the latency-critical hot path is untouched.
        self.voice_edit_hotkey = voice_edit_hotkey
        self._voice_edit_trigger, self._voice_edit_modifiers = (
            _parse_hotkey(voice_edit_hotkey) if voice_edit_hotkey else ("", ()))
        # A modifier-only voice-edit hotkey (e.g. "ctrl+alt" / "right ctrl")
        # has no character trigger, so we hook the *last* part as the key and
        # gate on the rest being held. Such a key never types into — and so
        # never destroys — the user's selection, and needs no suppression.
        self._voice_edit_modifier_only = bool(
            voice_edit_hotkey and _is_modifier_only_hotkey(voice_edit_hotkey))
        if self._voice_edit_modifier_only:
            _ve_parts = [p.strip().lower()
                         for p in voice_edit_hotkey.split("+") if p.strip()]
            # `keyboard.on_press_key` is unreliable for *modifier* scan codes
            # (e.g. right ctrl = 57373) — it binds without error but never
            # fires on a physical press. So a modifier-only hotkey is driven by
            # a single global hook that edge-detects "all required modifiers
            # held" instead. Keep the raw sided names ("right ctrl") for the
            # is_pressed() held-check.
            self._voice_edit_required_keys = tuple(_ve_parts)
            self._voice_edit_hook_key = _ve_parts[-1]
            self._voice_edit_gate_modifiers = normalize_all(
                _SIDED_MODIFIERS.get(p, p) for p in _ve_parts)
            self._voice_edit_hook_candidates = ()
        else:
            self._voice_edit_required_keys = ()
            self._voice_edit_hook_key = self._voice_edit_trigger
            self._voice_edit_hook_candidates = (
                (self._voice_edit_trigger,) if self._voice_edit_trigger else ())
            self._voice_edit_gate_modifiers = self._voice_edit_modifiers
        self._voice_edit_engaged = False
        self._voice_editing = False
        # KP4 voice-answer: a second modifier-only hotkey. Reads the selection
        # as *context*, asks the LLM to write a reply, and puts the reply on the
        # clipboard (never pasted — so it can't wipe a selection). Modifier-only
        # to match voice-edit's reliable global-hook path.
        self.voice_answer_hotkey = voice_answer_hotkey
        self._voice_answer_modifier_only = bool(
            voice_answer_hotkey and _is_modifier_only_hotkey(voice_answer_hotkey))
        if self._voice_answer_modifier_only:
            _va_parts = [p.strip().lower()
                         for p in voice_answer_hotkey.split("+") if p.strip()]
            self._voice_answer_required_keys = tuple(_va_parts)
        else:
            self._voice_answer_required_keys = ()
        self._voice_answer_engaged = False
        self._voice_answering = False
        self.snippets_enabled = snippets_enabled
        self.silence_trim_enabled = silence_trim_enabled
        self.polish_skip_trivial = polish_skip_trivial
        self.polish_skip_max_words = polish_skip_max_words
        self.live_transcribe_enabled = live_transcribe_enabled
        self._live_active = False
        self._live_parts: list = []
        self._live_consumed = 0
        self._live_thread: threading.Thread | None = None
        self._press_state: _PressState | None = None
        self._paused = False
        self._active = False
        self._recording = False
        self._t_press = 0.0
        # AP5 command mode: the last pasted/transformed block, edited in place
        # by voice commands. Kept separate from _last_pasted (which AP2 clears).
        self._last_block = ""
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
        # AP7.2: cancel key — only acts while recording, otherwise a no-op so
        # normal Esc isn't disturbed.
        if self._cancel_trigger and self._cancel_trigger != self._trigger_key:
            try:
                self._hook_handles.append(
                    keyboard.on_press_key(self._cancel_trigger, self._on_cancel,
                                          suppress=False))
            except Exception as e:
                log.debug("Kunde inte registrera avbryt-tangent: %s", e)
        # KP3: voice-edit hotkey — own press/release pair, separate from the
        # dictation hot path. Only registered when configured and distinct.
        #
        # Two mechanisms, because `keyboard.on_press_key` is unreliable for
        # modifier scan codes:
        #   * modifier-only hotkey (recommended, e.g. "right ctrl"/"ctrl+alt")
        #     → a single global hook edge-detects "all required modifiers held".
        #   * character trigger (legacy) → on_press_key with suppress=True so
        #     the character never types into (and replaces) the selection.
        if self._voice_edit_modifier_only and self._voice_edit_required_keys:
            # Map each required key to its scan codes so the global hook can
            # read held-state straight from the event (timing-safe).
            self._voice_edit_scancodes = {}
            for _k in self._voice_edit_required_keys:
                try:
                    self._voice_edit_scancodes[_k] = set(
                        keyboard.key_to_scan_codes(_k))
                except Exception:
                    self._voice_edit_scancodes[_k] = set()
            try:
                handle = keyboard.hook(self._on_voice_edit_global_event)
                self._hook_handles.append(handle)
                log.info("Röstredigering aktiv (global hook): %s",
                         "+".join(self._voice_edit_required_keys))
            except Exception as e:
                log.warning("Kunde inte registrera röstediterings-hook: %s", e)
        elif (self._voice_edit_hook_key
                and self._voice_edit_hook_key != self._trigger_key):
            for _key in self._voice_edit_hook_candidates:
                try:
                    h_press = keyboard.on_press_key(
                        _key, self._on_voice_edit_press, suppress=True)
                    h_release = keyboard.on_release_key(
                        _key, self._on_voice_edit_release, suppress=True)
                except Exception as e:
                    log.debug("Röstediterings-tangent '%s' ej hookbar: %s",
                              _key, e)
                    continue
                self._hook_handles.append(h_press)
                self._hook_handles.append(h_release)
                self._voice_edit_hook_key = _key  # the one that actually bound
                break
            else:
                if self._voice_edit_hook_candidates:
                    log.warning("Kunde inte registrera röstediterings-tangent "
                                "(%s)", self.voice_edit_hotkey)
        # KP4: voice-answer hotkey (modifier-only) — same global-hook mechanism.
        if self._voice_answer_modifier_only and self._voice_answer_required_keys:
            self._voice_answer_scancodes = {}
            for _k in self._voice_answer_required_keys:
                try:
                    self._voice_answer_scancodes[_k] = set(
                        keyboard.key_to_scan_codes(_k))
                except Exception:
                    self._voice_answer_scancodes[_k] = set()
            try:
                handle = keyboard.hook(self._on_voice_answer_global_event)
                self._hook_handles.append(handle)
                log.info("Svara-läge aktivt (global hook): %s",
                         "+".join(self._voice_answer_required_keys))
            except Exception as e:
                log.warning("Kunde inte registrera svara-hook: %s", e)
        self.on_status(f"Klar — håll {self.hotkey.upper()} för att prata")

    def undo_last(self) -> bool:
        """AP7.7: erase the most recently pasted block (best-effort)."""
        block = getattr(self, "_last_block", "")
        if not block:
            return False
        from paste import erase_last
        # +1 for the trailing space paste_text appends.
        erase_last(len(block) + 1)
        self._last_block = ""
        self._last_pasted = ""
        self.on_status("Ångrade senaste")
        if self.indicator:
            self.indicator.show("Ångrade", state="done")
            self.indicator.hide(delay_ms=1200)
        log.info("Ångrade senaste blocket (%d tecken)", len(block))
        return True

    def run_voice_edit(self, instruction: str) -> str:
        """KP3: apply a spoken instruction to the current selection.

        Reads the selection, runs it through the LLM with ``instruction``, and
        replaces the selection with the result. Returns a ``voice_edit`` result
        code. Fail-safe: never disturbs the selection on error, and is a no-op
        (``FAILED``) when LLM is disabled, since there's no transform to run.

        This is the routing seam — given an already-transcribed instruction it
        is fully testable. The hotkey→record→transcribe capture that produces
        ``instruction`` is wired separately (hot path; needs a Windows smoke
        test).
        """
        import voice_edit
        from paste import read_selection, paste_text

        tr = self.transcriber
        if not getattr(tr, "llm_enabled", False):
            log.info("Rösteditering kräver att LLM är på — ignorerar")
            if self.indicator:
                self.indicator.show("Slå på AI-städning först", state="error")
                self.indicator.hide(delay_ms=2000)
            return voice_edit.FAILED

        def _transform(selection: str, instr: str) -> str:
            from llm_polish import instruct
            return instruct(
                selection, instr,
                api_key=getattr(tr, "llm_api_key", ""),
                model=getattr(tr, "llm_model", ""),
                provider=getattr(tr, "llm_provider", "github"),
                base_url_override=getattr(tr, "llm_base_url", ""),
            )

        def _paste_replacement(text: str, replace_len: int) -> None:
            # The selection is still highlighted (read_selection only issued
            # Ctrl+C), so a paste overwrites it — replace_len stays 0.
            paste_text(text, active_modifiers=self._modifier_keys,
                       replace_len=replace_len)

        result = voice_edit.run(
            instruction,
            read_selection=lambda: read_selection(self._modifier_keys),
            transform=_transform,
            paste_replacement=_paste_replacement,
        )

        # Map result → UI (4 indicator states only).
        if self.indicator:
            if result == voice_edit.OK:
                self.indicator.show("Redigerat", state="done")
                self.indicator.hide(delay_ms=1200)
            elif result == voice_edit.NO_SELECTION:
                self.indicator.show("Markera text först", state="error")
                self.indicator.hide(delay_ms=2000)
            elif result == voice_edit.UNCHANGED:
                self.indicator.show("Ingen ändring", state="done")
                self.indicator.hide(delay_ms=1200)
            elif result in (voice_edit.FAILED, voice_edit.NO_INSTRUCTION):
                self.indicator.show("Kunde inte redigera", state="error")
                self.indicator.hide(delay_ms=2000)
        log.info("Rösteditering: %s", result)
        return result

    def run_voice_answer(self, instruction: str) -> str:
        """KP4: write a reply to the current selection; put it on the clipboard.

        Reads the selection as *context*, asks the LLM to generate a reply per
        ``instruction``, and copies the reply to the clipboard — it is **not**
        pasted, so a selection (here or elsewhere) is never overwritten. The
        user pastes it where they want with Ctrl+V. Returns a result code for
        the worker to map to the indicator. Fail-safe and a no-op without LLM.
        """
        from paste import read_selection, copy_to_clipboard

        tr = self.transcriber
        if not getattr(tr, "llm_enabled", False):
            log.info("Svara-läget kräver att LLM är på — ignorerar")
            if self.indicator:
                self.indicator.show("Slå på AI-städning först", state="error")
                self.indicator.hide(delay_ms=2000)
            return "failed"

        selection = (read_selection(self._modifier_keys) or "").strip()
        if not selection:
            if self.indicator:
                self.indicator.show("Markera text först", state="error")
                self.indicator.hide(delay_ms=2000)
            log.info("Svara-läget: no_selection")
            return "no_selection"

        from llm_polish import answer
        reply = (answer(
            selection, instruction,
            api_key=getattr(tr, "llm_api_key", ""),
            model=getattr(tr, "llm_model", ""),
            provider=getattr(tr, "llm_provider", "github"),
            base_url_override=getattr(tr, "llm_base_url", ""),
        ) or "").strip()

        if not reply:
            if self.indicator:
                self.indicator.show("Kunde inte skapa svar", state="error")
                self.indicator.hide(delay_ms=2000)
            log.info("Svara-läget: failed")
            return "failed"

        if not copy_to_clipboard(reply):
            if self.indicator:
                self.indicator.show("Kunde inte kopiera svar", state="error")
                self.indicator.hide(delay_ms=2000)
            return "failed"

        if self.indicator:
            self.indicator.show("Svar kopierat — Ctrl+V", state="done")
            self.indicator.hide(delay_ms=2500)
        log.info("Svara-läget: ok (%d tecken i urklipp)", len(reply))
        return "ok"

    def set_paused(self, paused: bool) -> None:
        """AP7.3: pause/resume dictation without quitting (session state)."""
        self._paused = bool(paused)
        log.info("Diktering %s", "pausad" if self._paused else "återupptagen")

    def is_paused(self) -> bool:
        return getattr(self, "_paused", False)

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

    def _try_command(self, text: str) -> bool:
        """AP5: if ``text`` is a command, transform the last block in place.

        Returns True when the command ran and the result was pasted (replacing
        the previous block); False when no command matched or it couldn't run,
        so the caller falls back to normal dictation.
        """
        try:
            import commands
        except Exception:
            return False
        cmd = commands.detect_command(text)
        if cmd is None:
            return False

        tr = self.transcriber

        def _llm_transform(instruction: str, prev: str) -> str:
            from llm_polish import instruct
            return instruct(
                prev, instruction,
                api_key=getattr(tr, "llm_api_key", ""),
                model=getattr(tr, "llm_model", ""),
                provider=getattr(tr, "llm_provider", "github"),
                base_url_override=getattr(tr, "llm_base_url", ""),
            )

        transform = _llm_transform if getattr(tr, "llm_enabled", False) else None
        prev_block = self._last_block
        result = commands.execute(cmd, prev_block, transform)
        if not result:
            # Recognised but couldn't run (e.g. LLM command with LLM off) —
            # let the caller dictate the words normally instead.
            return False
        if self._worker_stop.is_set() or not self._active:
            return True
        # Replace the previous block: backspace over exactly what we pasted
        # (paste_text strips + adds a trailing space), then paste the result.
        paste_text(result, active_modifiers=self._modifier_keys,
                   replace_len=replace_len_for(prev_block))
        self._last_block = result
        self._last_pasted = result
        msg = f"Kommando: {cmd.phrase}"
        self.on_status(f"{msg} — håll {self.hotkey.upper()} igen")
        if self.indicator:
            self.indicator.show(msg, state="done")
            self.indicator.hide(delay_ms=1800)
        log.info("Kommandoläge utförde '%s'", cmd.phrase)
        return True

    def _context_tail_for_stt(self, ctx, tr_provider: str) -> str:
        """Tail of the focused field's text, for Whisper continuation biasing.

        Feeding the last ~sentence of what already precedes the dictation into
        ``initial_prompt`` makes Whisper continue with consistent casing,
        terminology and punctuation (the same "context awareness" trick the
        commercial dictation apps use). Best-effort: the field reader returns
        the field's text, so when the caret is mid-document the tail may not
        be the exact caret context — initial_prompt is a soft bias, so a
        slightly-off tail degrades to a no-op rather than an error.

        Privacy: field text is screen content — the same data category as
        on-screen names. It biases the *local* decoder freely (never leaves
        the machine) but goes to a remote STT provider only with the explicit
        ``context_to_remote_accepted`` consent.
        """
        text = getattr(ctx, "focused_text", "") if ctx is not None else ""
        if not text:
            return ""
        if tr_provider != "local" and not getattr(
                self, "context_to_remote_accepted", False):
            return ""
        # Collapse whitespace/newlines (Whisper prompts are single-stream) and
        # keep a tail short enough to leave prompt budget for hotwords.
        tail = " ".join(text.split())[-_CTX_TAIL_MAX_CHARS:]
        # Avoid starting mid-word: drop the first (likely truncated) token.
        if len(tail) == _CTX_TAIL_MAX_CHARS and " " in tail:
            tail = tail.split(" ", 1)[1]
        return tail

    def _names_for_llm(self, onscreen_names: str) -> str:
        """Gate on-screen names before they reach the LLM polisher.

        Same data category and consent as the remote-STT gate: names scraped
        from the focused window/UI may only be sent to a *remote* LLM provider
        when the user has explicitly consented. A local loopback LLM
        (http://localhost/...) never leaves the machine, so it's exempt.
        """
        if not onscreen_names:
            return ""
        provider = getattr(self.transcriber, "llm_provider", "")
        base_url = getattr(self.transcriber, "llm_base_url", "")
        is_local = False
        if provider == "custom" and base_url:
            try:
                from url_security import is_plaintext_loopback
                is_local = is_plaintext_loopback(base_url)
            except Exception:
                is_local = False
        if is_local or getattr(self, "context_to_remote_accepted", False):
            return onscreen_names
        log.debug("Skärmnamn skickas ej till remote-LLM (medgivande saknas)")
        return ""

    def _dictate_replace_mode(self, text: str, record_ms: float,
                              transcribe_ms: float, context_hotpath_ms: float,
                              uia_ms: float, profile_desc: str,
                              onscreen_names: str) -> None:
        """L3: paste the raw transcript immediately, then replace it with the
        polished version when polish lands (editable fields only)."""
        t_p0 = time.monotonic()
        paste_text(text, active_modifiers=self._modifier_keys)
        raw_paste_ms = (time.monotonic() - t_p0) * 1000
        self._last_pasted = text
        self._last_block = text
        log.info("Latens (rå→ersätt) första synliga: record=%.0fms "
                 "transcribe=%.0fms paste=%.0fms",
                 record_ms, transcribe_ms, raw_paste_ms)
        self.on_status("Klistrad (rå) — granskar…")
        if self.indicator:
            self.indicator.show("Granskar…", state="transcribe")

        raw_text = text
        t_llm0 = time.monotonic()

        def _on_replace(original: str, polished: str) -> None:
            if self._worker_stop.is_set() or not self._active:
                return
            llm_ms = (time.monotonic() - t_llm0) * 1000
            tr = self.transcriber
            replace_ms = 0.0
            # Only replace if our raw paste is still the last thing pasted
            # (best-effort: a newer dictation/command supersedes it; pressing
            # Enter/Tab before polish lands may still cause a double — a
            # documented trade-off of this mode).
            if (polished and polished != raw_text
                    and self._last_pasted == raw_text):
                t_r0 = time.monotonic()
                paste_text(polished, active_modifiers=self._modifier_keys,
                           replace_len=replace_len_for(raw_text))
                self._last_pasted = polished
                self._last_block = polished
                replace_ms = (time.monotonic() - t_r0) * 1000
            self._log_latency(
                record_ms, transcribe_ms, llm_ms, raw_paste_ms + replace_ms,
                context_hotpath_ms=context_hotpath_ms, uia_ms=uia_ms,
                conn_ms=getattr(tr, "last_polish_conn_ms", 0.0),
                conn_reused=getattr(tr, "last_polish_conn_reused", None),
                first_token_ms=getattr(tr, "last_polish_first_token_ms", 0.0))
            state = getattr(tr, "last_polish_state", "local")
            msg = ("Klistrad (LLM-polerad)" if state == "llm_changed"
                   else "Klistrad (LLM-granskad)")
            self.on_status(f"{msg} — håll {self.hotkey.upper()} igen")
            if self.indicator:
                self.indicator.show(msg, state="done")
                self.indicator.hide(delay_ms=1800)

        try:
            self.transcriber.polish_async(
                raw_text, _on_replace, on_stage=None,
                app_profile=profile_desc,
                onscreen_names=self._names_for_llm(onscreen_names))
        except Exception as e:
            log.error("polish_async (rå→ersätt) kraschade: %s", e, exc_info=True)

    def _live_loop(self, ps: "_PressState") -> None:
        """L5.7: while recording, transcribe completed (silence-delimited)
        chunks ahead of release so only the tail remains afterwards.

        Tracks progress as a *sample offset* into the (16 kHz finalized)
        recording, not a chunk count. Because a completed chunk is one followed
        by detected silence, its end offset is stable as the recording grows —
        so the post-release tail in ``_combine_live`` is exactly the audio after
        the last decoded chunk, with no boundary drift / dropped or duplicated
        words. Results are written into *ps* so a later press can't clobber them.

        Finalization is incremental (audio.StreamingFinalizer): only the raw
        samples added since the previous poll are downmixed/resampled, instead
        of re-finalizing the whole growing snapshot every 400 ms (which was
        O(n²) total work). Falls back to whole-snapshot finalize when soxr is
        unavailable (scipy can't resample statefully across chunk boundaries).
        """
        from audio import StreamingFinalizer
        from flow import silence_segments
        consumed_samples = 0  # end of last decoded chunk (16 kHz samples)
        parts: list[str] = []
        finalizer: StreamingFinalizer | None = None
        raw_done = 0  # raw samples already fed to the finalizer
        final = np.empty(0, dtype=np.float32)  # accumulated 16 kHz audio
        try:
            while self._recording and self._active:
                time.sleep(_LIVE_POLL_S)
                audio_raw, ch, rate = self.recorder.snapshot()
                if audio_raw.size == 0:
                    continue
                if StreamingFinalizer.available():
                    if finalizer is None:
                        finalizer = StreamingFinalizer(ch, rate)
                    new_raw = audio_raw[raw_done:]
                    raw_done = audio_raw.shape[0]
                    new16 = finalizer.feed(new_raw)
                    if new16.size:
                        final = np.concatenate([final, new16])
                else:
                    final = finalize_audio(audio_raw, ch, rate)
                bounds = silence_segments(final, 16000, self.min_rms)
                # Decode every *completed* chunk (all but the last, which is
                # still growing) that we haven't already consumed.
                for a0, a1 in bounds[:-1]:
                    if a0 < consumed_samples:
                        continue  # already decoded in an earlier pass
                    if not (self._recording and self._active):
                        break
                    # Feed the already-decoded partials as continuation
                    # context so chunk-by-chunk decoding doesn't lose the
                    # intra-utterance context a whole-clip decode would have.
                    txt = self.transcriber.transcribe(
                        final[a0:a1],
                        preceding_text=" ".join(parts)[-_CTX_TAIL_MAX_CHARS:])
                    if txt.strip():
                        parts.append(txt.strip())
                    consumed_samples = a1
        except Exception as e:
            log.debug("Live-transkribering fel: %s", e)
        ps.live_parts = parts
        ps.live_consumed = consumed_samples

    def _combine_live(self, audio: np.ndarray, press_state=None) -> str:
        """L5.7: join live partials with the post-release tail. Degrades to a
        normal full-batch transcribe for short utterances (one chunk).

        Reads the live partials from *press_state* when given (the per-job
        binding), falling back to the legacy instance attributes for callers
        that don't pass one (tests)."""
        from flow import split_on_silence
        if press_state is not None:
            t = press_state.live_thread
            if t is not None and t.is_alive():
                t.join(timeout=5.0)
            parts = list(press_state.live_parts)
            consumed_samples = press_state.live_consumed
        else:
            t = getattr(self, "_live_thread", None)
            if t is not None and t.is_alive():
                t.join(timeout=5.0)
            parts = list(getattr(self, "_live_parts", []))
            consumed_samples = getattr(self, "_live_consumed", 0)
        # The tail is exactly the audio after the last live-decoded chunk
        # (consumed_samples is a sample offset, not a chunk count). Clamp it:
        # the live loop's incremental resampler can land a few samples off the
        # batch-finalized length, and a chunk always ends in detected silence
        # so the clamp lands in silence. Re-split only the tail so a long
        # trailing segment with internal pauses still chunks well, without
        # ever re-touching already-decoded audio.
        consumed_samples = min(int(consumed_samples), int(audio.size))
        tail = audio[consumed_samples:] if consumed_samples < audio.size else audio[:0]
        tail_chunks = split_on_silence(tail, 16000, self.min_rms)
        if not tail_chunks and tail.size:
            tail_chunks = [tail]
        for c in tail_chunks:
            # Same continuation context as the live loop: the partials
            # decoded so far precede this tail.
            txt = self.transcriber.transcribe(
                c, preceding_text=" ".join(parts)[-_CTX_TAIL_MAX_CHARS:])
            if txt.strip():
                parts.append(txt.strip())
        return " ".join(parts).strip()

    @staticmethod
    def _expand_snippet(text: str) -> str:
        """AP7.6: expand a leading snippet trigger. Returns text unchanged on
        no match / any failure."""
        try:
            import snippets
            return snippets.expand(text)
        except Exception:
            return text

    @staticmethod
    def _read_focused_text() -> str:
        """Best-effort read of the focused field (AP3 → AP2 learning)."""
        try:
            import context_win
            return context_win.get_focused_text()
        except Exception:
            return ""

    def _resolve_context(self):
        """AP3: resolve active-app profile + on-screen names. Best-effort.

        Synchronous fallback used when no press-time snapshot is available
        (legacy callers / tests). The hot path uses the async snapshot instead.
        """
        try:
            import context_win
            return context_win.get_context(getattr(self, "app_profiles", None))
        except Exception as e:
            log.debug("Kontextmedvetenhet misslyckades: %s", e)
            return None

    def _resolve_context_async(self, holder, last_pasted: str) -> None:
        """L1: resolve context off the hot path. Reads the focused field once,
        whose text serves both AP2 learning and AP3 biasing."""
        try:
            import context_win
            app, _title = context_win.get_active_app()
            profile_key = context_win.resolve_profile_key(
                app, getattr(self, "app_profiles", None))
            profile = context_win.PROFILES.get(
                profile_key, context_win.PROFILES["default"])
            # Skip the (expensive) field read only when nothing needs it: a
            # polish-off profile (e.g. code) AND no prior paste to learn from.
            need_text = profile.polish or bool(last_pasted)
            holder.ctx = context_win.get_context(
                getattr(self, "app_profiles", None), read_text=need_text)
        except Exception as e:
            log.debug("Kontext (async) misslyckades: %s", e)
            holder.ctx = None
        finally:
            holder.event.set()

    def _await_context(self, press_state=None):
        """Return ``(ctx, hotpath_ms)`` from the press-time resolution (L1).

        Prefers the holder bound to *press_state* (the per-job binding); falls
        back to the legacy instance slot for callers that don't pass one."""
        holder = press_state.ctx_holder if press_state is not None else None
        if holder is None:
            holder = getattr(self, "_ctx_result", None)
        if holder is None:
            return None, 0.0
        t0 = time.monotonic()
        holder.event.wait(timeout=_CTX_JOIN_TIMEOUT)
        elapsed = (time.monotonic() - t0) * 1000
        if not holder.event.is_set():
            log.debug("Kontext ej klar inom %.0f ms — tom kontext", _CTX_JOIN_TIMEOUT * 1000)
        return holder.ctx, elapsed

    def _observe_corrections(self, ctx=None) -> None:
        """AP2: compare the previously pasted text against the focused field.

        Consumes the focused-field text from the press-time snapshot (``ctx``)
        so it never issues its own UIA read on the critical path (L1). Falls
        back to ``_field_reader`` only when no snapshot is available (legacy).
        Best-effort and silent on any failure — never blocks dictation.
        """
        if not getattr(self, "learning_enabled", True):
            return
        last = getattr(self, "_last_pasted", "")
        if not last:
            return
        self._last_pasted = ""
        observed = ""
        if ctx is not None and getattr(ctx, "focused_text", ""):
            observed = ctx.focused_text
        else:
            reader = getattr(self, "_field_reader", None)
            if reader is not None:
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
                     llm_ms: float, paste_ms: float, *,
                     context_hotpath_ms: float = 0.0, uia_ms: float = 0.0,
                     conn_ms: float = 0.0, conn_reused: bool | None = None,
                     first_token_ms: float = 0.0) -> None:
        """Log the per-step latency breakdown for the hot path (AP1 + L0).

        ``context_hotpath_ms`` is how much context/UIA work landed on the
        critical path (≈0 once L1 overlaps it with recording); ``uia_ms`` is the
        raw UIA read time wherever it ran; ``conn_ms``/``conn_reused`` describe
        remote connection setup; ``first_token_ms`` is polish TTFT.
        """
        pipeline = transcribe_ms + llm_ms + paste_ms
        reused = "?" if conn_reused is None else ("true" if conn_reused else "false")
        log.info(
            "Latens: record=%.0fms transcribe=%.0fms llm=%.0fms paste=%.0fms "
            "context_hotpath=%.0fms uia=%.0fms conn=%.0fms conn_reused=%s "
            "first_token=%.0fms (pipeline efter release=%.0fms)",
            record_ms, transcribe_ms, llm_ms, paste_ms,
            context_hotpath_ms, uia_ms, conn_ms, reused, first_token_ms, pipeline,
        )
        _record_latency_sample({
            "transcribe_ms": transcribe_ms, "llm_ms": llm_ms,
            "paste_ms": paste_ms, "context_hotpath_ms": context_hotpath_ms,
            "conn_ms": conn_ms,
        })

    def _modifier_held(self) -> bool:
        """All required modifiers must be physically held right now."""
        if not self._modifiers:
            return True
        try:
            return all(keyboard.is_pressed(m) for m in self._modifiers)
        except Exception:
            return False

    def _voice_edit_modifiers_held(self) -> bool:
        gate = getattr(self, "_voice_edit_gate_modifiers",
                       self._voice_edit_modifiers)
        if not gate:
            return True
        try:
            return all(keyboard.is_pressed(m) for m in gate)
        except Exception:
            return False

    def _combo_held(self, keys, codes_map, event=None) -> bool:
        """True when *every* key in ``keys`` is physically down.

        When called from the global hook we trust the *current* event for the
        key it concerns (a down/up we're handling right now) to avoid
        ``is_pressed`` update-order races on the listener thread; other required
        keys fall back to ``is_pressed``. Shared by voice-edit and voice-answer.
        """
        if not keys:
            return False
        sc = getattr(event, "scan_code", None) if event is not None else None
        etype = getattr(event, "event_type", None) if event is not None else None
        try:
            for k in keys:
                codes = (codes_map or {}).get(k)
                if codes and sc is not None and sc in codes:
                    ok = (etype == "down")
                else:
                    ok = keyboard.is_pressed(k)
                if not ok:
                    return False
            return True
        except Exception:
            return False

    def _voice_edit_required_held(self, event=None) -> bool:
        """True when every key of the voice-edit modifier-only hotkey is down."""
        return self._combo_held(
            getattr(self, "_voice_edit_required_keys", ()),
            getattr(self, "_voice_edit_scancodes", {}), event)

    def _on_voice_edit_global_event(self, event):
        """Global keyboard hook driving a modifier-only voice-edit hotkey.

        ``keyboard.on_press_key`` does not fire for modifier scan codes (e.g.
        right ctrl = 57373), so we watch every event and edge-detect when the
        full required-modifier combo becomes held (start) or is broken (stop).
        Runs on the keyboard-listener thread — kept cheap and exception-safe so
        it can never break the global listener.
        """
        try:
            engaged = self._voice_edit_required_held(event)
            if engaged and not self._voice_edit_engaged:
                self._voice_edit_engaged = True
                self._on_voice_edit_press(event)
            elif not engaged and self._voice_edit_engaged:
                self._voice_edit_engaged = False
                self._on_voice_edit_release(event)
        except Exception as e:
            log.debug("voice-edit global hook error: %s", e)

    def _on_voice_edit_press(self, _):
        """KP3: start recording a voice-edit instruction. Mirrors _on_press but
        flags the capture so the worker routes it to run_voice_edit() instead of
        pasting it as dictation. Kept separate so the dictation hot path is
        untouched."""
        if not (self._active and not getattr(self, "_paused", False)
                and not self._recording
                and self._voice_edit_modifiers_held()):
            return
        try:
            self._recording = True
            self._voice_editing = True
            self._t_press = time.monotonic()
            # No context/live-transcribe for an instruction — it's a command,
            # not dictated prose. Keeps this path minimal.
            if self.indicator is not None:
                self.recorder.on_level = self.indicator.push_level
            else:
                self.recorder.on_level = None
            self.recorder.start()
            sounds.play_start()
            self.on_status("Lyssnar på redigering…")
            if self.indicator:
                self.indicator.show("Säg en redigering…", state="listen",
                                    level_source=lambda: self.recorder.level)
        except Exception as e:
            self._recording = False
            self._voice_editing = False
            log.error("Mic start error (voice-edit): %s", e, exc_info=True)
            sounds.play_error()

    def _on_voice_edit_release(self, _):
        """KP3: stop the instruction recording and enqueue it tagged as a
        voice-edit job."""
        if not (self._active and self._recording
                and getattr(self, "_voice_editing", False)):
            return
        self._recording = False
        self.recorder.on_level = None
        try:
            audio, channels, rate = self.recorder.stop_fast()
        except Exception as e:
            self._voice_editing = False
            log.error("Audio stop error (voice-edit): %s", e, exc_info=True)
            sounds.play_error()
            return
        sounds.play_stop()
        rms = self.recorder.rms()
        record_ms = (time.monotonic() - self._t_press) * 1000 if self._t_press else 0.0
        # Tagged job: the 6th element marks this as a voice-edit instruction so
        # the worker transcribes it and routes to run_voice_edit().
        try:
            self._jobs.put_nowait((audio, channels, rate, rms, record_ms,
                                   "voice_edit", None))
        except queue.Full:
            log.warning("Kö full — hoppar över röstediteringen")
            self._voice_editing = False
            return
        self.on_status("Tolkar redigering…")
        if self.indicator:
            self.indicator.show("Tolkar redigering…", state="transcribe")

    # ---- KP4 voice-answer (reply to selection; result to clipboard) -------- #

    def _on_voice_answer_global_event(self, event):
        """Global hook driving the modifier-only voice-answer hotkey."""
        try:
            engaged = self._combo_held(
                self._voice_answer_required_keys,
                getattr(self, "_voice_answer_scancodes", {}), event)
            if engaged and not self._voice_answer_engaged:
                self._voice_answer_engaged = True
                self._on_voice_answer_press(event)
            elif not engaged and self._voice_answer_engaged:
                self._voice_answer_engaged = False
                self._on_voice_answer_release(event)
        except Exception as e:
            log.debug("voice-answer global hook error: %s", e)

    def _on_voice_answer_press(self, _):
        """Start recording a voice-answer instruction (mirrors voice-edit)."""
        if not (self._active and not getattr(self, "_paused", False)
                and not self._recording):
            return
        try:
            self._recording = True
            self._voice_answering = True
            self._t_press = time.monotonic()
            if self.indicator is not None:
                self.recorder.on_level = self.indicator.push_level
            else:
                self.recorder.on_level = None
            self.recorder.start()
            sounds.play_start()
            self.on_status("Lyssnar på svar…")
            if self.indicator:
                self.indicator.show("Säg vad du vill svara…", state="listen",
                                    level_source=lambda: self.recorder.level)
        except Exception as e:
            self._recording = False
            self._voice_answering = False
            log.error("Mic start error (voice-answer): %s", e, exc_info=True)
            sounds.play_error()

    def _on_voice_answer_release(self, _):
        """Stop recording and enqueue the instruction tagged as voice-answer."""
        if not (self._active and self._recording
                and getattr(self, "_voice_answering", False)):
            return
        self._recording = False
        self.recorder.on_level = None
        try:
            audio, channels, rate = self.recorder.stop_fast()
        except Exception as e:
            self._voice_answering = False
            log.error("Audio stop error (voice-answer): %s", e, exc_info=True)
            sounds.play_error()
            return
        sounds.play_stop()
        rms = self.recorder.rms()
        record_ms = (time.monotonic() - self._t_press) * 1000 if self._t_press else 0.0
        try:
            self._jobs.put_nowait((audio, channels, rate, rms, record_ms,
                                   "voice_answer", None))
        except queue.Full:
            log.warning("Kö full — hoppar över svaret")
            self._voice_answering = False
            return
        self.on_status("Skapar svar…")
        if self.indicator:
            self.indicator.show("Skapar svar…", state="transcribe")

    def _on_cancel(self, _):
        """AP7.2: discard the in-progress recording. No-op when not recording
        (so normal Esc is left alone)."""
        if not (self._active and self._recording):
            return
        self._recording = False
        self.recorder.on_level = None
        try:
            self.recorder.shutdown()   # close stream + drop captured audio
        except Exception:
            log.debug("recorder.shutdown() vid avbrott misslyckades", exc_info=True)
        try:
            sounds.play_error()
        except Exception:
            pass
        self.on_status(f"Avbruten — håll {self.hotkey.upper()}")
        if self.indicator:
            self.indicator.show("Avbruten", state="error")
            self.indicator.hide(delay_ms=1500)
        log.info("Diktering avbruten (%s)", self.cancel_hotkey)

    def _on_press(self, _):
        if (self._active and not getattr(self, "_paused", False)
                and not self._recording and self._modifier_held()):
            try:
                self._recording = True
                self._t_press = time.monotonic()
                # Per-press state, bound to this recording's eventual job so a
                # quick next press can't clobber it (see _PressState).
                ps = _PressState()
                self._press_state = ps
                # L1: resolve active-app context + focused-field snapshot on a
                # daemon thread *now*, overlapping the whole recording, so the
                # UIA cost is off the critical path after key-up.
                self._ctx_result = None
                if getattr(self, "context_awareness", False):
                    holder = _ContextHolder()
                    self._ctx_result = holder
                    ps.ctx_holder = holder
                    threading.Thread(
                        target=self._resolve_context_async,
                        args=(holder, self._last_pasted),
                        name="ctx-resolve", daemon=True).start()
                # Wire the audio thread to push RMS levels directly to the
                # UI indicator — replaces the 50 ms polling timer with an
                # event-driven path. Cleared in _on_release.
                if self.indicator is not None:
                    self.recorder.on_level = self.indicator.push_level
                else:
                    self.recorder.on_level = None
                self.recorder.start()
                # L5.7: live-transcribe completed chunks while recording (local
                # provider only; Fas 2 remote is intentionally a no-op).
                self._live_active = False
                if (getattr(self, "live_transcribe_enabled", False)
                        and getattr(self.transcriber, "transcription_provider",
                                    "local") == "local"):
                    self._live_active = True
                    ps.live_active = True
                    self._live_parts = []
                    self._live_consumed = 0
                    ps.live_thread = threading.Thread(
                        target=self._live_loop, args=(ps,),
                        name="live-tx", daemon=True)
                    self._live_thread = ps.live_thread
                    self._live_thread.start()
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
            self._jobs.put_nowait((audio, channels, rate, rms, record_ms,
                                   "dictation", self._press_state))
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
                     rate: int, rms: float, record_ms: float = 0.0,
                     kind: str = "dictation", press_state=None):
        n_raw = audio_raw.shape[0] if audio_raw.ndim >= 1 else 0
        log.info("Audio: %d raw samples, RMS=%.5f", n_raw, rms)

        # KP3: a voice-edit instruction — transcribe it, then apply it to the
        # current selection via run_voice_edit() instead of pasting it.
        if kind == "voice_edit":
            self._voice_editing = False
            try:
                if rms < self.min_rms:
                    log.info("Röstedigering för tyst, ignorerar")
                    if self.indicator:
                        self.indicator.show("Inget hördes", state="error")
                        self.indicator.hide(delay_ms=1500)
                    return
                audio = finalize_audio(audio_raw, channels, rate)
                if len(audio) < MIN_AUDIO_SAMPLES:
                    # Mirror the sibling branches: don't leave the pill stuck
                    # in "Tolkar redigering…" when the clip is too short.
                    if self.indicator:
                        self.indicator.show("Inget hördes", state="error")
                        self.indicator.hide(delay_ms=1500)
                    return
                instruction = self.transcriber.transcribe(audio, capitalize=False)
                if instruction.strip():
                    self.run_voice_edit(instruction)
                elif self.indicator:
                    self.indicator.show("Hörde ingen redigering", state="error")
                    self.indicator.hide(delay_ms=1500)
            except Exception as e:
                log.error("Voice-edit job error: %s", e, exc_info=True)
            return

        # KP4: a voice-answer instruction — transcribe it, then generate a reply
        # to the current selection and put it on the clipboard (never pasted).
        if kind == "voice_answer":
            self._voice_answering = False
            try:
                if rms < self.min_rms:
                    log.info("Svara-instruktion för tyst, ignorerar")
                    if self.indicator:
                        self.indicator.show("Inget hördes", state="error")
                        self.indicator.hide(delay_ms=1500)
                    return
                audio = finalize_audio(audio_raw, channels, rate)
                if len(audio) < MIN_AUDIO_SAMPLES:
                    if self.indicator:
                        self.indicator.show("Inget hördes", state="error")
                        self.indicator.hide(delay_ms=1500)
                    return
                instruction = self.transcriber.transcribe(audio, capitalize=False)
                if instruction.strip():
                    self.run_voice_answer(instruction)
                elif self.indicator:
                    self.indicator.show("Hörde ingen instruktion", state="error")
                    self.indicator.hide(delay_ms=1500)
            except Exception as e:
                log.error("Voice-answer job error: %s", e, exc_info=True)
            return

        # L1: collect the press-time context snapshot once (bounded wait) and
        # reuse it for both the learning loop and transcription/polish.
        ctx, context_hotpath_ms = self._await_context(press_state)

        # AP2: learn from any manual edits the user made to the last paste
        # before starting this new dictation (best-effort, never blocks).
        self._observe_corrections(ctx)

        if rms < self.min_rms:
            log.info("Inspelning för tyst (RMS=%.5f < %.5f), ignorerar",
                     rms, self.min_rms)
            self.on_status(f"Inget hördes — håll {self.hotkey.upper()}")
            if self.indicator:
                self.indicator.show("Inget hördes", state="error")
                self.indicator.hide(delay_ms=1500)
            return

        # Audio prep (downmix/resample/trim) gets its own handler: a failure
        # here would otherwise bubble to _worker_loop's catch-all, which only
        # logs — leaving the indicator stuck on "Transkriberar…" with no user-
        # visible error. _transcribe() below has its own equivalent tail.
        try:
            audio = finalize_audio(audio_raw, channels, rate)
            n = len(audio)

            if n < MIN_AUDIO_SAMPLES:
                log.info("Inspelning för kort (%d samples), ignorerar", n)
                self.on_status(f"Klar — håll {self.hotkey.upper()}")
                if self.indicator:
                    self.indicator.hide(delay_ms=0)
                return

            # L5.5: trim edge silence (cheaper than VAD) so fewer samples reach
            # Whisper. Keeps a pad so word edges aren't clipped.
            if getattr(self, "silence_trim_enabled", True):
                trimmed = _trim_silence(audio, 16000, self.min_rms)
                if trimmed.size >= MIN_AUDIO_SAMPLES and trimmed.size < n:
                    log.info("RMS-trim: %d -> %d samples", n, trimmed.size)
                    audio = trimmed
        except Exception as e:
            log.error("Ljudberedning misslyckades: %s", e, exc_info=True)
            self.on_status(f"Fel — håll {self.hotkey.upper()}")
            if self.indicator:
                self.indicator.show("Kunde inte bearbeta ljudet", state="error")
                self.indicator.hide(delay_ms=4000)
            return

        self._transcribe(audio, record_ms, ctx=ctx,
                         context_hotpath_ms=context_hotpath_ms,
                         press_state=press_state)

    def _transcribe(self, audio: np.ndarray, record_ms: float = 0.0,
                    ctx=_NO_CTX, context_hotpath_ms: float = 0.0,
                    press_state=None):
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

            # AP3/L1 context: prefer the press-time snapshot (off the hot path).
            # When called without one (legacy/tests) resolve synchronously.
            if ctx is _NO_CTX:
                ctx = None
                context_hotpath_ms = 0.0
                if getattr(self, "context_awareness", False):
                    t_ctx0 = time.monotonic()
                    ctx = self._resolve_context()
                    context_hotpath_ms = (time.monotonic() - t_ctx0) * 1000

            # A "code"-style profile disables polish and capitalisation; names
            # bias the local decoder and (only when polishing) the LLM prompt.
            profile_desc = ""
            onscreen_names = ""
            capitalize = True
            uia_ms = 0.0
            if ctx is not None:
                profile_desc = ctx.profile_description
                onscreen_names = ctx.onscreen_names
                capitalize = ctx.capitalize
                uia_ms = getattr(ctx, "read_ms", 0.0)
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
            tr_label = _provider_status_label(tr_provider)
            if llm_enabled or tr_provider != "local":
                self.on_status(f"Transkriberar {tr_label}…")
                if self.indicator:
                    self.indicator.show(f"Transkriberar {tr_label}…", state="transcribe")
            # Privacy gate: on-screen names bias the local decoder freely (they
            # never leave the machine), but are only forwarded to a *remote* STT
            # provider when the user has explicitly consented — they are a
            # separate data category from the audio itself.
            stt_hotwords = onscreen_names
            if tr_provider != "local" and not getattr(
                    self, "context_to_remote_accepted", False):
                if onscreen_names:
                    log.debug("Skärmnamn skickas ej till remote-STT "
                              "(medgivande saknas)")
                stt_hotwords = ""
            # Continuation bias: the tail of what already precedes the caret
            # goes into Whisper's initial_prompt (same remote gate as names).
            preceding = self._context_tail_for_stt(ctx, tr_provider)
            live_active = (press_state.live_active if press_state is not None
                           else getattr(self, "_live_active", False))
            if live_active:
                # L5.7: most of the audio was already decoded during recording;
                # only the tail remains. Live mode is local-only, so the remote
                # privacy gate above is a no-op there (stt_hotwords == names).
                text = self._combine_live(audio, press_state)
            else:
                text = self.transcriber.transcribe(
                    audio, capitalize=capitalize, extra_hotwords=stt_hotwords,
                    preceding_text=preceding)
            transcribe_ms = (time.monotonic() - t_tx0) * 1000
            log.info("Resultat klart (%s)", _text_meta(text))
            if text.strip():
                if self._worker_stop.is_set() or not self._active:
                    log.info("Hoppar över paste från stale transkribering")
                    return

                # AP5 command mode: if this utterance is a command on the last
                # block, edit that block in place instead of dictating new text.
                if (getattr(self, "command_mode_enabled", False)
                        and getattr(self, "_last_block", "")
                        and self._try_command(text)):
                    return

                # AP7.6 snippets: expand a leading trigger phrase. A canned
                # expansion is pasted directly (no polish reformatting).
                if getattr(self, "snippets_enabled", False):
                    expanded = self._expand_snippet(text)
                    if expanded != text:
                        t_p0 = time.monotonic()
                        paste_text(expanded, active_modifiers=self._modifier_keys)
                        self._last_pasted = expanded
                        self._last_block = expanded
                        self._log_latency(record_ms, transcribe_ms, 0.0,
                                          (time.monotonic() - t_p0) * 1000,
                                          context_hotpath_ms=context_hotpath_ms,
                                          uia_ms=uia_ms)
                        self.on_status(f"Snippet — håll {self.hotkey.upper()} igen")
                        if self.indicator:
                            self.indicator.show("Snippet", state="done")
                            self.indicator.hide(delay_ms=1500)
                        return

                # L5.6: skip the whole LLM round-trip for trivial transcripts
                # (short + no disfluencies) — text is pasted directly.
                if (llm_enabled and getattr(self, "polish_skip_trivial", True)
                        and _is_trivial(text, getattr(self, "polish_skip_max_words", 6))):
                    log.info("Trivialt yttrande (%d ord) — hoppar polish",
                             len(text.split()))
                    llm_enabled = False

                # L3 "rå → ersätt": paste raw now, replace with polished later.
                # Reaches here only for editable fields (code/terminal profiles
                # disable polish, so llm_enabled is already False there).
                if llm_enabled and getattr(self, "llm_replace_mode", False):
                    self._dictate_replace_mode(
                        text, record_ms, transcribe_ms, context_hotpath_ms,
                        uia_ms, profile_desc, onscreen_names)
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
                    # Mirror the transcription status: name where the text is
                    # going so the user always sees which service polishes it.
                    llm_provider = getattr(self.transcriber, "llm_provider", "local")
                    polish_label = _provider_status_label(llm_provider)
                    self.on_status(f"Polerar {polish_label}…")
                    if self.indicator:
                        # Polish is still "processing" — reuse the transcribe
                        # state (orange). The indicator only supports the four
                        # canonical states (listen/transcribe/done/error).
                        self.indicator.show(f"Polerar {polish_label}…", state="transcribe")

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
                        self._last_block = final_text
                        tr = self.transcriber
                        self._log_latency(
                            record_ms, transcribe_ms, llm_ms,
                            (time.monotonic() - t_p0) * 1000,
                            context_hotpath_ms=context_hotpath_ms, uia_ms=uia_ms,
                            conn_ms=getattr(tr, "last_polish_conn_ms", 0.0),
                            conn_reused=getattr(tr, "last_polish_conn_reused", None),
                            first_token_ms=getattr(tr, "last_polish_first_token_ms", 0.0))
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
                            self.indicator.hide(delay_ms=950)

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
                            onscreen_names=self._names_for_llm(onscreen_names))
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
                    self._last_block = text
                    tr = self.transcriber
                    self._log_latency(
                        record_ms, transcribe_ms, 0.0,
                        (time.monotonic() - t_p0) * 1000,
                        context_hotpath_ms=context_hotpath_ms, uia_ms=uia_ms,
                        conn_ms=getattr(tr, "last_transcribe_conn_ms", 0.0),
                        conn_reused=getattr(tr, "last_transcribe_conn_reused", None))
                    message = "Klistrad"
                    self.on_status(f"{message} — håll {self.hotkey.upper()} igen")
                    if self.indicator:
                        self.indicator.show(message, state="done")
                        self.indicator.hide(delay_ms=950)
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
