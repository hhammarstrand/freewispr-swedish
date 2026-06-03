"""
Validation helpers for user-provided remote endpoints.

Why this module exists
----------------------
Both `llm_polish` and `remote_transcribe` accept a `base_url_override` for the
"custom" provider. The override flows from `~/.freewispr-swedish/config.json`
and the Settings UI directly to `urllib.request.urlopen` together with the
user's API key and (for transcription) recorded microphone audio.

If a user enters `http://attacker.example/v1`, every request would leak the
bearer token and the audio in cleartext. We refuse to make that request.

Policy
------
* `https://` — always allowed.
* `http://` — allowed only when the host resolves to loopback
  (`localhost`, `127.0.0.0/8`, `::1`) AND the caller opted in via
  ``allow_plaintext_loopback=True``. This carve-out exists so power users
  can point the LLM provider at a local Ollama / LM Studio without going
  through TLS.
* All other schemes (`file://`, `ftp://`, `javascript:`, …) — rejected.
* IPv6 zone identifiers, userinfo (`user:pass@host`) — rejected as a
  defense-in-depth measure against URL parser confusion.

The function returns `(ok, error_message)` so callers can surface a
human-readable Swedish message in the UI without trying to translate
exceptions.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit


def _is_loopback_host(host: str) -> bool:
    if not host:
        return False
    host = host.strip("[]").lower()
    if host in ("localhost", "ip6-localhost", "ip6-loopback"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_base_url(url: str, *, allow_plaintext_loopback: bool = False
                      ) -> tuple[bool, str]:
    """
    Validate a user-supplied base URL.

    Args:
        url: The URL to validate. Empty/whitespace is rejected.
        allow_plaintext_loopback: If True, ``http://`` is permitted but only
            for loopback hosts. Use this for LLM endpoints (local Ollama is
            a common setup). Leave False for transcription endpoints — the
            audio payload is too sensitive to send unencrypted even to
            loopback, because anything that can sniff loopback (other
            processes, system tools) can capture the recording.

    Returns:
        ``(True, "")`` if the URL is acceptable, otherwise
        ``(False, "<svensk förklaring>")``.
    """
    if url is None:
        return False, "Ingen URL angiven."
    s = url.strip()
    if not s:
        return False, "Ingen URL angiven."

    try:
        parts = urlsplit(s)
    except ValueError as e:
        return False, f"Ogiltig URL: {e}"

    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False, (
            f"Endast http(s):// stöds — fick \"{scheme}://\". "
            f"Ange en HTTPS-URL till leverantörens API."
        )

    if not parts.hostname:
        return False, "URL:en saknar värdnamn."

    if parts.username or parts.password:
        return False, (
            "URL:en får inte innehålla användarnamn eller lösenord "
            "(user:pass@host)."
        )

    # A base URL is only scheme/host/port/path — endpoints are built by
    # appending paths. A querystring or fragment is almost always a sign that
    # the user pasted a full URL with credentials (e.g. ?api_key=...), which
    # would leak into proxy/server logs and make path concatenation ambiguous.
    if parts.query:
        return False, (
            "URL:en får inte innehålla en frågesträng (?...). "
            "Ange bara bas-URL:en till API:et, t.ex. https://host/v1."
        )
    if parts.fragment:
        return False, (
            "URL:en får inte innehålla ett fragment (#...). "
            "Ange bara bas-URL:en till API:et, t.ex. https://host/v1."
        )

    if scheme == "http":
        if not allow_plaintext_loopback:
            return False, (
                "Endast HTTPS tillåts för fjärrtranskribering — ljud "
                "och API-nyckel skickas annars i klartext. Ändra till "
                "https:// eller använd en lokal Whisper istället."
            )
        if not _is_loopback_host(parts.hostname):
            return False, (
                f"HTTP utan TLS tillåts endast för loopback (localhost, "
                f"127.0.0.1, ::1). Värdnamnet \"{parts.hostname}\" är inte "
                f"loopback — använd https:// i stället."
            )

    return True, ""


def is_plaintext_loopback(url: str) -> bool:
    """Convenience: True iff ``url`` is a valid http:// loopback URL."""
    ok, _ = validate_base_url(url, allow_plaintext_loopback=True)
    if not ok:
        return False
    parts = urlsplit(url.strip())
    return parts.scheme.lower() == "http" and _is_loopback_host(parts.hostname or "")
