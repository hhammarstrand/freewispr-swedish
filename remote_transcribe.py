"""
Remote audio transcription via OpenAI-kompatibelt ``/v1/audio/transcriptions``.

Används som alternativ till lokal ``faster-whisper`` när användaren har valt
en remote-leverantör (staik.se eller berget.ai). Båda hostar KB-Whisper Large,
KB-bibliotekets svensk-tränade Whisper-modell.

Designkontrakt:

- Funktionen ``transcribe()`` blockerar tills servern svarat eller höjt fel.
- Vid lyckat svar returneras ren text (samma format som ``Transcriber._postprocess``
  tar emot från lokal Whisper, dvs. utan extra newlines).
- Vid valfritt fel höjs ``RemoteTranscribeError`` med ett kort meddelande som
  går att visa i indikatorn. Anroparen ansvarar för att inte krascha.
- Inget audio-data loggas. Endast längd och resultatets längd skrivs ut.
"""
from __future__ import annotations

import io
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.request
import wave
from typing import NamedTuple

# HTTP status-koder som indikerar ett övergående fel hos servern/gatewayen.
# Dessa är värda att försöka igen — till skillnad från 4xx (klientfel) som
# inte blir bättre av en retry. STAIK:s gateway svarar tidvis 502/503 under
# last; ett par återförsök med backoff räddar de flesta sådana fallen.
_RETRYABLE_HTTP_CODES = frozenset({502, 503, 504})
_MAX_ATTEMPTS = 3
_RETRY_BASE_DELAY = 0.6  # sekunder; växer exponentiellt per försök

import numpy as np

import http_pool

log = logging.getLogger("freewispr")


class RemoteTranscribeError(RuntimeError):
    """Raised when remote transcription fails. Message is safe to display."""


class _Provider(NamedTuple):
    label: str
    base_url: str
    key_env_vars: tuple[str, ...]
    default_model: str
    user_configurable_url: bool


PROVIDERS: dict[str, _Provider] = {
    "staik": _Provider(
        label="staik.se (SE)",
        base_url="https://api.staik.se/v1",
        key_env_vars=("STAIK_API_KEY",),
        default_model="kb-whisper-large",
        user_configurable_url=False,
    ),
    "berget": _Provider(
        label="Berget AI (SE)",
        base_url="https://api.berget.ai/v1",
        key_env_vars=("BERGET_API_KEY",),
        default_model="KBLab/kb-whisper-large",
        user_configurable_url=False,
    ),
    "custom": _Provider(
        label="Custom (OpenAI-kompatibel)",
        base_url="",
        key_env_vars=("TRANSCRIPTION_API_KEY",),
        default_model="",
        user_configurable_url=True,
    ),
}


def provider_labels() -> dict[str, str]:
    return {pid: p.label for pid, p in PROVIDERS.items()}


def provider_default_model(provider: str) -> str:
    p = PROVIDERS.get(provider)
    return p.default_model if p else ""


def _get_provider(provider: str) -> _Provider:
    if provider not in PROVIDERS:
        raise RemoteTranscribeError(f"Okänd remote-leverantör: {provider!r}")
    return PROVIDERS[provider]


def _resolve_base_url(provider: str, base_url_override: str = "") -> str:
    p = _get_provider(provider)
    url = (base_url_override or p.base_url or "").strip().rstrip("/")
    if not url:
        raise RemoteTranscribeError("Ingen base_url för custom-leverantören")
    # Hard requirement for transcription: TLS only. The payload is microphone
    # audio plus a bearer token — even loopback HTTP is too leaky because any
    # local process can sniff the recording. Built-in providers use https://
    # so this only ever rejects misconfigured custom endpoints.
    from url_security import validate_base_url
    ok, msg = validate_base_url(url, allow_plaintext_loopback=False)
    if not ok:
        raise RemoteTranscribeError(msg)
    return url


def _resolve_api_key(api_key: str, provider: str) -> str:
    explicit = (api_key or "").strip()
    if explicit:
        return explicit
    p = _get_provider(provider)
    for name in p.key_env_vars:
        token = os.environ.get(name, "").strip()
        if token:
            return token
    return ""


# --------------------------------------------------------------------------- #
#  WAV-encoding och multipart-builder
# --------------------------------------------------------------------------- #

def _float_to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    """Konvertera float32 mono [-1, 1] till 16-bit PCM WAV-bytes."""
    if audio.dtype != np.float32:
        audio = audio.astype(np.float32, copy=False)
    if audio.ndim != 1:
        if audio.shape[1] > 1:
            audio = audio.mean(axis=1).astype(np.float32)
        else:
            audio = audio.reshape(-1)
    # Klampa och konvertera till int16 utan att introducera DC.
    clipped = np.clip(audio, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(sample_rate))
        wav.writeframes(pcm.tobytes())
    return buf.getvalue()


