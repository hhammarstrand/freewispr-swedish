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
import urllib.error
import urllib.request
import wave
from typing import NamedTuple

import numpy as np

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
        label="Berget AI (EU)",
        base_url="https://api.berget.ai/v1",
        key_env_vars=("BERGET_API_KEY",),
        default_model="KBLab/kb-whisper-large",
        user_configurable_url=False,
    ),
    "custom": _Provider(
        label="Custom (OpenAI-kompatibel)",
        base_url="",
        key_env_vars=("LLM_API_KEY",),
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

def transcribe(
    audio: np.ndarray,
    sample_rate: int,
    provider: str,
    api_key: str = "",
    model: str = "",
    language: str = "sv",
    base_url_override: str = "",
    timeout_sec: float = 60.0,
) -> str:
    """Skicka ljud till remote-leverantör. Returnerar transkriberad text.

    Höjer ``RemoteTranscribeError`` vid valfritt fel — anroparen ansvarar för
    att inte krascha appen.
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

    body, content_type = _build_multipart(fields, wav_bytes)
    headers = {
        "Accept": "application/json",
        "Content-Type": content_type,
        "Content-Length": str(len(body)),
    }
    if resolved_key:
        headers["Authorization"] = f"Bearer {resolved_key}"

    url = f"{base}/audio/transcriptions"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    log.info("Remote transcribe -> %s (%s, %d samples, %d sr)",
             provider, used_model, audio.size, sample_rate)

    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        # Försök läsa kropp för bättre felmeddelande men logga inte audio.
        body_snippet = ""
        try:
            body_snippet = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        msg = _http_message(e.code, body_snippet)
        log.warning("Remote transcribe HTTP %d (%s): %s", e.code, provider, msg)
        raise RemoteTranscribeError(msg) from e
    except urllib.error.URLError as e:
        log.warning("Remote transcribe nätverksfel (%s): %s", provider, e.reason)
        raise RemoteTranscribeError(f"Nätverksfel: {e.reason}") from e
    except Exception as e:
        log.warning("Remote transcribe oväntat fel (%s): %s", provider, e)
        raise RemoteTranscribeError(f"Fel: {e}") from e

    # Body kan vara JSON ({"text": "..."}) eller ren text beroende på server.
    try:
        data = json.loads(raw.decode("utf-8"))
        text = (data.get("text") if isinstance(data, dict) else "") or ""
    except Exception:
        text = raw.decode("utf-8", errors="replace")

    text = text.strip()
    log.info("Remote transcribe ok (%s, %d chars)", provider, len(text))
    return text


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
        return f"Serverfel (HTTP {code})"
    snippet = body[:120] if body else ""
    return f"HTTP {code}: {snippet}".rstrip(": ")
