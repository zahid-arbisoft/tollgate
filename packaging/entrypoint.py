"""PyInstaller entrypoint: double-click → desktop window; CLI args pass through.

`Tollgate.exe serve`, `Tollgate.app/Contents/MacOS/Tollgate version` etc. behave
like the `tollgate` CLI. No arguments → the desktop shell.
"""

import sys

from tollgate.cli import app

if len(sys.argv) <= 1:
    sys.argv = ["tollgate", "desktop"]

app()