def _build_multipart(fields: dict[str, str], wav_bytes: bytes,
                     filename: str = "audio.wav") -> tuple[bytes, str]:
    """Bygg multipart/form-data body. Returnerar (body, content_type)."""
    boundary = "----freewispr-" + secrets.token_hex(16)
    crlf = b"\r\n"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(b"--" + boundary.encode("ascii") + crlf)
        parts.append(
            f'Content-Disposition: form-data; name="{name}"'.encode("ascii") + crlf
        )
        parts.append(crlf)
        parts.append(str(value).encode("utf-8"))
        parts.append(crlf)
    # File part.
    parts.append(b"--" + boundary.encode("ascii") + crlf)
    parts.append(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode("ascii") + crlf
    )
    parts.append(b"Content-Type: audio/wav" + crlf)
    parts.append(crlf)
    parts.append(wav_bytes)
    parts.append(crlf)
    parts.append(b"--" + boundary.encode("ascii") + b"--" + crlf)
    body = b"".join(parts)
    return body, f"multipart/form-data; boundary={boundary}"


# --------------------------------------------------------------------------- #
#  Publika operationer
# --------------------------------------------------------------------------- #

def _request_with_retry(url: str, headers: dict[str, str], body: bytes,
                        provider: str, timeout_sec: float) -> bytes:
    """Skicka requesten och försök igen vid övergående serverfel.

    Återförsök sker bara vid 502/503/504 och vid nätverksfel (URLError),
    eftersom dessa typiskt är tillfälliga. Klientfel (4xx) höjs direkt utan
    retry. Mellan försöken väntar vi med exponentiell backoff. Om alla försök
    misslyckas höjs ``RemoteTranscribeError`` med det sista felmeddelandet.

    Transporten går via ``http_pool`` (L2) så TCP/TLS-anslutningen återanvänds
    mellan dikteringar i stället för en ny handskakning varje gång. Samma
    ``body`` återanvänds på varje försök, så ingen ominspelning behövs.
    """
    last_error: Exception | None = None

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return http_pool.request(url, headers, payload=body, method="POST",
                                     timeout=timeout_sec, parse="raw")
        except urllib.error.HTTPError as e:
            body_snippet = ""
            try:
                body_snippet = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            msg = _http_message(e.code, body_snippet)
            last_error = RemoteTranscribeError(msg)

            if e.code in _RETRYABLE_HTTP_CODES and attempt < _MAX_ATTEMPTS:
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                log.warning(
                    "Remote transcribe HTTP %d (%s): %s — försöker igen "
                    "(%d/%d) om %.1fs",
                    e.code, provider, msg, attempt, _MAX_ATTEMPTS, delay,
                )
                time.sleep(delay)
                continue

            log.warning("Remote transcribe HTTP %d (%s): %s",
                        e.code, provider, msg)
            raise last_error from e
        except urllib.error.URLError as e:
            last_error = RemoteTranscribeError(f"Nätverksfel: {e.reason}")
            if attempt < _MAX_ATTEMPTS:
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                log.warning(
                    "Remote transcribe nätverksfel (%s): %s — försöker igen "
                    "(%d/%d) om %.1fs",
                    provider, e.reason, attempt, _MAX_ATTEMPTS, delay,
                )
                time.sleep(delay)
                continue
            log.warning("Remote transcribe nätverksfel (%s): %s",
                        provider, e.reason)
            raise last_error from e
        except Exception as e:
            log.warning("Remote transcribe oväntat fel (%s): %s", provider, e)
            raise RemoteTranscribeError(f"Fel: {e}") from e

    # Bör inte nås — loopen returnerar eller höjer alltid. Skyddsnät:
    assert last_error is not None
    raise last_error


