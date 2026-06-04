"""
Sanitise text returned from untrusted remote sources before it lands in the
user's clipboard / paste buffer.

Threat model
------------
* LLM-polish returns text from a third-party provider (GitHub Models,
  OpenAI, Berget, custom). A compromised or hostile provider could embed
  ANSI / OSC / DCS escape sequences in the polished text.
* Remote transcription returns text from a Whisper-compatible API. Same
  risk surface.
* The user pastes that text into arbitrary targets (terminals, editors,
  chat apps). Some terminals still act on control characters pasted into
  them — Windows Terminal sanitises since 2022, but older xterm, conhost,
  PuTTY and many TTY-based tools do not.

Policy
------
Strip every C0 and C1 control byte except:
* ``\t``   (horizontal tab — common in dictated structured text)
* ``\n``   (line feed — preserved verbatim)

In particular this removes:
* ``\x00`` (NUL — string truncation on C-API consumers)
* ``\x07`` (BEL — audible alarm on some terminals)
* ``\x08`` (BS — backspace; can erase preceding text in terminals)
* ``\x0b``/``\x0c`` (vertical tab / form feed)
* ``\r``   (carriage return alone — normalised to nothing; CRLF callers
            should normalise to ``\n`` themselves before sanitising)
* ``\x1b`` (ESC — leading byte of all ANSI/OSC/CSI/DCS sequences)
* ``\x7f`` (DEL)
* ``\x80``-``\x9f`` (C1 controls — used by some 8-bit terminals)

Whisper occasionally emits ``\u200b`` zero-width space inside Swedish
compounds; we leave that alone. Beyond the ASCII/Latin-1 control bytes we
also strip the "Trojan Source" (CVE-2021-42574) bidi-override and isolate
characters (U+202A-U+202E, U+2066-U+2069) plus the line/paragraph
separators U+2028/U+2029. A compromised provider could otherwise visually
reorder pasted text — especially source code — without changing its
logical content, or smuggle a line break past a single-line consumer.
"""

from __future__ import annotations

# Built once at import time. Maps every codepoint we strip → None.
# We *keep* \t (0x09) and \n (0x0a); everything else in [0x00, 0x1f] goes,
# plus 0x7f (DEL) and [0x80, 0x9f] (C1).
_KEEP = {0x09, 0x0a}
# Trojan-Source / line-injection Unicode formatting chars (CVE-2021-42574):
# bidi embeddings/overrides, bidi isolates, and line/paragraph separators.
_BIDI_AND_SEPARATORS = (
    list(range(0x202a, 0x202f))  # LRE, RLE, PDF, LRO, RLO
    + list(range(0x2066, 0x206a))  # LRI, RLI, FSI, PDI
    + [0x2028, 0x2029]  # line / paragraph separator
)
_STRIP_TABLE = {
    cp: None
    for cp in (
        list(range(0x00, 0x20))
        + [0x7f]
        + list(range(0x80, 0xa0))
        + _BIDI_AND_SEPARATORS
    )
    if cp not in _KEEP
}


def sanitize_output(text: str) -> str:
    """
    Strip control bytes and dangerous Unicode formatting characters from
    ``text``, preserving ``\\t`` and ``\\n``. Idempotent. Returns ``""`` for
    None.
    """
    if not text:
        return ""
    # Normalise lone CR / CRLF → LF first so we don't lose line breaks
    # when \r is stripped.
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.translate(_STRIP_TABLE)
