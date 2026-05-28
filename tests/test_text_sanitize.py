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
        # We only strip ASCII/Latin-1 controls. Whisper sometimes emits
        # \u200b inside Swedish compounds; leave it alone.
        s = "ord\u200bdelning"
        assert sanitize_output(s) == s
