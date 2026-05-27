"""Atomic JSON file I/O with corruption recovery and mtime-based caching."""
import json
import logging
import os
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import strftime
from typing import Any

log = logging.getLogger("freewispr")


def load_json(path: Path, default):
    if not path.exists():
        return default.copy() if isinstance(default, dict) else default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        backup = path.with_suffix(path.suffix + f".corrupt-{strftime('%Y%m%d-%H%M%S')}")
        try:
            shutil.copy2(path, backup)
            log.warning("Korrupt JSON i %s; backup sparad som %s", path, backup)
        except Exception as backup_error:
            log.warning("Korrupt JSON i %s; kunde inte skapa backup: %s", path, backup_error)
        log.warning("Använder standarddata efter JSON-fel i %s: %s", path, e)
        return default.copy() if isinstance(default, dict) else default
    except Exception as e:
        log.warning("Kunde inte läsa JSON från %s: %s", path, e)
        return default.copy() if isinstance(default, dict) else default


def save_json_atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            tmp_name = f.name
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
        raise


class JsonCache:
    """Reusable JSON file cache with mtime-based invalidation.

    Wraps a single JSON file with an in-memory cache that is only
    refreshed when the file's mtime changes.  Reads use ``load_json``
    and writes use ``save_json_atomic``.
    """

    def __init__(self, path: Path, default: Any = None) -> None:
        self._path = path
        self._default = default if default is not None else {}
        self._data: dict | None = None
        self._data_mtime: float = 0.0

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path:
        """The underlying file path."""
        return self._path

    def mtime(self) -> float:
        """Return the file's current mtime, or 0.0 if missing."""
        try:
            return self._path.stat().st_mtime
        except OSError:
            return 0.0

    def load(self) -> dict:
        """Return cached data, re-reading from disk only when mtime changes."""
        current_mt = self.mtime()
        if self._data is not None and current_mt == self._data_mtime:
            return self._data
        self._data = dict(load_json(self._path, self._default))
        self._data_mtime = current_mt
        return self._data

    def save(self, data: dict) -> None:
        """Write *data* atomically and update the in-memory cache."""
        save_json_atomic(self._path, data)
        self._data = data
        self._data_mtime = self.mtime()
