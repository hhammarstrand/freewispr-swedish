"""
Delad keep-alive HTTP-transport (L2).

Persistent anslutning per origin så att TLS-handskakningen inte betalas per
diktering. Används av både ``llm_polish`` (chat/SSE) och ``remote_transcribe``
(multipart audio). Stale anslutning → reopen + retry-en-gång.

Per-anrop-statistik (anslutningstid, om anslutningen återanvändes, samt TTFT för
streaming) exponeras via :func:`last_stats` (thread-local) så att latensloggen
(L0) kan rapportera ``conn_ms``/``conn_reused``/``first_token_ms`` utan att
ändra anroparnas returtyper.

Loggar aldrig nyckel eller innehåll — bara tider/metadata.
"""
from __future__ import annotations

import http.client
import io
import json
import threading
import time
import urllib.error
from urllib.parse import urlsplit

_lock = threading.Lock()
_connections: dict[tuple[str, str, int], http.client.HTTPConnection] = {}
_local = threading.local()

# Cap response bodies so a hostile or buggy provider can't stream an
# arbitrarily large body and exhaust memory on the hot path. Transcription
# and chat-completion responses are kilobytes; 32 MB is a very generous ceiling.
_MAX_RESPONSE_BYTES = 32 * 1024 * 1024


def _set_stats(conn_ms: float, conn_reused: bool, first_token_ms: float = 0.0) -> None:
    _local.stats = {
        "conn_ms": conn_ms,
        "conn_reused": conn_reused,
        "first_token_ms": first_token_ms,
    }


def last_stats() -> dict:
    """Return the stats for the most recent request on this thread."""
    return dict(getattr(_local, "stats", {}))


def connection_for(url: str, timeout: float
                   ) -> tuple[tuple[str, str, int], http.client.HTTPConnection, bool]:
    """Return ``(key, connection, reused)`` for ``url``, opening one if needed."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    key = (parts.scheme, host, port)
    conn = _connections.get(key)
    if conn is not None:
        # http.client locks the socket timeout at connect() time; reassigning
        # conn.timeout afterwards does NOT change an already-connected socket.
        # A connection opened by a warmer (short timeout) would otherwise make
        # a later long request (e.g. a 60 s remote transcription) time out
        # early. Reopen when the caller needs more headroom than we have.
        opened = getattr(conn, "_pool_timeout", None)
        if opened is not None and timeout > opened:
            drop_connection(key)
            conn = None
    if conn is None:
        if parts.scheme == "https":
            conn = http.client.HTTPSConnection(host, port, timeout=timeout)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn._pool_timeout = timeout
        _connections[key] = conn
        return key, conn, False
    return key, conn, True


def drop_connection(key: tuple[str, str, int]) -> None:
    conn = _connections.pop(key, None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def reset() -> None:
    """Close all pooled connections (call after settings/provider changes)."""
    with _lock:
        for key in list(_connections):
            drop_connection(key)


def read_sse(resp: http.client.HTTPResponse, t_send: float = 0.0) -> dict:
    """Assemble a streamed chat-completion (SSE) into the legacy response dict.

    Records TTFT (first content delta) into thread-local stats when ``t_send``
    is given, so paste-prep latency analysis (L3) can see it.
    """
    content_parts: list[str] = []
    model = ""
    first_token_ms = 0.0
    total_bytes = 0
    for raw_line in resp:
        total_bytes += len(raw_line)
        if total_bytes > _MAX_RESPONSE_BYTES:
            raise urllib.error.URLError("SSE response exceeded size limit")
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
                if not content_parts and t_send:
                    first_token_ms = (time.monotonic() - t_send) * 1000
                content_parts.append(piece)
    if t_send:
        st = getattr(_local, "stats", {}) or {}
        st["first_token_ms"] = first_token_ms
        _local.stats = st
    return {
        "choices": [{"message": {"content": "".join(content_parts)}}],
        "model": model,
        "usage": {},
    }


def request(url: str, headers: dict[str, str], payload: bytes | None = None,
            method: str = "POST", timeout: float = 8.0, stream: bool = False,
            parse: str = "json"):
    """Perform a pooled request.

    Returns a parsed dict (``parse="json"`` or ``stream``) or raw bytes
    (``parse="raw"``). Raises ``urllib.error.HTTPError`` on >=400 and
    ``urllib.error.URLError`` on connection failure after one retry.
    """
    parts = urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    with _lock:
        key, conn, reused = connection_for(url, timeout)
        attempts = 0
        while True:
            attempts += 1
            conn_ms = 0.0
            try:
                if not reused:
                    t_c = time.monotonic()
                    conn.connect()
                    conn_ms = (time.monotonic() - t_c) * 1000
                t_send = time.monotonic()
                conn.request(method, path, body=payload, headers=headers)
                resp = conn.getresponse()
                if resp.status >= 400:
                    err_body = resp.read(_MAX_RESPONSE_BYTES + 1)[:_MAX_RESPONSE_BYTES]
                    drop_connection(key)
                    _set_stats(conn_ms, reused)
                    raise urllib.error.HTTPError(
                        url, resp.status, resp.reason,
                        dict(resp.getheaders()), io.BytesIO(err_body),
                    )
                _set_stats(conn_ms, reused)
                if stream:
                    return read_sse(resp, t_send)
                raw = resp.read(_MAX_RESPONSE_BYTES + 1)
                if len(raw) > _MAX_RESPONSE_BYTES:
                    drop_connection(key)
                    raise urllib.error.URLError("Response exceeded size limit")
                if parse == "raw":
                    return raw
                return json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError:
                raise
            except (ConnectionError, http.client.HTTPException, OSError) as e:
                drop_connection(key)
                if attempts < 2:
                    # Stale keep-alive connection — reopen and retry once.
                    key, conn, reused = connection_for(url, timeout)
                    reused = False
                    continue
                raise urllib.error.URLError(e) from e
