#!/bin/bash
# Build BG Spotter.app — run from the repo root:  ./build_app.sh
# Output: dist/BG Spotter.app
set -euo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python
[ -x "$PY" ] || PY=python3

"$PY" assets/make_icon.py

.venv/bin/pyinstaller --noconfirm --windowed --clean \
  --name "BG Spotter" \
  --osx-bundle-identifier com.akahonaudio.bgspotter \
  --icon assets/AppIcon.icns \
  --paths src \
  src/bg_spotter/__main__.py

# Stamp human-readable metadata into the bundle's Info.plist
# 2.0.1 = mono embedded master (Pro Tools multichannel fix), unique media names,
# working GUI export path.  Keep this ahead of whatever dist/*.dmg already holds:
# a stale build carrying the same version number shipped broken once before.
APP_VERSION="2.0.1"
PLIST="dist/BG Spotter.app/Contents/Info.plist"
plutil -replace CFBundleName        -string "BG Spotter"            "$PLIST"
plutil -replace CFBundleDisplayName -string "BG Spotter"            "$PLIST"
plutil -replace CFBundleShortVersionString -string "$APP_VERSION"   "$PLIST"
plutil -replace CFBundleVersion     -string "$APP_VERSION"          "$PLIST"
plutil -replace NSHighResolutionCapable -bool true                  "$PLIST"

# Re-sign ad-hoc after plist edits so the bundle stays launchable
codesign --force --deep --sign - "dist/BG Spotter.app" 2>/dev/null || true

echo
echo "Built: dist/BG Spotter.app"
echo "Verify with: BGSPOTTER_SELFTEST=/path/to/video.mov BGSPOTTER_SELFTEST_OUT=/tmp/t.aaf \\"
echo "             './dist/BG Spotter.app/Contents/MacOS/BG Spotter'"