def transcribe(
    audio: np.ndarray,
    sample_rate: int,
    provider: str,
    api_key: str = "",
    model: str = "",
    language: str = "sv",
    base_url_override: str = "",
    timeout_sec: float = 60.0,
    prompt: str = "",
    temperature: float | None = None,
) -> str:
    """Skicka ljud till remote-leverantör. Returnerar transkriberad text.

    Höjer ``RemoteTranscribeError`` vid valfritt fel — anroparen ansvarar för
    att inte krascha appen.

    AP4: ``prompt`` (biasing-sträng) och ``temperature`` skickas med när de
    anges. OpenAI-kompatibla transkriberings-API:er stödjer dessa fält; en
    leverantör som ignorerar dem gör helt enkelt no-op.
    """
    if audio is None or audio.size == 0:
        return ""

    p = _get_provider(provider)
    base = _resolve_base_url(provider, base_url_override)
    resolved_key = _resolve_api_key(api_key, provider)
    used_model = (model or p.default_model).strip()

    if not used_model:
        raise RemoteTranscribeError("Inget modellnamn angivet för transkribering")
    if not resolved_key and provider != "custom":
        raise RemoteTranscribeError(f"Ingen {p.label}-nyckel hittades")

    wav_bytes = _float_to_wav_bytes(audio, sample_rate)
    fields = {"model": used_model}
    if language:
        fields["language"] = language
    if prompt:
        # Whisper prompt budget is ~224 tokens; keep it short.
        fields["prompt"] = prompt[:800]
        log.info("Remote transcribe inkluderar prompt (%d tecken) — "
                 "leverantörer som inte stödjer det ignorerar fältet",
                 len(fields["prompt"]))
    if temperature is not None:
        fields["temperature"] = str(temperature)

    body, content_type = _build_multipart(fields, wav_bytes)
    headers = {
        "Accept": "application/json",
        "Content-Type": content_type,
        "Content-Length": str(len(body)),
    }
    if resolved_key:
        headers["Authorization"] = f"Bearer {resolved_key}"

    url = f"{base}/audio/transcriptions"

    log.info("Remote transcribe -> %s (%s, %d samples, %d sr)",
             provider, used_model, audio.size, sample_rate)

    raw = _request_with_retry(url, headers, body, provider, timeout_sec)

    # Body kan vara JSON ({"text": "..."}) eller ren text beroende på server.
    try:
        data = json.loads(raw.decode("utf-8"))
        text = (data.get("text") if isinstance(data, dict) else "") or ""
    except Exception:
        text = raw.decode("utf-8", errors="replace")

    # Sanity check: servern kan returnera HTML trots HTTP 200.
    if '<html' in text.lower() or '<!' in text[:20]:
        log.warning("Remote transcribe returnerade HTML istället för text")
        return ""

    # Sanitise control bytes before logging length / returning to the
    # dictation pipeline. A hostile provider could embed ANSI escapes
    # that would otherwise land on the user's clipboard verbatim.
    from text_sanitize import sanitize_output
    text = sanitize_output(text.strip())
    log.info("Remote transcribe ok (%s, %d chars)", provider, len(text))
    return text


def test_connection(
    provider: str,
    api_key: str = "",
    base_url_override: str = "",
    timeout_sec: float = 8.0,
) -> tuple[bool, str]:
    """Snabb anslutningsverifiering. Returnerar ``(ok, message)``.

    Pingar ``{base}/models`` (OpenAI-kompatibelt) och tolkar svaret. Försöker
    *inte* lista transkriberings-modeller specifikt — leverantörer som Berget
    blandar in LLM-modeller i samma katalog och vi bryr oss bara om att
    autentiseringen fungerar.

    Inga ljud-bytes skickas. Säker att anropa på UI-tråden men kan blockera
    upp till ``timeout_sec`` sekunder — kallaren bör köra i bakgrundstråd.
    """
    try:
        p = _get_provider(provider)
    except RemoteTranscribeError as e:
        return False, str(e)

    try:
        base = _resolve_base_url(provider, base_url_override)
    except RemoteTranscribeError as e:
        return False, str(e)

    resolved_key = _resolve_api_key(api_key, provider)
    if not resolved_key and provider != "custom":
        return False, f"Ingen {p.label}-nyckel hittades"

    headers = {"Accept": "application/json"}
    if resolved_key:
        headers["Authorization"] = f"Bearer {resolved_key}"

    url = f"{base}/models"
    req = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            resp.read(1024)  # förbruka lite av kroppen för att stänga TLS rent
    except urllib.error.HTTPError as e:
        body_snippet = ""
        try:
            body_snippet = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        return False, _http_message(e.code, body_snippet)
    except urllib.error.URLError as e:
        return False, f"Nätverksfel: {e.reason}"
    except Exception as e:
        return False, f"Fel: {e}"

    return True, f"Ansluten till {p.label}"


def _http_message(code: int, body: str) -> str:
    if code == 401:
        return "Ogiltig API-nyckel (HTTP 401)"
    if code == 403:
        return "Åtkomst nekad (HTTP 403)"
    if code == 404:
        return "Modellen finns inte (HTTP 404)"
    if code == 413:
        return "Ljudfilen är för stor (HTTP 413)"
    if code == 415:
        return "Filformatet stöds inte (HTTP 415)"
    if code == 429:
        return "Rate limit eller daglig token-cap nådd (HTTP 429)"
    if 500 <= code < 600:
        if code in _RETRYABLE_HTTP_CODES:
            return f"Servern tillfälligt otillgänglig (HTTP {code}) — försök igen"
        return f"Serverfel (HTTP {code})"
    snippet = body[:120] if body else ""
    return f"HTTP {code}: {snippet}".rstrip(": ")
