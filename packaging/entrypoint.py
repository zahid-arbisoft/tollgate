"""PyInstaller entrypoint: double-click → desktop window; CLI args pass through.

`Tollgate.exe serve`, `Tollgate.app/Contents/MacOS/Tollgate version` etc. behave
like the `tollgate` CLI. No arguments → the desktop shell.
"""

import sys

# Frozen windowed apps have no console: stdout/stderr may be None, and a real
# Windows console speaks cp1252 — either way, any non-ASCII byte in a log line
# would crash the app (UnicodeEncodeError inside logging's error handler).
# Route everything through UTF-8 with replacement before importing anything.
for _name in ("stdout", "stderr"):
    _stream = getattr(sys, _name)
    if _stream is None:
        import os

        setattr(
            sys,
            _name,
            open(os.devnull, "w", encoding="utf-8", errors="replace"),
        )
    else:
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass

from tollgate.cli import app

if len(sys.argv) <= 1:
    sys.argv = ["tollgate", "desktop"]

app()
