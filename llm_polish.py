"""
LLM text polishing — post-process Whisper output via en valbar OpenAI-kompatibel
leverantör.

Inbyggda leverantörer:

- ``github`` — GitHub Models (`models.github.ai/inference`). Token från sparad
  nyckel, ``GITHUB_TOKEN``/``GH_TOKEN`` eller ``gh auth token``.
- ``staik``  — staik.se (`api.staik.se/v1`). Nyckel ``sk-st-...``.
- ``berget`` — berget.ai (`api.berget.ai/v1`). Svenskt företag (grundat 2024)
  som hostar öppna modeller på datacenter i Sverige.
- ``openai`` — OpenAI (`api.openai.com/v1`).
- ``custom`` — användardefinierad ``base_url`` för valfri OpenAI-kompatibel
  server (lokal llama.cpp, Groq, OpenRouter, Together, Mistral, m.fl.).

LLM:n korrigerar transkriptionsartefakter (felhörda ord, grammatik, interpunktion)
UTAN att ändra fakta, namn, siffror eller meningens betydelse.
"""
from __future__ import annotations

import http.client
import io
import json
import logging
import os
import subprocess
import threading
import urllib.error
import urllib.request
from typing import NamedTuple
from urllib.parse import urlsplit

log = logging.getLogger("freewispr")


# --------------------------------------------------------------------------- #
#  Provider registry
# --------------------------------------------------------------------------- #

class _Provider(NamedTuple):
    label: str
    base_url: str            # Utan trailing slash. Tomt för ``custom``.
    api_version: str         # GitHub Models kräver header; övriga lämnar tomt.
    accept: str
    default_model: str
    fallback_models: dict[str, str]
    aliases: dict[str, str]
    key_env_vars: tuple[str, ...]
    use_gh_cli: bool         # Fallback till `gh auth token` när env saknas.
    user_configurable_url: bool  # ``custom`` läser base_url från config.


PROVIDERS: dict[str, _Provider] = {
    "github": _Provider(
        label="GitHub Models",
        base_url="https://models.github.ai/inference",
        api_version="2026-03-10",
        accept="application/vnd.github+json",
        default_model="openai/gpt-4.1-nano",
        fallback_models={
            "openai/gpt-4.1-nano": "GPT-4.1 Nano — snabbast (~1s)",
            "openai/gpt-4.1-mini": "GPT-4.1 Mini — bra balans (~1.3s)",
            "openai/gpt-4.1":      "GPT-4.1 — högre kvalitet",
            "openai/gpt-4o-mini":  "GPT-4o Mini — snabb",
            "openai/gpt-4o":       "GPT-4o — hög kvalitet",
        },
        aliases={
            "gpt-4.1-nano": "openai/gpt-4.1-nano",
            "gpt-4.1-mini": "openai/gpt-4.1-mini",
            "gpt-4.1":      "openai/gpt-4.1",
            "gpt-4o-mini":  "openai/gpt-4o-mini",
            "gpt-4o":       "openai/gpt-4o",
        },
        key_env_vars=("GITHUB_TOKEN", "GH_TOKEN"),
        use_gh_cli=True,
        user_configurable_url=False,
    ),
    "staik": _Provider(
        label="staik.se (SE)",
        base_url="https://api.staik.se/v1",
        api_version="",
        accept="application/json",
        default_model="gemma4:31b",
        fallback_models={
            "gemma4:31b":      "Gemma 4 31B — stor kontext, vision",
            "qwen3.6:35b-a3b": "Qwen 3.6 35B MoE — snabb per token",
            "qwen3.5:9b":      "Qwen 3.5 9B — minst, snabbast",
        },
        aliases={},
        key_env_vars=("STAIK_API_KEY",),
        use_gh_cli=False,
        user_configurable_url=False,
    ),
    "berget": _Provider(
        label="Berget AI (SE)",
        base_url="https://api.berget.ai/v1",
        api_version="",
        accept="application/json",
        default_model="mistralai/Mistral-Small-3.2-24B-Instruct-2506",
        fallback_models={
            "mistralai/Mistral-Small-3.2-24B-Instruct-2506":
                "Mistral Small 24B — bra balans (multimodal)",
            "meta-llama/Llama-3.1-8B-Instruct":
                "Llama 3.1 8B — snabb, billig",
            "meta-llama/Llama-3.3-70B-Instruct":
                "Llama 3.3 70B — högre kvalitet",
            "openai/gpt-oss-120b":
                "GPT-OSS 120B — stor öppen modell",
            "zai-org/GLM-4.7-FP8":
                "GLM 4.7 — 200k kontext",
        },
        aliases={},
        key_env_vars=("BERGET_API_KEY",),
        use_gh_cli=False,
        user_configurable_url=False,
    ),
    "openai": _Provider(
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        api_version="",
        accept="application/json",
        default_model="gpt-4.1-nano",
        fallback_models={
            "gpt-4.1-nano": "GPT-4.1 Nano — snabbast",
            "gpt-4.1-mini": "GPT-4.1 Mini — bra balans",
            "gpt-4.1":      "GPT-4.1 — högre kvalitet",
            "gpt-4o-mini":  "GPT-4o Mini",
            "gpt-4o":       "GPT-4o",
        },
        aliases={},
        key_env_vars=("OPENAI_API_KEY",),
        use_gh_cli=False,
        user_configurable_url=False,
    ),
    "custom": _Provider(
        label="Custom (OpenAI-kompatibel)",
        base_url="",   # användaren anger i config
        api_version="",
        accept="application/json",
        default_model="",
        fallback_models={},
        aliases={},
        key_env_vars=("LLM_API_KEY",),
        use_gh_cli=False,
        user_configurable_url=True,
    ),
}

