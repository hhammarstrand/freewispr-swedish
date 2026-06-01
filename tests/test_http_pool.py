"""L2: shared keep-alive pool — connection reuse per host."""
from __future__ import annotations

import importlib


def test_connection_for_reuses_same_host_opens_new_for_other():
    hp = importlib.reload(importlib.import_module("http_pool"))
    hp.reset()
    try:
        k1, c1, reused1 = hp.connection_for("https://api.example.com/v1/a", 5.0)
        assert reused1 is False
        # Second call to the same origin reuses the very same connection object.
        k2, c2, reused2 = hp.connection_for("https://api.example.com/v1/b", 5.0)
        assert reused2 is True
        assert c2 is c1
        assert k2 == k1
        # A different host opens a fresh connection.
        _k3, c3, reused3 = hp.connection_for("https://other.example.com/v1", 5.0)
        assert reused3 is False
        assert c3 is not c1
    finally:
        hp.reset()


def test_reset_clears_pool():
    hp = importlib.reload(importlib.import_module("http_pool"))
    hp.connection_for("https://api.example.com/v1", 5.0)
    hp.reset()
    # After reset the next lookup is a fresh (non-reused) connection.
    _k, _c, reused = hp.connection_for("https://api.example.com/v1", 5.0)
    assert reused is False
    hp.reset()
