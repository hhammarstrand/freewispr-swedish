"""KBLab Whisper transcription with optional LLM polishing."""
from __future__ import annotations

import re
import logging
import threading
from collections.abc import Callable
from pathlib import Path
import numpy as np
from faster_whisper import WhisperModel


log = logging.getLogger("freewispr")

CONFIG_DIR = Path.home() / ".freewispr-swedish"
MODEL_DIR = CONFIG_DIR / "models"
HOTWORDS_FILE = CONFIG_DIR / "hotwords.txt"

# How often to ping the LLM endpoint to keep the pooled connection alive (L3).
# Comfortably under typical keep-alive idle timeouts (~60 s).
_LLM_WARM_INTERVAL = 25.0


def _text_meta(text: str) -> str:
    words = len(text.split())
    return f"chars={len(text)}, words={words}"


def _find_local_model(repo_name: str, revision: str = "default") -> str | None:
    """Return local snapshot path if the model is already downloaded.

    Checks two locations in order:
      1. Manually converted CTranslate2 model:
         MODEL_DIR/kb-whisper-{size}-ct2/model.bin
         These are converted via ctranslate2.converters.TransformersConverter
         and are known to work correctly (no vocabulary mismatch issues).
      2. HuggingFace snapshot:
         MODEL_DIR/models--<org>--<name>/snapshots/<hash>/model.bin
         These may need vocabulary patching for large/medium models.

    AP4: when ``revision`` is a KBLab style variant (``strict``/``subtitle``),
    a separate CT2 build at ``{short_name}-{revision}-ct2`` is preferred. If
    that build is missing we log and fall back to the default model — we never
    silently use a different decode style than requested without the user's
    converted artefact present.
    """
    # repo_name is e.g. "KBLab/kb-whisper-large" → extract "kb-whisper-large"
    short_name = repo_name.split("/")[-1] if "/" in repo_name else repo_name

    revision = (revision or "default").strip().lower()
    if revision in ("strict", "subtitle"):
        rev_dir = MODEL_DIR / f"{short_name}-{revision}-ct2"
        if rev_dir.exists() and (rev_dir / "model.bin").exists():
            log.info("Använder KBLab-revision '%s' ct2-modell: %s",
                     revision, rev_dir)
            return str(rev_dir)
        log.warning(
            "CT2-bygge för revision '%s' saknas (%s) — faller tillbaka till "
            "default. Kör 'python convert_model.py %s --revision %s' för att "
            "skapa det.", revision, rev_dir, short_name, revision,
        )

    # 1. Check for manually converted ct2 model first
    ct2_dir = MODEL_DIR / f"{short_name}-ct2"
    if ct2_dir.exists() and (ct2_dir / "model.bin").exists():
        log.info("Hittade konverterad ct2-modell: %s", ct2_dir)
        return str(ct2_dir)

    # 2. Fall back to HuggingFace snapshot
    safe_name = repo_name.replace("/", "--")
    model_dir = MODEL_DIR / f"models--{safe_name}"
    if not model_dir.exists():
        return None
    snapshots = model_dir / "snapshots"
    if not snapshots.exists():
        return None
    # Pick the newest snapshot that contains a model.bin
    for snap in sorted(snapshots.iterdir(), reverse=True):
        if (snap / "model.bin").exists():
            _patch_vocabulary(snap)
            return str(snap)
    return None


def _patch_vocabulary(snapshot_dir: Path) -> None:
    """Fix KBLab large model vocabulary mismatch.

    KBLab/kb-whisper-large has 51866 tokens (extra <|30.00|> timestamp)
    while CTranslate2 expects exactly 51865. This causes:
      RuntimeError: [json.exception.type_error.305] cannot use operator[]
      with a string argument with null
    We trim the extra token on disk once.

    SAFETY: Mutating the HuggingFace cache in place is fragile — a `huggingface-cli
    download` (or any cache validation) will redownload the original and undo us.
    To make the patch traceable and recoverable we:
      1. Save the original to ``vocabulary.json.orig`` before overwriting.
      2. Drop a ``.freewispr-patched`` marker so we don't repeatedly log/patch.
      3. Loudly recommend the user run ``python convert_model.py large`` for a
         proper fix (writes a clean ct2 model next to the HF cache).
    """
    import json
    vocab_path = snapshot_dir / "vocabulary.json"
    marker = snapshot_dir / ".freewispr-patched"
    if not vocab_path.exists():
        return
    if marker.exists():
        return  # already patched in a previous run
    try:
        with open(vocab_path, "r", encoding="utf-8") as f:
            vocab = json.load(f)
        if isinstance(vocab, list) and len(vocab) > 51865:
            log.warning(
                "vocabulary.json har %d tokens (förväntade 51865). "
                "Patchar HuggingFace-cachen på plats — kör hellre "
                "'python convert_model.py large' för en permanent lösning.",
                len(vocab),
            )
            backup = snapshot_dir / "vocabulary.json.orig"
            if not backup.exists():
                vocab_path.replace(backup)
                # vocab_path no longer exists; recreate it below.
            vocab = vocab[:51865]
            with open(vocab_path, "w", encoding="utf-8") as f:
                json.dump(vocab, f, ensure_ascii=False)
            marker.write_text("trimmed to 51865 tokens by freewispr-swedish\n",
                              encoding="utf-8")
    except Exception as e:
        log.warning("Kunde inte patcha vocabulary.json: %s", e)

