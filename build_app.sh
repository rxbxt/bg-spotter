#!/bin/bash
# Build BG Spotter.app — run from the repo root:  ./build_app.sh
#
# Environment overrides:
#   PY=...           interpreter to build with          (default .venv/bin/python)
#   TARGET_ARCH=...  arm64 | x86_64 | universal2        (default: interpreter's own)
#   DIST=...         output directory                   (default dist)
#
# PyInstaller cannot cross-compile: the produced binary matches the architecture
# the *interpreter* actually runs as. To build an Intel app on Apple Silicon, use
# an x86_64 interpreter, e.g.
#   arch -x86_64 /usr/bin/python3 -m venv .venv-intel
#   arch -x86_64 .venv-intel/bin/pip install -e ".[dev]"
#   PY=.venv-intel/bin/python TARGET_ARCH=x86_64 DIST=dist-intel ./build_app.sh
set -euo pipefail
cd "$(dirname "$0")"

PY=${PY:-.venv/bin/python}
[ -x "$PY" ] || PY=python3
DIST=${DIST:-dist}

# bash 3.2 (macOS default) trips on "${arr[@]}" when empty under set -u
ARCH_ARGS=""
ARCH_PREFIX=""
if [ -n "${TARGET_ARCH:-}" ]; then
  ARCH_ARGS="--target-arch $TARGET_ARCH"
  # A venv created from a universal binary still launches as the host arch, so
  # ask for the requested one explicitly (this is what makes an Intel build from
  # Apple Silicon produce x86_64 code rather than silently reusing arm64).
  if [ "$(uname -s)" = "Darwin" ]; then
    ARCH_PREFIX="arch -$TARGET_ARCH"
  fi
fi

# shellcheck disable=SC2086
$ARCH_PREFIX "$PY" assets/make_icon.py

# shellcheck disable=SC2086
$ARCH_PREFIX "$PY" -m PyInstaller --noconfirm --windowed --clean \
  --name "BG Spotter" \
  --distpath "$DIST" \
  $ARCH_ARGS \
  --osx-bundle-identifier com.akahonaudio.bgspotter \
  --icon assets/AppIcon.icns \
  --paths src \
  src/bg_spotter/__main__.py

# Stamp human-readable metadata into the bundle's Info.plist
# Version comes from pyproject.toml — one source of truth. The Oct 4 incident was
# a stale build carrying the same version as the good one; drift is the enemy here.
APP_VERSION="$(sed -n 's/^version = "\([^"]*\)".*/\1/p' pyproject.toml | head -1)"
[ -n "$APP_VERSION" ] || { echo "Could not read version from pyproject.toml" >&2; exit 1; }
PLIST="$DIST/BG Spotter.app/Contents/Info.plist"
plutil -replace CFBundleName        -string "BG Spotter"            "$PLIST"
plutil -replace CFBundleDisplayName -string "BG Spotter"            "$PLIST"
plutil -replace CFBundleShortVersionString -string "$APP_VERSION"   "$PLIST"
plutil -replace CFBundleVersion     -string "$APP_VERSION"          "$PLIST"
plutil -replace NSHighResolutionCapable -bool true                  "$PLIST"

# Record what we actually produced, so an Intel build can never be mistaken for
# an Apple Silicon one (or vice versa) after the fact.
BUILT_ARCHS="$(lipo -archs "$DIST/BG Spotter.app/Contents/MacOS/BG Spotter" 2>/dev/null || echo unknown)"
plutil -replace CFBundleGetInfoString -string "BG Spotter $APP_VERSION ($BUILT_ARCHS)" "$PLIST"

# Re-sign ad-hoc after plist edits so the bundle stays launchable
codesign --force --deep --sign - "$DIST/BG Spotter.app" 2>/dev/null || true

echo
echo "Built: $DIST/BG Spotter.app  ($BUILT_ARCHS)"
echo "Verify with: BGSPOTTER_SELFTEST=/path/to/video.mov BGSPOTTER_SELFTEST_OUT=/tmp/t.aaf \\"
echo "             '$DIST/BG Spotter.app/Contents/MacOS/BG Spotter'"
