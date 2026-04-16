import re
import logging
from pathlib import Path
import numpy as np
from faster_whisper import WhisperModel

import corrections as corr_module

log = logging.getLogger("freewispr")

CONFIG_DIR = Path.home() / ".freewispr-swedish"
MODEL_DIR = CONFIG_DIR / "models"
HOTWORDS_FILE = CONFIG_DIR / "hotwords.txt"


def _find_local_model(repo_name: str) -> str | None:
    """Return local snapshot path if the model is already downloaded.

    Checks two locations in order:
      1. Manually converted CTranslate2 model:
         MODEL_DIR/kb-whisper-{size}-ct2/model.bin
         These are converted via ctranslate2.converters.TransformersConverter
         and are known to work correctly (no vocabulary mismatch issues).
      2. HuggingFace snapshot:
         MODEL_DIR/models--<org>--<name>/snapshots/<hash>/model.bin
         These may need vocabulary patching for large/medium models.
    """
    # 1. Check for manually converted ct2 model first
    # repo_name is e.g. "KBLab/kb-whisper-large" → extract "kb-whisper-large"
    short_name = repo_name.split("/")[-1] if "/" in repo_name else repo_name
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
    """
    import json
    vocab_path = snapshot_dir / "vocabulary.json"
    if not vocab_path.exists():
        return
    try:
        with open(vocab_path, "r", encoding="utf-8") as f:
            vocab = json.load(f)
        if isinstance(vocab, list) and len(vocab) > 51865:
            log.info("Patchar vocabulary.json: %d → 51865 tokens", len(vocab))
            vocab = vocab[:51865]
            with open(vocab_path, "w", encoding="utf-8") as f:
                json.dump(vocab, f, ensure_ascii=False)
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

# Whisper noise/placeholder tokens to strip (always, regardless of settings).
# These appear when Whisper hallucinates on silence or background noise.
_NOISE_PLACEHOLDERS = re.compile(
    r'\[BLANK_AUDIO\]'
    r'|\[SILENCE\]'
    r'|<\|nospeech\|>'
    r'|<\|endoftext\|>'
    # Bracketed noise labels (English & Swedish)
    r'|\[(?:'
    r'applause|applåder|background noise|bakgrundsljud|blank audio'
    r'|breathing|andning|cough|hosta|exhale|inhale'
    r'|laughter|laughing|skratt|music|musik'
    r'|noise|ljud|silence|tystnad|sigh|suckar'
    r'|sniffing|static|brus|unclear speech|otydligt tal'
    r'|unintelligible|wind|vind|wind noise'
    r')\]'
    # Same with parentheses
    r'|\((?:'
    r'applause|applåder|background noise|bakgrundsljud|blank audio'
    r'|breathing|andning|cough|hosta|exhale|inhale'
    r'|laughter|laughing|skratt|music|musik'
    r'|noise|ljud|silence|tystnad|sigh|suckar'
    r'|sniffing|static|brus|unclear speech|otydligt tal'
    r'|unintelligible|wind|vind|wind noise'
    r')\)',
    re.IGNORECASE,
)

def _postprocess(text: str) -> str:
    """Clean up Whisper output for better readability.

    Handles real issues that KBLab models produce:
    - Repeated words/phrases (Whisper stutter)
    - Whitespace before punctuation
    - Multiple punctuation in a row
    - Stray leading/trailing punctuation
    - Unicode normalization (smart quotes, dashes)
    """
    if not text:
        return text

    # 1. Normalize unicode quotes and dashes to standard forms
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")

    # 2. Remove repeated words: "det det" → "det", "jag jag jag" → "jag"
    text = re.sub(r'\b(\w+)(\s+\1){1,}\b', r'\1', text, flags=re.IGNORECASE | re.UNICODE)

    # 3. Remove repeated short phrases (2-4 words): "det var bra det var bra" → "det var bra"
    text = re.sub(
        r'\b((?:\w+\s+){1,3}\w+)(\s+\1)+\b',
        r'\1',
        text,
        flags=re.IGNORECASE | re.UNICODE,
    )

    # 4. Fix whitespace before punctuation: "hej , du" → "hej, du"
    text = re.sub(r'\s+([.,;:!?])', r'\1', text)

    # 5. Ensure space after punctuation (but not digits: "3.14"): "hej.du" → "hej. du"
    text = re.sub(r'([.,;:!?])([A-Za-z\u00C0-\u00F6\u00F8-\u00FF])', r'\1 \2', text)

    # 6. Collapse multiple punctuation: "hej..." → "hej.", "hej,," → "hej,"
    text = re.sub(r'([.!?]){2,}', r'\1', text)
    text = re.sub(r'([,;:]){2,}', r'\1', text)

    # 7. Strip leading punctuation
    text = re.sub(r'^[.,;:!?\s]+', '', text)

    # 8. Collapse multiple spaces
    text = re.sub(r'\s{2,}', ' ', text).strip()

    # 9. Capitalize first letter
    if text:
        text = text[0].upper() + text[1:]

    return text


def _check_cuda() -> bool:
    """Check if CUDA (GPU) is available. Fails fast if torch is broken."""
    try:
        import importlib
        spec = importlib.util.find_spec("torch")
        if spec is None:
            return False
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def _get_device_and_compute(use_cuda: bool) -> tuple:
    """
    Determine device and compute type based on CUDA setting.
    Returns (device, compute_type, cuda_used).
    """
    cuda_available = _check_cuda()
    
    if use_cuda and cuda_available:
        return ("cuda", "float16", True)
    elif use_cuda and not cuda_available:
        log.warning("CUDA begärt men ingen GPU hittades. Använder CPU.")
        return ("cpu", "int8", False)
    else:
        return ("cpu", "int8", False)


# Initial prompts guide Whisper toward the right language and style.
# This dramatically improves first-word accuracy and reduces hallucinations.
# Include a few natural Swedish phrases to anchor the decoder.
_INITIAL_PROMPTS = {
    "sv": (
        "Hej, det här är en diktering på svenska."
        " Jag dikterar text med korrekt interpunktion och stavning."
    ),
    "en": "Hello, this is a dictation in English.",
}


def _load_hotwords() -> str | None:
    """Build a comma-separated hotwords string for faster-whisper.

    Sources (combined, deduplicated):
      1. The *correct* values from the personal corrections dictionary.
         These are proper nouns, names, and terms the user cares about.
      2. An optional hotwords.txt file at ~/.freewispr-swedish/hotwords.txt
         (one word or phrase per line, blank lines and # comments ignored).

    Returns None if no hotwords are available.
    """
    words: set[str] = set()

    # 1. Correction dictionary → the "right" (target) values
    try:
        for _wrong, right in corr_module.load().items():
            term = right.strip()
            if term:
                words.add(term)
    except Exception as e:
        log.debug("Kunde inte läsa ordlista för hotwords: %s", e)

    # 2. hotwords.txt (optional)
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
# Invalidated when corrections.json or hotwords.txt change (checked by mtime).
_hotwords_cache: str | None = None
_hotwords_mtime: tuple[float, float] = (0.0, 0.0)  # (corrections_mtime, hotwords_mtime)


def _get_hotwords_cached() -> str | None:
    """Return cached hotwords string, reloading only if source files changed."""
    global _hotwords_cache, _hotwords_mtime

    corr_mt = corr_module._FILE.stat().st_mtime if corr_module._FILE.exists() else 0.0
    hw_mt = HOTWORDS_FILE.stat().st_mtime if HOTWORDS_FILE.exists() else 0.0
    current = (corr_mt, hw_mt)

    if current != _hotwords_mtime:
        _hotwords_cache = _load_hotwords()
        _hotwords_mtime = current
        log.debug("Hotwords-cache uppdaterad (mtime ändrad)")

    return _hotwords_cache


class Transcriber:
    def __init__(self, model_size: str = "small", language: str = "sv",
                 use_cuda: bool = True,
                 llm_enabled: bool = False, llm_api_key: str = "",
                 llm_model: str = "gpt-4.1-nano"):
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        self.language = language
        self.llm_enabled = llm_enabled
        self.llm_api_key = llm_api_key
        self.llm_model = llm_model
        
        # Get the KBLab model name
        model_name = KBLAB_MODELS.get(model_size, model_size)
        
        # Use local snapshot if already downloaded — avoids network check
        model_path = _find_local_model(model_name)
        
        # Determine device and compute type
        device, compute_type, cuda_used = _get_device_and_compute(use_cuda)
        
        if model_path:
            log.info("Laddar Whisper '%s' från lokal cache (%s)...", model_size, device)
        else:
            log.info("Laddar ned Whisper '%s' (%s) (%s)...", model_size, model_name, device)
            model_path = model_name  # Download from HuggingFace
        
        if cuda_used:
            log.info("GPU: NVIDIA CUDA aktiverad")
        
        self.model_size = model_size
        self.model = WhisperModel(
            model_path,
            device=device,
            compute_type=compute_type,
            download_root=str(MODEL_DIR),
        )
        log.info("Whisper '%s' (%s) laddad OK [%s, %s]", model_size, model_name, device, compute_type)
        if self.llm_enabled and self.llm_api_key:
            log.info("LLM-granskning aktiverad: %s", self.llm_model)

    def transcribe(self, audio: np.ndarray) -> str:
        log.info("Transkriberar: %d samples, peak=%.4f, modell=%s, lang=%s",
                 len(audio), np.abs(audio).max(), self.model_size, self.language)

        prompt = _INITIAL_PROMPTS.get(self.language, "")
        hotwords = _get_hotwords_cached()

        # Try with VAD first, fall back to without on error.
        # segments is a lazy generator, so the error surfaces during
        # iteration, not at the transcribe() call itself.
        for use_vad in [True, False]:
            try:
                segments, info = self.model.transcribe(
                    audio,
                    language=self.language,
                    beam_size=5,
                    best_of=1,
                    vad_filter=use_vad,
                    vad_parameters={"min_silence_duration_ms": 300} if use_vad else None,
                    initial_prompt=prompt or None,
                    condition_on_previous_text=False,
                    without_timestamps=True,
                    # Decoder optimizations — zero latency cost:
                    # Mild penalty on repeated tokens (prevents "det det det")
                    repetition_penalty=1.1,
                    # Forbid repeating 3-word sequences exactly
                    no_repeat_ngram_size=3,
                    # Bias toward user's vocabulary (names, terms)
                    hotwords=hotwords,
                )
                raw_texts = []
                for s in segments:
                    raw_texts.append(s.text.strip())
                raw = " ".join(raw_texts)
                break
            except RuntimeError as e:
                if use_vad:
                    log.warning("VAD-transkribering kraschade: %s — försöker utan VAD", e)
                    continue
                raise

        log.info("Rå text: '%s'", raw)
        # Strip noise/placeholder tokens, then post-process
        text = _NOISE_PLACEHOLDERS.sub("", raw)
        text = re.sub(r"\s{2,}", " ", text).strip()
        text = corr_module.apply(text)
        text = _postprocess(text)
        log.info("Resultat (lokal): '%s'", text)

        # LLM polishing — optional, never blocks on failure
        if self.llm_enabled and self.llm_api_key and text:
            from llm_polish import polish
            from auto_learn import record_correction

            result = polish(text, self.llm_api_key, self.llm_model)
            if result.changed:
                # Feed the before/after to auto-learning
                record_correction(text, result.text)
                text = result.text
                log.info("Resultat (LLM, %dms): '%s'", result.latency_ms, text)

        return text
