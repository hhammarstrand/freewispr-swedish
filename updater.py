"""GitHub Releases update-check för freewispr-swedish.

Notis-only design: vi kollar mot ``api.github.com/.../releases/latest``,
jämför versioner med ``packaging.version`` och returnerar info om en nyare
stabil release finns. Ingen automatisk nedladdning - användaren öppnar
release-sidan i webbläsaren och installerar själv.

Säkerhetsval:
  - URL hårdkodad till ``https://api.github.com`` (ingen MITM via config).
  - Repo hårdkodat (ingen kapning via config).
  - ``html_url`` valideras att börja med rätt GitHub-prefix innan vi
    returnerar den - skydd om svaret skulle vara manipulerat.
  - Skippar helt när vi inte kör som frozen PyInstaller-exe, så
    utvecklare som kör ``python main.py`` inte spammas med notiser.
  - Alla fel sväljs och returnerar ``None``; en update-check får aldrig
    knäcka appens funktion.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from packaging.version import InvalidVersion, Version

log = logging.getLogger("freewispr")

# Hårdkodat - aldrig override via config. Förhindrar att en angripare som
# muterar config.json kan peka uppdateringschecken mot eget repo.
_REPO = "hhammarstrand/freewispr-swedish"
_API_URL = f"https://api.github.com/repos/{_REPO}/releases/latest"
_HTML_URL_PREFIX = f"https://github.com/{_REPO}/"

_CACHE_DIR = Path.home() / ".freewispr-swedish"
_CACHE_FILE = _CACHE_DIR / "update_cache.json"

# Override för utvecklare som vill testa update-flow i script-läge.
_FORCE_ENV_VAR = "FREEWISPR_FORCE_UPDATE_CHECK"


@dataclass(frozen=True)
class UpdateInfo:
    """Information om en tillgänglig uppdatering."""
    version: str          # "1.1.0" (utan v-prefix)
    tag: str              # "v1.1.0"
    url: str              # html_url till release-sidan
    published_at: str     # ISO-datum, bara för loggning


def _is_frozen() -> bool:
    """True om vi körs som PyInstaller-byggd .exe."""
    return bool(getattr(sys, "frozen", False))


def _load_cache() -> dict[str, Any]:
    """Läs cache-filen. Returnerar tom dict vid fel/avsaknad."""
    try:
        if _CACHE_FILE.is_file():
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.debug("Kunde inte läsa update-cache: %s", e)
    return {}


def _save_cache(data: dict[str, Any]) -> None:
    """Skriv cache atomiskt. Tyst vid fel - cache är inte kritiskt."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(_CACHE_FILE)
    except Exception as e:
        log.debug("Kunde inte spara update-cache: %s", e)


def _valid_url(url: str) -> bool:
    """html_url måste peka in i vårt GitHub-repo. Skydd mot manipulerade svar."""
    return isinstance(url, str) and url.startswith(_HTML_URL_PREFIX)


def _newer(latest_tag: str, current: str) -> bool:
    """True om ``latest_tag`` är en nyare version än ``current``."""
    try:
        return Version(latest_tag.lstrip("v")) > Version(current)
    except InvalidVersion:
        log.debug("Ogiltigt versionsformat: latest=%s current=%s",
                  latest_tag, current)
        return False


def _build_request(current_version: str, etag: str | None) -> urlrequest.Request:
    """Bygg HTTP-request med headers GitHub kräver."""
    headers = {
        "Accept": "application/vnd.github+json",
        # GitHub kräver User-Agent - hjälper också felsökning hos dem.
        "User-Agent": f"freewispr-swedish/{current_version}",
    }
    if etag:
        headers["If-None-Match"] = etag
    return urlrequest.Request(_API_URL, headers=headers, method="GET")


def _info_from_cache(cache: dict[str, Any],
                     current_version: str) -> UpdateInfo | None:
    """Bygg UpdateInfo från cachad data om den fortfarande är relevant."""
    last_ver = cache.get("last_known_version")
    last_url = cache.get("last_known_url")
    if not (last_ver and last_url):
        return None
    if not _valid_url(last_url):
        return None
    if not _newer(last_ver, current_version):
        return None
    return UpdateInfo(
        version=last_ver,
        tag=f"v{last_ver}" if not last_ver.startswith("v") else last_ver,
        url=last_url,
        published_at=cache.get("last_known_published_at", ""),
    )


def check_for_update(current_version: str,
                     timeout: float = 5.0,
                     force: bool = False) -> UpdateInfo | None:
    """Kontrollera om en nyare release finns på GitHub.

    Args:
        current_version: Versionssträng från ``main.__version__``.
        timeout: Sekunder att vänta på GitHub API.
        force: Om True, kör även i script-läge (utvecklartest).

    Returns:
        UpdateInfo om en nyare stabil version finns, annars None.
        Returnerar alltid None vid fel - update-check får aldrig krascha
        anroparen.
    """
    if not _is_frozen() and not force and not os.environ.get(_FORCE_ENV_VAR):
        log.debug("Update-check skippad (script-läge)")
        return None

    cache = _load_cache()
    etag = cache.get("etag")

    try:
        req = _build_request(current_version, etag)
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            body = resp.read()
            new_etag = resp.headers.get("ETag")
    except urlerror.HTTPError as e:
        if e.code == 304:
            # Inget nytt sedan senaste check - använd cache.
            log.debug("Update-check: 304 Not Modified")
            return _info_from_cache(cache, current_version)
        if e.code == 403:
            log.warning("GitHub rate limit eller forbidden: %s", e)
        else:
            log.debug("GitHub API HTTP %s: %s", e.code, e)
        return None
    except (urlerror.URLError, TimeoutError, OSError) as e:
        log.debug("Update-check nätverksfel: %s", e)
        return None
    except Exception as e:
        log.debug("Update-check oväntat fel: %s", e)
        return None

    if status != 200:
        log.debug("Update-check oväntad status: %s", status)
        return None

    try:
        data = json.loads(body.decode("utf-8"))
    except Exception as e:
        log.debug("Kunde inte parsa GitHub-svar: %s", e)
        return None

    tag = data.get("tag_name", "")
    html_url = data.get("html_url", "")
    published_at = data.get("published_at", "")

    if not tag or not _valid_url(html_url):
        log.debug("Ogiltigt release-svar: tag=%r url=%r", tag, html_url)
        return None

    # Uppdatera cache oavsett om det är nyare eller ej, så ETag funkar
    # nästa gång.
    version_clean = tag.lstrip("v")
    new_cache = {
        "etag": new_etag or "",
        "last_known_version": version_clean,
        "last_known_url": html_url,
        "last_known_published_at": published_at,
    }
    _save_cache(new_cache)

    if not _newer(tag, current_version):
        return None

    return UpdateInfo(
        version=version_clean,
        tag=tag,
        url=html_url,
        published_at=published_at,
    )
