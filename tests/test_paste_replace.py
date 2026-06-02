"""Fix #5: replace_len_for matches the glyphs paste_text actually emits.

paste_text strips its input and appends exactly one trailing space, so a
previously pasted block occupies len(stripped) + 1 glyphs. Command-mode replace
backspaces that many characters; the count must come from this single source of
truth so a stored *unstripped* block (e.g. an LLM result) never miscounts.
"""
from __future__ import annotations

import paste


def test_replace_len_for_counts_stripped_plus_trailing_space():
    assert paste.replace_len_for("hej") == 4  # len("hej") + 1


def test_replace_len_for_ignores_surrounding_whitespace():
    # paste_text strips, so leading/trailing whitespace must not inflate count.
    assert paste.replace_len_for("  hej  ") == 4
    assert paste.replace_len_for("hej\n") == 4


def test_replace_len_for_empty_returns_zero():
    # Never backspace into unrelated content when there is no prior block.
    assert paste.replace_len_for("") == 0
    assert paste.replace_len_for("   ") == 0
    assert paste.replace_len_for(None) == 0


def test_replace_len_for_unicode_counts_codepoints():
    # Swedish glyphs are one backspace each.
    assert paste.replace_len_for("Åsa") == 4