DEFAULT_PROVIDER = "github"


def provider_labels() -> dict[str, str]:
    """Mapping ``id -> visningsnamn`` för Settings-UI."""
    return {pid: p.label for pid, p in PROVIDERS.items()}


def provider_default_model(provider: str) -> str:
    return _get_provider(provider).default_model


def is_user_configurable_url(provider: str) -> bool:
    return _get_provider(provider).user_configurable_url


def _get_provider(provider: str) -> _Provider:
    return PROVIDERS.get(provider or DEFAULT_PROVIDER, PROVIDERS[DEFAULT_PROVIDER])


def _resolve_base_url(provider: str, base_url_override: str = "") -> str:
    p = _get_provider(provider)
    url = (base_url_override or p.base_url or "").strip().rstrip("/")
    if not url:
        return url
    # LLM endpoints are commonly pointed at local Ollama / LM Studio over
    # plaintext loopback. Accept that, reject everything else non-HTTPS.
    from url_security import validate_base_url
    ok, msg = validate_base_url(url, allow_plaintext_loopback=True)
    if not ok:
        raise ValueError(msg)
    return url


def normalize_model(model: str = "", provider: str = DEFAULT_PROVIDER) -> str:
    p = _get_provider(provider)
    name = (model or p.default_model).strip()
    return p.aliases.get(name, name)


# --------------------------------------------------------------------------- #
#  Nyckelhantering
# --------------------------------------------------------------------------- #

def resolve_api_key(api_key: str = "", provider: str = DEFAULT_PROVIDER) -> str:
    """Returnera nyckeln användaren angett, eller fall tillbaka på miljö/CLI.

    För ``github`` används samma fallback-kedja som tidigare så att samma
    maskin-token som ``opencode``/``gh`` använder återanvänds automatiskt.
    Övriga providers läser bara explicit nyckel + dokumenterad miljövariabel.
    """
    explicit = (api_key or "").strip()
    if explicit:
        return explicit
    p = _get_provider(provider)
    for name in p.key_env_vars:
        token = os.environ.get(name, "").strip()
        if token:
            return token
    if p.use_gh_cli:
        try:
            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                timeout=3.0,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
    return ""


# --------------------------------------------------------------------------- #
#  HTTP
# --------------------------------------------------------------------------- #

