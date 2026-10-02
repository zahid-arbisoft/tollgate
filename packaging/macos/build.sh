#!/usr/bin/env bash
# Local macOS build: .app (ad-hoc signed, no admin needed) + zip.
# Optional: create-dmg via brew for the .dmg step (skipped if absent).
set -euo pipefail
cd "$(dirname "$0")/../.."

VERSION="${TOLLGATE_VERSION:-0.1.0}"

uv sync --extra desktop --dev
uv run pyinstaller packaging/tollgate.spec --noconfirm --clean

APP="dist/Tollgate.app"
# Ad-hoc signing works without any admin rights or developer account.
codesign --force --deep --sign - "$APP"
echo "signed (ad-hoc): $APP"

ditto -c -k --keepParent "$APP" "tollgate-$VERSION-macos-arm64.zip"
echo "zip: tollgate-$VERSION-macos-arm64.zip"

if command -v create-dmg >/dev/null 2>&1; then
  create-dmg --volname "Tollgate" --app-drag-link "Tollgate" \
    "tollgate-$VERSION.dmg" "$APP" || true
  echo "dmg: tollgate-$VERSION.dmg"
else
  echo "create-dmg not found — skipped .dmg (brew install create-dmg)"
fi
