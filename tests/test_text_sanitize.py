"""Tests for text_sanitize.sanitize_output."""

from __future__ import annotations

import pytest

from text_sanitize import sanitize_output


class TestSanitizeOutput:
    def test_empty_inputs(self):
        assert sanitize_output("") == ""
        assert sanitize_output(None) == ""  # type: ignore[arg-type]

    def test_plain_text_unchanged(self):
        s = "Hej världen! Det här är en vanlig mening."
        assert sanitize_output(s) == s

    def test_swedish_diacritics_preserved(self):
        assert sanitize_output("åäö ÅÄÖ") == "åäö ÅÄÖ"

    def test_tab_and_newline_preserved(self):
        assert sanitize_output("a\tb\nc") == "a\tb\nc"

    @pytest.mark.parametrize("payload,expected", [
        ("normal\x00text", "normaltext"),         # NUL
        ("ding\x07ding", "dingding"),             # BEL
        ("erase\x08me", "eraseme"),               # BS
        ("clear\x0bvtab", "clearvtab"),           # VT
        ("page\x0cfeed", "pagefeed"),             # FF
        ("esc\x1b[31mred", "esc[31mred"),         # ESC (ANSI prefix)
        ("del\x7fbyte", "delbyte"),               # DEL
        ("c1\x9btest", "c1test"),                 # C1 control
    ])
    def test_control_bytes_stripped(self, payload, expected):
        assert sanitize_output(payload) == expected

    def test_lone_cr_becomes_lf(self):
        assert sanitize_output("line1\rline2") == "line1\nline2"

    def test_crlf_normalised_to_lf(self):
        assert sanitize_output("line1\r\nline2") == "line1\nline2"

    def test_ansi_color_sequence_neutralised(self):
        # ESC bytes stripped → the literal "[31m" remains as plain text,
        # which terminals render as harmless ASCII instead of switching
        # to red foreground.
        assert sanitize_output("\x1b[31mRED\x1b[0m") == "[31mRED[0m"

    def test_idempotent(self):
        s = "esc\x1bseq\x07bell"
        once = sanitize_output(s)
        twice = sanitize_output(once)
        assert once == twice == "escseqbell"

    def test_unicode_zero_width_preserved(self):
        # Zero-width space is not a Trojan-Source vector. Whisper sometimes
        # emits \u200b inside Swedish compounds; leave it alone.
        s = "ord\u200bdelning"
        assert sanitize_output(s) == s

    @pytest.mark.parametrize("cp", [
        0x202a, 0x202b, 0x202c, 0x202d, 0x202e,  # bidi embeddings/overrides
        0x2066, 0x2067, 0x2068, 0x2069,          # bidi isolates
    ])
    def test_bidi_overrides_stripped(self, cp):
        # Trojan Source (CVE-2021-42574): these reorder rendered text without
        # changing logical content. Must not survive sanitisation.
        payload = f"safe{chr(cp)}danger"
        assert sanitize_output(payload) == "safedanger"

    @pytest.mark.parametrize("cp", [0x2028, 0x2029])
    def test_line_paragraph_separators_stripped(self, cp):
        # Treated as line terminators by some parsers (e.g. JS); strip so they
        # can't smuggle a break past a single-line consumer.
        payload = f"a{chr(cp)}b"
        assert sanitize_output(payload) == "ab"