# System prompt: the model is a *språkstädare* (language tidier), not an author.
# KBLab Whisper already removes most filler, so the job is resolving
# self-corrections, untangling run-on speech, applying known fixes/names, and
# light formatting — never adding content or changing meaning. The few-shot
# block anchors the four behaviours the spec calls out.
_SYSTEM_PROMPT = (
    "Du är en svensk språkstädare för dikterad text (tal-till-text), inte en "
    "författare. Ändra ALDRIG innebörden. Lägg ALDRIG till fakta, hälsningar "
    "eller signaturer som inte sagts.\n"
    "Uppgifter, i denna ordning:\n"
    "1. Lös självrättelser och omstarter — behåll den slutliga avsikten "
    "(t.ex. 'klockan fem, nej förresten sex' → 'klockan sex').\n"
    "2. Bryt rörig talspråksföljd till läsbara meningar med korrekt interpunktion.\n"
    "3. Tillämpa kända rättelser och fackord/egennamn från referensblocket om "
    "det finns.\n"
    "4. Lätt formatering enligt eventuell app-profil.\n"
    "Gör INTE: jaga fyllnadsord utöver det uppenbara (modellen som "
    "transkriberat har redan rensat det mesta), ompolera redan korrekt text, "
    "eller fylla ut.\n"
    "Om texten redan är korrekt, returnera den EXAKT som den är.\n"
    "Returnera ENBART den färdiga texten — ingen förklaring, inga kodstaket, "
    "inga citationstecken runt."
)

_FEWSHOT = (
    "\n\nExempel:\n"
    "In: jag tänkte vi ses klockan fem nej förresten sex\n"
    "Ut: Jag tänkte vi ses klockan sex.\n"
    "In: så vi måste alltså fixa det här och eh sen ringa kunden och sen så\n"
    "Ut: Vi måste fixa det här och sedan ringa kunden.\n"
    "In: jag pratade med johan på kammar igår (referens: kammar → Kalmar)\n"
    "Ut: Jag pratade med Johan i Kalmar igår.\n"
    "In: skapa en ny gren som heter feature snedstreck login (app-profil: "
    "kod / ingen versalisering / ingen interpunktion)\n"
    "Ut: skapa en ny gren som heter feature/login"
)


def build_reference_block(
    personal_context: str = "",
    corrections: dict[str, str] | None = None,
    app_profile: str = "",
    onscreen_names: str = "",
) -> str:
    """Compose the reference block from its parts, omitting empty sections.

    Returns an empty string when everything is empty so the caller never sends
    a dangling header the model might treat as an instruction. The block is
    explicitly framed as *reference only* in :func:`_build_system_prompt`.
    """
    blocks: list[str] = []

    ctx = (personal_context or "").strip()
    if ctx:
        blocks.append("Personlig kontext:\n" + ctx)

    pairs = [
        (str(k).strip(), str(v).strip())
        for k, v in (corrections or {}).items()
        if str(k).strip() and str(v).strip() and str(k).strip() != str(v).strip()
    ]
    if pairs:
        lines = "\n".join(f"- {k} → {v}" for k, v in pairs)
        blocks.append("Kända rättelser (vänster → höger):\n" + lines)

    prof = (app_profile or "").strip()
    if prof:
        blocks.append("App-profil: " + prof)

    names = (onscreen_names or "").strip()
    if names:
        blocks.append("Namn på skärmen: " + names)

    return "\n\n".join(blocks)


def _build_system_prompt(reference_block: str = "") -> str:
    """Compose the system prompt, optionally appending a reference block.

    The reference is wrapped in clear delimiters and framed as *background
    reference* — not content to insert into the output. Empty / whitespace-only
    reference returns the bare base prompt (with few-shot) unchanged.
    """
    base = _SYSTEM_PROMPT + _FEWSHOT
    ref = (reference_block or "").strip()
    if not ref:
        return base
    return (
        f"{base}\n\n"
        "Referensblock (använd ENDAST som referens, klistra INTE in härifrån):\n"
        "---\n"
        f"{ref}\n"
        "---"
    )


def _text_meta(text: str) -> str:
    return f"chars={len(text)}, words={len(text.split())}"


