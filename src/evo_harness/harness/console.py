from __future__ import annotations

import os
import sys


def _reconfigure_stream(stream: object, *, errors: str) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if not callable(reconfigure):
        return
    try:
        reconfigure(encoding="utf-8", errors=errors)
    except Exception:
        pass


def enable_utf8_console() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleCP(65001)
        kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass
    _reconfigure_stream(sys.stdin, errors="replace")
    _reconfigure_stream(sys.stdout, errors="replace")
    _reconfigure_stream(sys.stderr, errors="backslashreplace")