# KBLab model mapping for Swedish Whisper
KBLAB_MODELS = {
    "tiny": "KBLab/kb-whisper-tiny",
    "base": "KBLab/kb-whisper-base",
    "small": "KBLab/kb-whisper-small",
    "medium": "KBLab/kb-whisper-medium",
    "large": "KBLab/kb-whisper-large",
}

# Pin specific HuggingFace revisions for reproducible downloads.
# Set to a commit SHA from the model's HF page to lock to that version.
# None = use latest (current behavior).
KBLAB_REVISIONS: dict[str, str | None] = {
    "tiny": None,
    "base": None,
    "small": None,
    "medium": None,
    "large": None,
}

# Whisper noise/placeholder tokens to strip (always, regardless of settings).
# These appear when Whisper hallucinates on silence or background noise.
_NOISE_PLACEHOLDERS = re.compile(
    r'\[BLANK_AUDIO\]'
    r'|\[SILENCE\]'
    r'|<\|nospeech\|>'
    r'|<\|endoftext\|>'
    # Music note characters
    r'|[♪♫]+'
    # Asterisk-delimited noise labels
    r'|\*(?:music|musik|noise|ljud|silence|tystnad)\*'
    # Bracketed noise labels (English & Swedish)
    r'|\[(?:'
    r'applause|applåder|background noise|bakgrundsljud|blank audio'
    r'|breathing|andning|cough|hosta|hostning|exhale|inhale'
    r'|harkling|laughter|laughing|skratt|music|musik'
    r'|noise|ljud|silence|tystnad|sigh|suckar'
    r'|sniffing|static|brus|unclear speech|otydligt tal'
    r'|unintelligible|wind|vind|wind noise'
    r')\]'
    # Same with parentheses
    r'|\((?:'
    r'applause|applåder|background noise|bakgrundsljud|blank audio'
    r'|breathing|andning|cough|hosta|hostning|exhale|inhale'
    r'|harkling|laughter|laughing|skratt|music|musik'
    r'|noise|ljud|silence|tystnad|sigh|suckar'
    r'|sniffing|static|brus|unclear speech|otydligt tal'
    r'|unintelligible|wind|vind|wind noise'
    r')\)',
    re.IGNORECASE,
)

# Pre-compiled regex patterns for _postprocess (compiled once at module load).
# Pattern (2) for repeated words is potentially O(n²) on pathological input,
# but Whisper outputs rarely exceed a few hundred words; compiling once
# avoids the per-call setup cost (~5-20 ms saved on longer paragraphs).
_RE_REPEAT_WORD = re.compile(r'\b(\w+)(\s+\1){1,}\b', re.IGNORECASE | re.UNICODE)
_RE_REPEAT_PHRASE = re.compile(r'\b((?:\w+\s+){1,3}\w+)(\s+\1)+\b', re.IGNORECASE | re.UNICODE)
_RE_SPACE_BEFORE_PUNCT = re.compile(r'\s+([.,;:!?])')
_RE_SPACE_AFTER_PUNCT = re.compile(r'([.,;:!?])([A-Za-z\u00C0-\u00F6\u00F8-\u00FF])')
_RE_REPEAT_STRONG_PUNCT = re.compile(r'([.!?]){2,}')
_RE_REPEAT_SOFT_PUNCT = re.compile(r'([,;:]){2,}')
_RE_LEADING_PUNCT = re.compile(r'^[.,;:!?\s]+')
_RE_MULTISPACE = re.compile(r'\s{2,}')

# Unicode normalization via str.translate — single C-level pass instead of
# six chained str.replace calls (5-10× faster on long strings).
_UNICODE_NORMALIZE = str.maketrans({
    "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-",
})