def _build_headers(provider: _Provider, api_key: str) -> dict[str, str]:
    headers = {
        "Accept": provider.accept,
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if provider.api_version:
        headers["X-GitHub-Api-Version"] = provider.api_version
    return headers


# --------------------------------------------------------------------------- #
#  Keep-alive HTTP transport
#
#  Each polish reuses a persistent connection per origin to skip the TLS
#  handshake (~50-150 ms saved per dictation). Connections are pooled by
#  (scheme, host, port) and guarded by a single lock — polish runs one at a
#  time on the hot path, so serialising HTTP here costs nothing in practice and
#  keeps http.client (which is not thread-safe per connection) correct when a
#  Settings "Testa"-call overlaps. A stale/closed connection is dropped and the
#  request retried once.
# --------------------------------------------------------------------------- #

_conn_lock = threading.Lock()
_connections: dict[tuple[str, str, int], http.client.HTTPConnection] = {}


def _connection_for(url: str, timeout: float) -> tuple[tuple[str, str, int],
                                                       http.client.HTTPConnection]:
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    key = (parts.scheme, host, port)
    conn = _connections.get(key)
    if conn is None:
        if parts.scheme == "https":
            conn = http.client.HTTPSConnection(host, port, timeout=timeout)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
        _connections[key] = conn
    else:
        conn.timeout = timeout
    return key, conn


def _drop_connection(key: tuple[str, str, int]) -> None:
    conn = _connections.pop(key, None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def reset_sessions() -> None:
    """Close all pooled connections. Call after settings changes / provider swap."""
    with _conn_lock:
        for key in list(_connections):
            _drop_connection(key)


def _read_sse(resp: http.client.HTTPResponse) -> dict:
    """Assemble a streamed chat-completion (SSE) into the legacy response dict.

    Reading deltas as they arrive lets the caller begin paste-prep the moment
    the final token lands instead of waiting on a buffered full-body read.
    """
    content_parts: list[str] = []
    model = ""
    for raw_line in resp:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line or not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except Exception:
            continue
        model = chunk.get("model", model) or model
        for choice in chunk.get("choices", []) or []:
            delta = choice.get("delta", {}) or {}
            piece = delta.get("content")
            if piece:
                content_parts.append(piece)
    return {
        "choices": [{"message": {"content": "".join(content_parts)}}],
        "model": model,
        "usage": {},
    }


def _http_request(url: str, headers: dict[str, str], payload: bytes | None,
                  method: str, timeout_sec: float, stream: bool) -> dict:
    parts = urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    with _conn_lock:
        key, conn = _connection_for(url, timeout_sec)
        attempts = 0
        while True:
            attempts += 1
            try:
                conn.request(method, path, body=payload, headers=headers)
                resp = conn.getresponse()
                if resp.status >= 400:
                    err_body = resp.read()
                    _drop_connection(key)
                    raise urllib.error.HTTPError(
                        url, resp.status, resp.reason,
                        dict(resp.getheaders()), io.BytesIO(err_body),
                    )
                if stream:
                    return _read_sse(resp)
                raw = resp.read()
                return json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError:
                raise
            except (ConnectionError, http.client.HTTPException, OSError) as e:
                _drop_connection(key)
                if attempts < 2:
                    # Stale keep-alive connection — reopen and retry once.
                    key, conn = _connection_for(url, timeout_sec)
                    continue
                raise urllib.error.URLError(e) from e


def _request_json(url: str, headers: dict[str, str], payload: bytes | None,
                  method: str, timeout_sec: float) -> dict:
    """Non-streaming JSON request over the keep-alive pool (used by fetch_models)."""
    return _http_request(url, headers, payload, method, timeout_sec, stream=False)


def _call_api(
    api_key: str,
    model: str,
    user_text: str,
    timeout_sec: float = 8.0,
    provider: str = DEFAULT_PROVIDER,
    base_url_override: str = "",
    context_text: str = "",
    stream: bool = True,
) -> dict:
    p = _get_provider(provider)
    base = _resolve_base_url(provider, base_url_override)
    if not base:
        raise ValueError("base_url saknas för custom-leverantör")
    normalized = normalize_model(model, provider)
    if not normalized:
        raise ValueError("inget modellnamn angivet")
    body = {
        "model": normalized,
        "messages": [
            {"role": "system", "content": _build_system_prompt(context_text)},
            {"role": "user",   "content": user_text},
        ],
        "temperature": 0,
        # Output is a cleaned-up version of the input, never much longer.
        # ~1.3× input chars + a small constant covers punctuation growth.
        "max_tokens": max(64, int(len(user_text) * 1.3) + 32),
    }
    if stream:
        body["stream"] = True
    payload = json.dumps(body).encode("utf-8")
    return _http_request(
        f"{base}/chat/completions",
        _build_headers(p, api_key),
        payload,
        method="POST",
        timeout_sec=timeout_sec,
        stream=stream,
    )


# --------------------------------------------------------------------------- #
#  Publika operationer
# --------------------------------------------------------------------------- #

class PolishResult(NamedTuple):
    text: str
    model: str
    latency_ms: int
    changed: bool


def polish(
    text: str,
    api_key: str,
    model: str = "",
    provider: str = DEFAULT_PROVIDER,
    base_url_override: str = "",
    context_text: str = "",
    corrections: dict[str, str] | None = None,
    app_profile: str = "",
    onscreen_names: str = "",
) -> PolishResult:
    """Skicka text genom vald leverantör. Returnerar alltid något användbart.

    ``context_text`` är användarens personliga kontext (egennamn, facktermer,
    tonalitet). ``corrections`` är inlärda term-par (``fel → rätt``),
    ``app_profile`` är aktiv app-profil (ton/format) och ``onscreen_names`` är
    namn nära markören. Alla vävs in i ett *referensblock* i system-prompten —
    tomma delar utelämnas helt så modellen aldrig får ett dingelblock.

    Vid valfritt fel returneras originaltexten oförändrad — diktering blockeras
    aldrig av LLM-problem.
    """
    import time

    p = _get_provider(provider)
    text = text.strip()
    resolved_key = resolve_api_key(api_key, provider)
    used_model = normalize_model(model, provider) or p.default_model

    if not text or (not resolved_key and provider != "custom"):
        # Custom-providern tillåts köra utan nyckel (lokal llama.cpp osv).
        return PolishResult(text=text, model=used_model, latency_ms=0, changed=False)
    if not _resolve_base_url(provider, base_url_override):
        return PolishResult(text=text, model=used_model, latency_ms=0, changed=False)
    if not used_model:
        return PolishResult(text=text, model=used_model, latency_ms=0, changed=False)

    reference = build_reference_block(
        context_text, corrections, app_profile, onscreen_names,
    )

    t0 = time.perf_counter()
    try:
        data = _call_api(resolved_key, used_model, text,
                         provider=provider, base_url_override=base_url_override,
                         context_text=reference)
        # Sanitise BEFORE length / equality checks so control bytes don't
        # skew the hallucination filter and don't reach the clipboard.
        from text_sanitize import sanitize_output
        result = sanitize_output(
            data["choices"][0]["message"]["content"].strip()
        )
        latency = int((time.perf_counter() - t0) * 1000)

        # Hallucinationsfilter: en korrigering ska inte förändra texten radikalt.
        if len(result) > len(text) * 2 or len(result) < len(text) * 0.5:
            log.warning(
                "LLM-svar avviker för mycket i längd (%d vs %d), använder original",
                len(result), len(text),
            )
            return PolishResult(text=text, model=used_model, latency_ms=latency,
                                changed=False)

        changed = result != text
        if changed:
            log.info("LLM-polerad (%s/%s, %dms, in=%s, out=%s)",
                     provider, used_model, latency, _text_meta(text), _text_meta(result))
        else:
            log.info("LLM: ingen ändring behövdes (%s/%s, %dms)",
                     provider, used_model, latency)
        return PolishResult(text=result, model=used_model, latency_ms=latency,
                            changed=changed)

    except urllib.error.HTTPError as e:
        latency = int((time.perf_counter() - t0) * 1000)
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        log.warning("LLM HTTP %d (%dms, provider=%s, model=%s): %s",
                    e.code, latency, provider, used_model, body)
        return PolishResult(text=text, model=used_model, latency_ms=latency,
                            changed=False)

    except Exception as e:
        latency = int((time.perf_counter() - t0) * 1000)
        log.warning("LLM-fel (%s, %dms): %s", provider, latency, e)
        return PolishResult(text=text, model=used_model, latency_ms=latency,
                            changed=False)


def test_connection(
    api_key: str,
    model: str = "",
    provider: str = DEFAULT_PROVIDER,
    base_url_override: str = "",
) -> tuple[bool, str]:
    """Pinga vald leverantör. Returnerar (ok, meddelande)."""
    import time

    p = _get_provider(provider)
    base = _resolve_base_url(provider, base_url_override)
    if not base:
        return False, "Ingen base_url angiven för custom-leverantör"

    resolved_key = resolve_api_key(api_key, provider)
    if not resolved_key and provider != "custom":
        if provider == "github":
            return False, (
                "Ingen GitHub-auth hittades (ange nyckel, GITHUB_TOKEN/GH_TOKEN "
                "eller logga in med 'gh auth login')"
            )
        env_hint = "/".join(p.key_env_vars) if p.key_env_vars else "API-nyckel"
        return False, f"Ingen {p.label}-nyckel hittades. Ange nyckel eller sätt {env_hint}."

    used_model = normalize_model(model, provider) or p.default_model
    if not used_model:
        return False, "Inget modellnamn angivet — välj eller skriv in en modell."

    test_input = "Det här är ett test av dikteringsfunktionen."

    t0 = time.perf_counter()
    try:
        data = _call_api(resolved_key, used_model, test_input, timeout_sec=10.0,
                         provider=provider, base_url_override=base_url_override,
                         stream=False)
        latency = int((time.perf_counter() - t0) * 1000)
        from text_sanitize import sanitize_output
        # Same threat model as polish(): the provider could embed ANSI/control
        # bytes in the response. Sanitise before showing in Settings UI so the
        # test path can't smuggle control sequences via the "Visa svar" line.
        result = sanitize_output(data["choices"][0]["message"]["content"]).strip()
        actual_model = data.get("model", used_model)
        usage = data.get("usage", {}) or {}
        tokens_in = usage.get("prompt_tokens", "?")
        tokens_out = usage.get("completion_tokens", "?")
        return True, (
            f"OK! Leverantör: {p.label}\n"
            f"Modell: {actual_model}\n"
            f"Svar: \"{result}\"\n"
            f"Tid: {latency}ms | Tokens: {tokens_in} in, {tokens_out} ut"
        )

    except urllib.error.HTTPError as e:
        latency = int((time.perf_counter() - t0) * 1000)
        if e.code == 401:
            return False, f"Ogiltig API-nyckel (HTTP 401, {latency}ms)"
        if e.code == 403:
            return False, f"Åtkomst nekad (HTTP 403, {latency}ms)"
        if e.code == 404:
            return False, f"Modell '{used_model}' finns inte (HTTP 404, {latency}ms)"
        if e.code == 429:
            return False, f"Rate limit — för många anrop (HTTP 429, {latency}ms)"
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        return False, f"HTTP {e.code} ({latency}ms): {body}"

    except urllib.error.URLError as e:
        latency = int((time.perf_counter() - t0) * 1000)
        return False, f"Nätverksfel ({latency}ms): {e.reason}"

    except Exception as e:
        latency = int((time.perf_counter() - t0) * 1000)
        return False, f"Fel ({latency}ms): {e}"


def fetch_models(
    api_key: str = "",
    provider: str = DEFAULT_PROVIDER,
    base_url_override: str = "",
    timeout_sec: float = 5.0,
) -> dict[str, str]:
    """Försök hämta tillgängliga modeller från leverantören.

    Faller alltid tillbaka på den statiska listan i provider-definitionen så att
    Settings-UI:t kan visa något även utan nätverk eller nyckel.
    """
    p = _get_provider(provider)
    base = _resolve_base_url(provider, base_url_override)
    if not base:
        return dict(p.fallback_models)

    resolved_key = resolve_api_key(api_key, provider)
    if not resolved_key and provider != "custom":
        return dict(p.fallback_models)

    try:
        data = _request_json(
            f"{base}/models",
            _build_headers(p, resolved_key),
            payload=None,
            method="GET",
            timeout_sec=timeout_sec,
        )
    except Exception as e:
        log.info("Kunde inte hämta modellista från %s: %s", provider, e)
        return dict(p.fallback_models)

    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        return dict(p.fallback_models)

    result: dict[str, str] = dict(p.fallback_models)
    for item in items:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id") or item.get("name")
        if not model_id:
            continue
        desc = (
            item.get("summary")
            or item.get("description")
            or p.fallback_models.get(str(model_id), "")
        )
        result[str(model_id)] = str(desc)

    return result or dict(p.fallback_models)
