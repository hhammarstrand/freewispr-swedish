"""Tester för update-checken mot GitHub Releases.

Vi mockar hela urllib-anropet så testerna inte rör nätverket.
"""
from __future__ import annotations

import json
from unittest.mock import patch
from urllib import error as urlerror

import pytest

import updater
from updater import UpdateInfo, check_for_update


# ---------------------------------------------------------------- helpers

class _FakeResponse:
    """Mimicry av context-manager-svar från urlopen()."""

    def __init__(self, status: int = 200, body: bytes = b"",
                 etag: str | None = None):
        self.status = status
        self._body = body
        self.headers = {"ETag": etag} if etag else {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _release_body(tag: str = "v1.1.0",
                  url: str | None = None,
                  published_at: str = "2026-06-01T10:00:00Z") -> bytes:
    """Bygg ett JSON-svar som GitHub skulle skicka."""
    if url is None:
        url = f"https://github.com/hhammarstrand/freewispr-swedish/releases/tag/{tag}"
    return json.dumps({
        "tag_name": tag,
        "html_url": url,
        "published_at": published_at,
        "prerelease": False,
        "draft": False,
    }).encode("utf-8")


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """Använd temp-dir för cache och låtsas vara frozen."""
    monkeypatch.setattr(updater, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(updater, "_CACHE_FILE", tmp_path / "update_cache.json")
    monkeypatch.setattr(updater, "_is_frozen", lambda: True)
    yield tmp_path


# ---------------------------------------------------------------- tests

def test_update_available_returns_info(isolated_cache):
    with patch.object(updater.urlrequest, "urlopen",
                      return_value=_FakeResponse(200, _release_body("v1.1.0"),
                                                 etag='W/"abc"')):
        info = check_for_update("1.0.0")
    assert isinstance(info, UpdateInfo)
    assert info.version == "1.1.0"
    assert info.tag == "v1.1.0"
    assert info.url.startswith("https://github.com/hhammarstrand/freewispr-swedish/")


def test_same_version_returns_none(isolated_cache):
    with patch.object(updater.urlrequest, "urlopen",
                      return_value=_FakeResponse(200, _release_body("v1.0.0"))):
        info = check_for_update("1.0.0")
    assert info is None


def test_higher_local_version_returns_none(isolated_cache):
    """Dev-build > release → ingen notis."""
    with patch.object(updater.urlrequest, "urlopen",
                      return_value=_FakeResponse(200, _release_body("v1.0.0"))):
        info = check_for_update("2.0.0")
    assert info is None


def test_invalid_version_tag_returns_none(isolated_cache):
    with patch.object(updater.urlrequest, "urlopen",
                      return_value=_FakeResponse(200, _release_body("latest"))):
        info = check_for_update("1.0.0")
    assert info is None


def test_etag_saved_on_first_call(isolated_cache):
    with patch.object(updater.urlrequest, "urlopen",
                      return_value=_FakeResponse(200, _release_body("v1.1.0"),
                                                 etag='W/"xyz"')):
        check_for_update("1.0.0")
    cache = json.loads((isolated_cache / "update_cache.json").read_text("utf-8"))
    assert cache["etag"] == 'W/"xyz"'
    assert cache["last_known_version"] == "1.1.0"


def test_etag_sent_on_subsequent_call(isolated_cache):
    # Förladda cache med ETag.
    (isolated_cache / "update_cache.json").write_text(json.dumps({
        "etag": 'W/"prev"',
        "last_known_version": "1.1.0",
        "last_known_url": "https://github.com/hhammarstrand/freewispr-swedish/releases/tag/v1.1.0",
    }), encoding="utf-8")

    captured = {}

    def fake_urlopen(req, timeout):
        captured["if_none_match"] = req.headers.get("If-none-match")
        return _FakeResponse(200, _release_body("v1.2.0"), etag='W/"new"')

    with patch.object(updater.urlrequest, "urlopen", side_effect=fake_urlopen):
        check_for_update("1.0.0")
    assert captured["if_none_match"] == 'W/"prev"'


def test_304_uses_cached_info(isolated_cache):
    (isolated_cache / "update_cache.json").write_text(json.dumps({
        "etag": 'W/"prev"',
        "last_known_version": "1.1.0",
        "last_known_url": "https://github.com/hhammarstrand/freewispr-swedish/releases/tag/v1.1.0",
    }), encoding="utf-8")

    err = urlerror.HTTPError(updater._API_URL, 304, "Not Modified", {}, None)
    with patch.object(updater.urlrequest, "urlopen", side_effect=err):
        info = check_for_update("1.0.0")
    assert info is not None
    assert info.version == "1.1.0"


def test_304_returns_none_when_cache_not_newer(isolated_cache):
    (isolated_cache / "update_cache.json").write_text(json.dumps({
        "etag": 'W/"prev"',
        "last_known_version": "0.9.0",  # äldre än current
        "last_known_url": "https://github.com/hhammarstrand/freewispr-swedish/releases/tag/v0.9.0",
    }), encoding="utf-8")

    err = urlerror.HTTPError(updater._API_URL, 304, "Not Modified", {}, None)
    with patch.object(updater.urlrequest, "urlopen", side_effect=err):
        info = check_for_update("1.0.0")
    assert info is None


def test_network_error_returns_none(isolated_cache):
    with patch.object(updater.urlrequest, "urlopen",
                      side_effect=urlerror.URLError("DNS-fel")):
        info = check_for_update("1.0.0")
    assert info is None


def test_rate_limit_403_returns_none(isolated_cache, caplog):
    err = urlerror.HTTPError(updater._API_URL, 403, "Forbidden", {}, None)
    with patch.object(updater.urlrequest, "urlopen", side_effect=err):
        info = check_for_update("1.0.0")
    assert info is None


def test_external_url_rejected(isolated_cache):
    """Manipulerat html_url ska avvisas - skydd mot förgiftade svar."""
    body = _release_body("v1.1.0", url="https://evil.example.com/phish")
    with patch.object(updater.urlrequest, "urlopen",
                      return_value=_FakeResponse(200, body)):
        info = check_for_update("1.0.0")
    assert info is None


def test_skipped_when_not_frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(updater, "_CACHE_FILE", tmp_path / "update_cache.json")
    monkeypatch.setattr(updater, "_is_frozen", lambda: False)
    monkeypatch.delenv(updater._FORCE_ENV_VAR, raising=False)

    called = {"v": False}

    def fake_urlopen(*a, **kw):
        called["v"] = True
        return _FakeResponse(200, _release_body("v1.1.0"))

    with patch.object(updater.urlrequest, "urlopen", side_effect=fake_urlopen):
        info = check_for_update("1.0.0")
    assert info is None
    assert called["v"] is False, "urlopen ska inte anropas i script-läge"


def test_force_bypasses_frozen_skip(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(updater, "_CACHE_FILE", tmp_path / "update_cache.json")
    monkeypatch.setattr(updater, "_is_frozen", lambda: False)

    with patch.object(updater.urlrequest, "urlopen",
                      return_value=_FakeResponse(200, _release_body("v1.1.0"))):
        info = check_for_update("1.0.0", force=True)
    assert info is not None
    assert info.version == "1.1.0"


def test_env_var_bypasses_frozen_skip(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(updater, "_CACHE_FILE", tmp_path / "update_cache.json")
    monkeypatch.setattr(updater, "_is_frozen", lambda: False)
    monkeypatch.setenv(updater._FORCE_ENV_VAR, "1")

    with patch.object(updater.urlrequest, "urlopen",
                      return_value=_FakeResponse(200, _release_body("v1.1.0"))):
        info = check_for_update("1.0.0")
    assert info is not None


def test_corrupt_json_returns_none(isolated_cache):
    with patch.object(updater.urlrequest, "urlopen",
                      return_value=_FakeResponse(200, b"<html>nope</html>")):
        info = check_for_update("1.0.0")
    assert info is None


def test_user_agent_header_sent(isolated_cache):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["ua"] = req.headers.get("User-agent")
        return _FakeResponse(200, _release_body("v1.0.0"))

    with patch.object(updater.urlrequest, "urlopen", side_effect=fake_urlopen):
        check_for_update("1.2.3")
    assert captured["ua"] == "freewispr-swedish/1.2.3"