def _postprocess(text: str, capitalize: bool = True) -> str:
    """Clean up Whisper output for better readability.

    Handles real issues that KBLab models produce:
    - Repeated words/phrases (Whisper stutter)
    - Whitespace before punctuation
    - Multiple punctuation in a row
    - Stray leading/trailing punctuation
    - Unicode normalization (smart quotes, dashes)

    ``capitalize=False`` skips the leading-capital step — used for the AP3
    "code/terminal" profile where forced versalisering is unwanted.
    """
    if not text:
        return text

    # 1. Normalize unicode quotes and dashes (single translation table pass)
    text = text.translate(_UNICODE_NORMALIZE)

    # 2. Remove repeated words: "det det" → "det", "jag jag jag" → "jag"
    text = _RE_REPEAT_WORD.sub(r'\1', text)

    # 3. Remove repeated short phrases (2-4 words): "det var bra det var bra" → "det var bra"
    text = _RE_REPEAT_PHRASE.sub(r'\1', text)

    # 4. Fix whitespace before punctuation: "hej , du" → "hej, du"
    text = _RE_SPACE_BEFORE_PUNCT.sub(r'\1', text)

    # 5. Ensure space after punctuation (but not digits: "3.14"): "hej.du" → "hej. du"
    text = _RE_SPACE_AFTER_PUNCT.sub(r'\1 \2', text)

    # 6. Collapse multiple punctuation: "hej..." → "hej.", "hej,," → "hej,"
    text = _RE_REPEAT_STRONG_PUNCT.sub(r'\1', text)
    text = _RE_REPEAT_SOFT_PUNCT.sub(r'\1', text)

    # 7. Strip leading punctuation
    text = _RE_LEADING_PUNCT.sub('', text)

    # 8. Collapse multiple spaces
    text = _RE_MULTISPACE.sub(' ', text).strip()

    # 9. Capitalize first letter (skipped for code/terminal profile)
    if text and capitalize:
        text = text[0].upper() + text[1:]

    return text


def _check_cuda() -> bool:
    """Check if CUDA (GPU) is available. Fails fast if torch is broken."""
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def _get_device_and_compute(use_cuda: bool, compute_type_override: str = "") -> tuple:
    """
    Determine device and compute type based on CUDA setting.
    Returns (device, compute_type, cuda_used).

    ``compute_type_override`` (AP4) lets the user pin e.g. ``int8_float16`` on
    CUDA or ``int8`` on CPU. Empty string keeps the safe auto defaults.
    """
    cuda_available = _check_cuda()
    override = (compute_type_override or "").strip()

    if use_cuda and cuda_available:
        # int8_float16 (L4): faster than float16 on CUDA at negligible WER cost
        # for short dictation. Override still wins.
        return ("cuda", override or "int8_float16", True)
    elif use_cuda and not cuda_available:
        log.warning("CUDA begärt men ingen GPU hittades. Använder CPU.")
        return ("cpu", override or "int8", False)
    else:
        return ("cpu", override or "int8", False)


# Initial prompts guide Whisper toward the right language and style.
# This dramatically improves first-word accuracy and reduces hallucinations.
# Include a few natural Swedish phrases to anchor the decoder.
# AP7.5: common English tech terms to bias toward when expect_english_terms is
# on (a mitigation — KBLab is Swedish-trained, so this can't fully fix English
# acoustics, only nudge spelling/recognition).
_ENGLISH_TERMS = (
    "deploy, deploya, staging, production, pull request, commit, committa, "
    "merge, mergea, branch, rebase, backend, frontend, framework, endpoint, "
    "release, deadline, feature, bug, debugga, review, pipeline, container, "
    "Kubernetes, Docker, Python, JavaScript, TypeScript, repository"
)

_INITIAL_PROMPTS = {
    "sv": (
        "Hej, det här är en diktering på svenska."
        " Jag dikterar text med korrekt interpunktion och stavning."
        " Förra mötet gick bra, vi bestämde att träffas igen på fredag."
    ),
    "en": "Hello, this is a dictation in English.",
}


def _load_hotwords() -> str | None:
    """Build a comma-separated hotwords string for faster-whisper.

    Loaded from an optional hotwords.txt file at
    ~/.freewispr-swedish/hotwords.txt (one word or phrase per line, blank
    lines and # comments ignored). Returns None if the file is missing
    or empty.

    Note: prior versions also pulled the *correct* values from
    corrections.json. That feature was retired together with the
    correction dictionary — personal vocabulary now lives in the
    personal_context.json LLM prompt instead, which is more flexible
    and works for remote transcription providers too.
    """
    words: set[str] = set()

    if HOTWORDS_FILE.exists():
        try:
            for line in HOTWORDS_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    words.add(line)
            log.info("Laddade %d hotwords från %s", len(words), HOTWORDS_FILE)
        except Exception as e:
            log.warning("Kunde inte läsa hotwords.txt: %s", e)

    if not words:
        return None

    result = ", ".join(sorted(words))
    log.debug("Hotwords (%d st): %s", len(words), result[:200])
    return result


# In-memory hotwords cache — avoids re-reading disk on every transcription.
# Invalidated when hotwords.txt changes (checked by mtime).
_hotwords_cache: str | None = None
_hotwords_mtime: float = 0.0


