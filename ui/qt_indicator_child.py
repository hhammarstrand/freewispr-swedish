"""Child-process entry point for the Qt floating indicator.

This module intentionally does not import ``main``. The indicator process must
never bootstrap the full tray app, otherwise a failed argv/venv handoff can
recursively spawn new app instances.
"""
from __future__ import annotations

import sys

from ui.qt_indicator import run_indicator_stdio


def main() -> int:
    follow_mouse = len(sys.argv) < 2 or sys.argv[1] != "0"
    run_indicator_stdio(follow_mouse)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
