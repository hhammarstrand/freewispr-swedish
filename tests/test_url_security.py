"""Tests for url_security.validate_base_url and provider-level enforcement."""

from __future__ import annotations

import pytest

from url_security import validate_base_url, is_plaintext_loopback


class TestValidateBaseUrl:
    @pytest.mark.parametrize("url", [
        "https://api.example.com/v1",
        "https://api.example.com:8443/v1/",
        "https://192.0.2.5/api",
        "https://[2001:db8::1]/v1",
    ])
    def test_https_always_accepted(self, url):
        ok, msg = validate_base_url(url)
        assert ok, msg

    @pytest.mark.parametrize("url,expect_keyword", [
        ("", "Ingen URL"),
        ("   ", "Ingen URL"),
        ("ftp://example.com/v1", "Endast http"),
        ("javascript:alert(1)", "Endast http"),
        ("file:///etc/passwd", "Endast http"),
        ("not-a-url", "Endast http"),
        ("https://user:pass@example.com/v1", "användarnamn"),
    ])
    def test_rejected_inputs(self, url, expect_keyword):
        ok, msg = validate_base_url(url)
        assert not ok
        assert expect_keyword.lower() in msg.lower()

    def test_http_rejected_when_plaintext_loopback_disabled(self):
        # Transcription path: even loopback HTTP rejected because audio is sensitive.
        ok, msg = validate_base_url("http://localhost:1234/v1",
                                    allow_plaintext_loopback=False)
        assert not ok
        assert "HTTPS" in msg or "https" in msg

    @pytest.mark.parametrize("url", [
        "http://localhost:11434/v1",
        "http://127.0.0.1:8080",
        "http://[::1]/api",
    ])
    def test_http_loopback_accepted_when_opted_in(self, url):
        ok, msg = validate_base_url(url, allow_plaintext_loopback=True)
        assert ok, msg

    @pytest.mark.parametrize("url", [
        "http://example.com/v1",
        "http://192.0.2.5/api",
        "http://internal.corp/v1",
    ])
    def test_http_nonloopback_rejected_even_when_opted_in(self, url):
        ok, msg = validate_base_url(url, allow_plaintext_loopback=True)
        assert not ok
        assert "loopback" in msg.lower()

    def test_is_plaintext_loopback_helper(self):
        assert is_plaintext_loopback("http://localhost:11434/v1")
        assert is_plaintext_loopback("http://127.0.0.1/")
        assert not is_plaintext_loopback("https://localhost/")
        assert not is_plaintext_loopback("http://example.com/")
        assert not is_plaintext_loopback("not-a-url")


class TestRemoteTranscribeRejectsPlaintext:
    def test_custom_http_rejected(self):
        import remote_transcribe as rt
        with pytest.raises(rt.RemoteTranscribeError) as ei:
            rt._resolve_base_url("custom", "http://localhost:9000/v1")
        assert "HTTPS" in str(ei.value) or "https" in str(ei.value)

    def test_custom_https_accepted(self):
        import remote_transcribe as rt
        url = rt._resolve_base_url("custom", "https://api.example.com/v1")
        assert url == "https://api.example.com/v1"


class TestLLMPolishAllowsLoopback:
    def test_custom_loopback_http_accepted(self):
        import llm_polish as llm
        url = llm._resolve_base_url("custom", "http://localhost:11434/v1")
        assert url == "http://localhost:11434/v1"

    def test_custom_http_nonloopback_rejected(self):
        import llm_polish as llm
        with pytest.raises(ValueError) as ei:
            llm._resolve_base_url("custom", "http://example.com/v1")
        assert "loopback" in str(ei.value).lower()
