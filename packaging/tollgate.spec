# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — per-user desktop app (macOS .app / Windows onedir exe).
# Build:  uv run pyinstaller packaging/tollgate.spec --noconfirm --clean

import sys
from os.path import join

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Version single-sourced from pyproject.toml (keeps .app bundle metadata honest).
def _version():
    import re
    from pathlib import Path

    pyproject = Path(SPECPATH) / ".." / "pyproject.toml"
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(), re.M)
    return m.group(1) if m else "0.0.0"

VERSION = _version()

# Data files that live inside the package: dashboard static build, vendored
# price map, alembic migrations (env.py + templates are loaded dynamically).
datas = collect_data_files("tollgate", include_py_files=True)
hiddenimports = collect_submodules("tollgate")
hiddenimports += [
    # loaded lazily / dynamically — invisible to static analysis
    "aiosqlite",  # SQLAlchemy async engine resolves the DBAPI by URL string
    "greenlet",  # SQLAlchemy async bridge
    # uvicorn loads its workers dynamically
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.auto",
    # keyring picks backends via entry points
    "keyring.backends.macOS",
    "keyring.backends.Windows",
]

a = Analysis(
    [join(SPECPATH, "entrypoint.py")],
    pathex=[SPECPATH + "/.."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="Tollgate",
    debug=False,
    console=False,  # GUI app; CLI args still work (stdout just isn't shown)
    strip=False,
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Tollgate",
)

if sys.platform == "darwin":
    bundle = BUNDLE(
        coll,
        name="Tollgate.app",
        bundle_identifier="dev.tollgate.app",
        info_plist={
            "CFBundleDisplayName": "Tollgate",
            "CFBundleShortVersionString": VERSION,
            "NSHighResolutionCapable": True,
        },
    )