def _get_hotwords_cached() -> str | None:
    """Return cached hotwords string, reloading only if hotwords.txt changed."""
    global _hotwords_cache, _hotwords_mtime

    hw_mt = HOTWORDS_FILE.stat().st_mtime if HOTWORDS_FILE.exists() else 0.0

    if hw_mt != _hotwords_mtime:
        _hotwords_cache = _load_hotwords()
        _hotwords_mtime = hw_mt
        log.debug("Hotwords-cache uppdaterad (mtime ändrad)")

    return _hotwords_cache


class Transcriber:
    def __init__(self, model_size: str = "small", language: str = "sv",
                 use_cuda: bool = True,
                 llm_enabled: bool = False, llm_api_key: str = "",
                 llm_model: str = "openai/gpt-4.1-nano",
                 llm_provider: str = "github",
                 llm_base_url: str = "",
                 transcription_provider: str = "local",
                 transcription_api_key: str = "",
                 transcription_model: str = "",
                 transcription_base_url: str = "",
                 beam_size: int = 1,
                 vad_filter: bool = True,
                 no_speech_threshold: float = 0.6,
                 compute_type: str = "",
                 kblab_revision: str = "default",
                 transcription_temperature: float = 0.0,
                 expect_english_terms: bool = False,
                 remote_audio_format: str = "wav",
                 whisper_batched: bool = False):
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        self.language = language
        self.llm_enabled = llm_enabled
        self.llm_api_key = llm_api_key
        self.llm_model = llm_model
        self.llm_provider = llm_provider
        self.llm_base_url = llm_base_url
        self.transcription_provider = transcription_provider
        self.transcription_api_key = transcription_api_key
        self.transcription_model = transcription_model
        self.transcription_base_url = transcription_base_url
        # AP4 backend-aware biasing/decoding knobs (local faster-whisper only;
        # remote OpenAI-compatible path uses temperature + prompt).
        self.beam_size = beam_size
        self.vad_filter = vad_filter
        self.no_speech_threshold = no_speech_threshold
        self.compute_type_override = compute_type
        self.kblab_revision = kblab_revision or "default"
        self.transcription_temperature = transcription_temperature
        self.expect_english_terms = expect_english_terms
        self.remote_audio_format = remote_audio_format or "wav"
        self.whisper_batched = whisper_batched
        self._batched = None
        self.on_stage = None

        # L3: keep the LLM connection warm so the first polish doesn't pay a
        # TLS handshake / provider cold-start. Only runs when LLM is enabled —
        # offline base mode (LLM off) issues no network traffic.
        self._llm_warm_stop = threading.Event()
        if llm_enabled:
            self._start_llm_warmer()
        # L5.3: warm the remote transcription connection too (only when remote).
        if transcription_provider != "local":
            self._start_transcribe_warmer()

        # When the user has opted into a remote transcription provider, the
        # local Whisper model is *not* loaded. This saves 0.5–3 GB of RAM/VRAM
        # and skips the warmup pass. There is no fallback — if the remote
        # request fails we surface the error to the user.
        self.model_size = model_size
        self._model_lock = threading.RLock()
        self.model = None
        self._warmed = False
        # Set to True after a CUDA OOM so future transcriptions fail fast with
        # a user-friendly message instead of repeatedly hitting OOM on a model
        # that's now in a broken state. Cleared only by restarting the app.
        self._cuda_oom = False

        if transcription_provider != "local":
            log.info("Remote-transkribering aktiv: provider=%s, model=%s",
                     transcription_provider, transcription_model or "(default)")
            if self.llm_enabled:
                log.info("LLM-granskning aktiverad: %s/%s",
                         self.llm_provider, self.llm_model)
            self.last_polish_state = "local"
            return

        # ---- Local Whisper path ----
        model_name = KBLAB_MODELS.get(model_size, model_size)
        model_path = _find_local_model(model_name, self.kblab_revision)
        device, compute_type, cuda_used = _get_device_and_compute(
            use_cuda, self.compute_type_override)

        # Fail-closed when the model isn't cached locally: faster-whisper would
        # otherwise silently reach out to huggingface.co. That's a privacy
        # surprise for a "local dictation" tool and an OS-dependent failure for
        # offline users. Refuse and tell the user exactly how to fix it.
        if not model_path:
            raise FileNotFoundError(
                f"Whisper-modellen '{model_size}' ({model_name}) finns inte "
                f"lokalt i {MODEL_DIR}. freewispr-swedish kontaktar inte "
                f"internet automatiskt — kör först:\n"
                f"    python convert_model.py {model_size}\n"
                f"för att ladda ned och konvertera modellen."
            )

        log.info("Laddar Whisper '%s' från lokal cache (%s)...", model_size, device)

        if cuda_used:
            log.info("GPU: NVIDIA CUDA aktiverad")

        # NOTE: Revision pinning only matters at download/convert time
        # (convert_model.py). Here local_files_only=True means we load
        # whatever snapshot is already on disk — no network request is made,
        # so the revision parameter has no effect.
        self.model = WhisperModel(
            model_path,
            device=device,
            compute_type=compute_type,
            download_root=str(MODEL_DIR),
            local_files_only=True,  # belt-and-braces: never hit the network
        )
        log.info("Whisper '%s' (%s) laddad OK [%s, %s]",
                 model_size, model_name, device, compute_type)

        # L5.8 (opt-in, experimental): wrap the model in a BatchedInferencePipeline
        # for parallel chunk decoding on *longer* clips. Guarded so a missing
        # class / old faster-whisper simply keeps the normal path.
        self._batched = None
        if getattr(self, "whisper_batched", False):
            try:
                from faster_whisper import BatchedInferencePipeline
                self._batched = BatchedInferencePipeline(model=self.model)
                log.info("BatchedInferencePipeline aktiverad (experimentellt)")
            except Exception as e:
                log.info("BatchedInferencePipeline ej tillgänglig: %s", e)

        if self.llm_enabled:
            log.info("LLM-granskning aktiverad: %s/%s",
                     self.llm_provider, self.llm_model)

        self.last_polish_state = "local"

        # Warm up CTranslate2 kernels / CUDA workspaces on a background thread.
        # faster-whisper allocates these lazily on the first real transcribe()
        # call, which adds 300-800 ms to the user's first hotkey press.
        # Running a silent inference here eats that cost while the tray is
        # still loading.
        threading.Thread(target=self._warmup, name="whisper-warmup",
                         daemon=True).start()

    def _start_llm_warmer(self) -> None:
        """Warm the LLM connection now + periodically (L3)."""
        def _loop():
            from llm_polish import warm
            kw = dict(model=self.llm_model, provider=self.llm_provider,
                      base_url_override=self.llm_base_url)
            warm(self.llm_api_key, **kw)
            while not self._llm_warm_stop.wait(_LLM_WARM_INTERVAL):
                warm(self.llm_api_key, **kw)
        threading.Thread(target=_loop, name="llm-warm", daemon=True).start()

    def _start_transcribe_warmer(self) -> None:
        """Warm the remote transcription connection now + periodically (L5.3)."""
        def _loop():
            import remote_transcribe as rt
            kw = dict(api_key=self.transcription_api_key,
                      base_url_override=self.transcription_base_url)
            rt.warm(self.transcription_provider, **kw)
            while not self._llm_warm_stop.wait(_LLM_WARM_INTERVAL):
                rt.warm(self.transcription_provider, **kw)
        threading.Thread(target=_loop, name="tr-warm", daemon=True).start()

    def _warmup(self) -> None:
        """Run a single silent inference to pre-allocate inference state."""
        try:
            import time as _time
            t0 = _time.monotonic()
            silent = np.zeros(16000, dtype=np.float32)  # 1 s of silence
            with self._model_lock:
                model = self.model
                if model is None:
                    return
                segments, _info = model.transcribe(
                    silent,
                    language=self.language,
                    beam_size=1,
                    best_of=1,
                    vad_filter=False,
                    without_timestamps=True,
                    condition_on_previous_text=False,
                )
                # Force the lazy generator to actually run the decoder while
                # holding the lock; faster-whisper is lazy here.
                for _ in segments:
                    pass
            self._warmed = True
            log.info("Whisper-warmup klar på %.0f ms", (_time.monotonic() - t0) * 1000)
        except Exception as e:
            log.debug("Whisper-warmup misslyckades (ignoreras): %s", e)

    def close(self) -> None:
        """Release the underlying WhisperModel to free VRAM/RAM.

        Also stops the LLM warm-keeper thread (L3).

        Important on model reload: keeping two WhisperModels alive briefly
        can pin 2-3 GB of VRAM and OOM smaller CUDA devices.
        """
        import gc
        warm_stop = getattr(self, "_llm_warm_stop", None)
        if warm_stop is not None:
            warm_stop.set()
        try:
            with self._model_lock:
                model = getattr(self, "model", None)
                if model is None:
                    return
                self.model = None  # type: ignore[assignment]
                del model
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
        except Exception as e:
            log.debug("Kunde inte frigöra modell rent: %s", e)

    def transcribe(self, audio: np.ndarray, capitalize: bool = True,
                   extra_hotwords: str = "") -> str:
        """Transcribe audio to text (local or remote) with postprocessing.

        Does NOT run LLM polish — use :meth:`polish_async` for that.
        Sets ``last_polish_state`` to ``"local"`` unconditionally.

        ``capitalize`` / ``extra_hotwords`` come from AP3 context awareness:
        the active app profile may disable leading-capitalisation, and on-screen
        proper nouns are added to the local decoder's hotwords.
        """
        self.last_polish_state = "local"
        log.info("Transkriberar: %d samples, peak=%.4f, modell=%s, lang=%s, provider=%s",
                 len(audio), max(abs(float(audio.min())), abs(float(audio.max()))) if audio.size else 0.0,
                 self.model_size, self.language, self.transcription_provider)

        if self.transcription_provider != "local":
            text = self._transcribe_remote(audio, capitalize=capitalize,
                                           extra_prompt=extra_hotwords)
        else:
            text = self._transcribe_local(audio, capitalize=capitalize,
                                          extra_hotwords=extra_hotwords)

        return text

    def polish_async(self, text: str,
                     callback: Callable[[str, str], None],
                     on_stage: Callable[[str], None] | None = None,
                     app_profile: str = "",
                     onscreen_names: str = "") -> None:
        """Run LLM polish in a background thread.

        When finished, calls ``callback(original_text, polished_text)``
        from the background thread.  If polish fails or text is unchanged
        the callback receives ``(text, text)``.

        Updates ``self.last_polish_state`` to reflect the outcome.

        ``on_stage`` is fired with ``"llm_reviewing"`` immediately. Prefer
        passing it as a parameter rather than mutating ``self.on_stage`` —
        per-job callbacks avoid a race when two jobs overlap (the older
        job's polish completion would otherwise overwrite the newer job's
        callback on the shared attribute). The ``self.on_stage`` fallback
        is kept for legacy callers and remote transcription.
        """
        self.last_polish_state = "llm_reviewing"
        if on_stage is None:
            on_stage = getattr(self, "on_stage", None)
        if on_stage is not None:
            try:
                on_stage("llm_reviewing")
            except Exception:
                pass

        def _run():
            import time as _time
            from llm_polish import polish

            # Track whether we've delivered exactly one callback. ``polish()``
            # has its own 8 s urllib timeout, but we also belt-and-braces:
            # log slow runs and guarantee the caller's callback fires even if
            # *it* raises — otherwise the indicator stays on "LLM-granskar…"
            # forever.
            t0 = _time.monotonic()
            delivered = False

            def _deliver(original: str, polished: str) -> None:
                nonlocal delivered
                if delivered:
                    return
                delivered = True
                try:
                    callback(original, polished)
                except Exception as cb_err:
                    # Swallow — we're in a daemon thread; if we let this
                    # propagate, the indicator stays stuck because no other
                    # code is going to clear it.
                    log.error("LLM-polish callback kraschade: %s",
                              cb_err, exc_info=True)

            try:
                try:
                    # Load personal context fresh every call. JsonCache uses
                    # mtime-based invalidation internally so this is cheap
                    # when nothing has changed, and picks up Settings saves
                    # immediately without restarting dictation.
                    try:
                        from personal_context import load as _load_context
                        ctx = _load_context()
                    except Exception as ctx_err:
                        log.debug("Kunde inte ladda personlig kontext: %s", ctx_err)
                        ctx = ""

                    # Learned corrections (AP2) — injected as reference so the
                    # model applies known fixes/names. Cheap mtime-cached read.
                    try:
                        from learning import load_corrections
                        corrections = load_corrections()
                    except Exception as corr_err:
                        log.debug("Kunde inte ladda rättelser: %s", corr_err)
                        corrections = {}

                    result = polish(
                        text,
                        self.llm_api_key,
                        model=self.llm_model,
                        provider=self.llm_provider,
                        base_url_override=self.llm_base_url,
                        context_text=ctx,
                        corrections=corrections,
                        app_profile=app_profile,
                        onscreen_names=onscreen_names,
                        expect_english_terms=getattr(
                            self, "expect_english_terms", False),
                    )
                except Exception as e:
                    log.warning("LLM-polish kraschade: %s", e, exc_info=True)
                    self.last_polish_state = "local"
                    _deliver(text, text)
                    return

                # Stash polish telemetry for the latency log (L0/L2/L3).
                self.last_polish_first_token_ms = getattr(result, "first_token_ms", 0.0)
                self.last_polish_conn_ms = getattr(result, "conn_ms", 0.0)
                self.last_polish_conn_reused = getattr(result, "conn_reused", None)

                elapsed = _time.monotonic() - t0
                if elapsed > 10.0:
                    # polish() should have timed out at 8 s; anything past
                    # ~10 s suggests the timeout was ignored (DNS hang, etc.).
                    log.warning(
                        "LLM-polish tog %.1f s (förväntat <8 s) — "
                        "nätverkshicka eller långsam leverantör?", elapsed,
                    )

                if result.changed:
                    self.last_polish_state = "llm_changed"
                    log.info("Resultat (LLM) klart (%dms, %s)",
                             result.latency_ms, _text_meta(result.text))
                    _deliver(text, result.text)
                else:
                    self.last_polish_state = "llm_unchanged"
                    _deliver(text, text)
            finally:
                # Last-resort safety net: if anything above slips through
                # without delivering (e.g. BaseException, MemoryError),
                # still fire the callback so the UI doesn't hang.
                if not delivered:
                    log.error("LLM-polish trådade ut utan callback — "
                              "levererar fallback")
                    self.last_polish_state = "local"
                    _deliver(text, text)

        threading.Thread(target=_run, name="llm-polish", daemon=True).start()

    def _transcribe_local(self, audio: np.ndarray, capitalize: bool = True,
                          extra_hotwords: str = "") -> str:
        prompt = _INITIAL_PROMPTS.get(self.language, "")
        hotwords = _get_hotwords_cached()
        # Merge AP3 on-screen proper nouns into the decoder hotwords.
        if extra_hotwords:
            hotwords = f"{hotwords}, {extra_hotwords}" if hotwords else extra_hotwords
        # AP7.5: bias toward common English tech terms when opted in.
        if getattr(self, "expect_english_terms", False):
            hotwords = f"{hotwords}, {_ENGLISH_TERMS}" if hotwords else _ENGLISH_TERMS

        if getattr(self, "_cuda_oom", False):
            # We already hit OOM in this session; refuse fast with the same
            # message instead of re-tripping it on every subsequent press.
            raise RuntimeError(
                "GPU-minne slut — appen växlar till CPU. "
                "Starta om för att försöka igen."
            )

        # AP4: configurable decoding/biasing (read via getattr so object.__new__
        # test instances without these attributes keep the safe defaults).
        beam_size = getattr(self, "beam_size", 1)
        no_speech_threshold = getattr(self, "no_speech_threshold", 0.6)
        vad_enabled = getattr(self, "vad_filter", True)
        # When VAD is on, try it first then fall back to no-VAD on error; when
        # off, only run the plain pass.
        vad_attempts = (True, False) if vad_enabled else (False,)

        raw = ""
        # segments is a lazy generator, so the error surfaces during
        # iteration, not at the transcribe() call itself.
        # L5.8 (opt-in): route *longer* clips (>20 s) through the batched
        # pipeline first. Fully isolated + fallback-safe — any failure (or an
        # empty result) drops to the normal decode loop below.
        batched = getattr(self, "_batched", None)
        if batched is not None and audio.size > 16000 * 20:
            try:
                with self._model_lock:
                    segments, _info = batched.transcribe(
                        audio, language=self.language, beam_size=beam_size,
                        vad_filter=vad_enabled, temperature=0.0)
                    raw = " ".join(s.text.strip() for s in segments)
                if raw.strip():
                    log.info("Batched decode klar (%s)", _text_meta(raw))
            except Exception as e:
                log.warning("Batched decode misslyckades — normal path: %s", e)
                raw = ""

        for use_vad in (() if raw.strip() else vad_attempts):
            try:
                with self._model_lock:
                    model = self.model
                    if model is None:
                        raise RuntimeError("Whisper-modellen är stängd")
                    segments, info = model.transcribe(
                        audio,
                        language=self.language,
                        # Greedy decoding (beam_size=1) — ~2× faster than beam_size=5
                        # with negligible WER difference on short dictation utterances.
                        beam_size=beam_size,
                        best_of=1,
                        vad_filter=use_vad,
                        # 500 ms keeps legitimate natural pauses intact;
                        # 300 ms was cutting words off.
                        vad_parameters={"min_silence_duration_ms": 500} if use_vad else None,
                        initial_prompt=prompt or None,
                        condition_on_previous_text=False,
                        without_timestamps=True,
                        # L5.1: pin a *scalar* temperature so faster-whisper
                        # never escalates through its (0.0, 0.2, …, 1.0)
                        # fallback (up to 6 decode passes) on hard audio.
                        temperature=0.0,
                        # Drop segments the model is confident are silence —
                        # reduces hallucination on quiet/noisy audio.
                        no_speech_threshold=no_speech_threshold,
                        # Decoder optimizations — zero latency cost:
                        # Mild penalty on repeated tokens (prevents "det det det")
                        repetition_penalty=1.1,
                        # Forbid repeating 3-word sequences exactly
                        no_repeat_ngram_size=3,
                        # Bias toward user's vocabulary (names, terms)
                        hotwords=hotwords,
                    )
                    raw = " ".join(s.text.strip() for s in segments)
                # L4/L5.1: log the effective decode knobs so the VAD on/off
                # delta is visible; decode_passes=1 thanks to scalar temperature.
                log.info("Lokal decode: vad=%s, beam=%d, no_speech=%.2f, "
                         "decode_passes=1", use_vad, beam_size, no_speech_threshold)
                # L5.5: only fall through to the no-VAD pass when the VAD pass
                # produced *nothing* (VAD over-trimmed real speech). A non-empty
                # result — or the no-VAD pass itself — ends the loop.
                if raw.strip() or not use_vad:
                    break
                log.info("VAD-passet gav tomt — försöker en gång utan VAD")
            except RuntimeError as e:
                msg = str(e).lower()

                # CUDA out-of-memory: the model is now in a poisoned state.
                # Retrying with the same model (even without VAD) will just
                # re-trip OOM. Empty the cache, set a sticky flag so future
                # transcriptions fail fast, and surface a friendly message.
                if "out of memory" in msg or (
                    "cuda" in msg and ("memory" in msg or "oom" in msg)
                ):
                    log.error("CUDA out-of-memory under transkribering: %s", e)
                    try:
                        import torch
                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()
                    except Exception as cache_err:
                        log.debug("torch.cuda.empty_cache() misslyckades: %s",
                                  cache_err)
                    self._cuda_oom = True
                    raise RuntimeError(
                        "GPU-minne slut — appen växlar till CPU. "
                        "Starta om för att försöka igen."
                    ) from e

                # Corrupt model file (vocabulary / tokenizer / JSON parse
                # errors). VAD retry won't help — the model itself is broken.
                if (
                    "vocabulary" in msg
                    or "tokenizer" in msg
                    or "json.exception" in msg
                ):
                    log.error("Modellfilen verkar korrupt: %s", e)
                    raise RuntimeError(
                        "Modellen verkar korrupt — kör "
                        "'python convert_model.py <size>' eller välj en annan "
                        "storlek i Inställningar."
                    ) from e

                if use_vad:
                    log.warning("VAD-transkribering kraschade: %s — försöker utan VAD", e)
                    continue
                raise

        log.info("Rå text mottagen (%s)", _text_meta(raw))
        # Strip noise/placeholder tokens. _postprocess handles whitespace
        # collapsing further down — no need to do it twice.
        text = _NOISE_PLACEHOLDERS.sub("", raw)
        text = _postprocess(text, capitalize=capitalize)
        log.info("Resultat (lokal) klart (%s)", _text_meta(text))
        return text

    def _transcribe_remote(self, audio: np.ndarray, capitalize: bool = True,
                           extra_prompt: str = "") -> str:
        """Skicka ljud till remote-leverantör.

        Inget fallback till lokal modell — vid fel loggas det och tom sträng
        returneras. Dictation-pipelinen klistrar inte in tom text, så
        användaren ser bara en felsignal i indikatorn (via on_status).
        """
        import remote_transcribe as rt

        on_stage = getattr(self, "on_stage", None)
        if on_stage is not None:
            try:
                on_stage("remote_transcribing")
            except Exception:
                pass

        # AP4: bias the remote OpenAI-compatible decoder with a prompt built
        # from the language anchor + hotwords + on-screen names. Providers that
        # ignore `prompt` simply no-op on it.
        bias_parts = [
            _INITIAL_PROMPTS.get(self.language, ""),
            _get_hotwords_cached() or "",
            extra_prompt or "",
            _ENGLISH_TERMS if getattr(self, "expect_english_terms", False) else "",
        ]
        prompt = " ".join(p for p in bias_parts if p).strip()
        temperature = getattr(self, "transcription_temperature", 0.0)

        try:
            raw = rt.transcribe(
                audio,
                sample_rate=16000,
                provider=self.transcription_provider,
                api_key=self.transcription_api_key,
                model=self.transcription_model,
                language=self.language,
                base_url_override=self.transcription_base_url,
                prompt=prompt,
                temperature=temperature,
                audio_format=getattr(self, "remote_audio_format", "wav"),
            )
        except rt.RemoteTranscribeError as e:
            log.warning("Remote-transkribering misslyckades: %s", e)
            if on_stage is not None:
                try:
                    on_stage("remote_error")
                except Exception:
                    pass
            return ""

        # Surface keep-alive connection telemetry for the latency log (L2).
        try:
            from http_pool import last_stats
            st = last_stats()
            self.last_transcribe_conn_ms = st.get("conn_ms", 0.0)
            self.last_transcribe_conn_reused = st.get("conn_reused")
        except Exception:
            pass

        log.info("Rå text mottagen (%s)", _text_meta(raw))
        text = _NOISE_PLACEHOLDERS.sub("", raw)
        text = _postprocess(text, capitalize=capitalize)
        log.info("Resultat (remote) klart (%s)", _text_meta(text))
        return text
