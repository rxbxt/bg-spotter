#!/usr/bin/env bash
# Package dist/BG Spotter.app into a drag-to-Applications disk image.
# Version comes from the built bundle, so the DMG can never disagree with the app.
set -euo pipefail
cd "$(dirname "$0")"

APP="dist/BG Spotter.app"
if [ ! -d "$APP" ]; then
  echo "No app bundle found. Run ./build_app.sh first." >&2
  exit 1
fi

VERSION=$(plutil -extract CFBundleShortVersionString raw "$APP/Contents/Info.plist")
DMG="dist/BG-Spotter-${VERSION}.dmg"
STAGE="$(mktemp -d)/BG Spotter ${VERSION}"

mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

rm -f "$DMG"
hdiutil create -volname "BG Spotter ${VERSION}" \
  -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null

rm -rf "$(dirname "$STAGE")"
echo "Built: $DMG ($(du -h "$DMG" | cut -f1))  version ${VERSION}"
echo "Note: ad-hoc signed (no Developer ID). macOS 15+: double-click once, then"
echo "System Settings > Privacy & Security > Open Anyway. macOS <=14: right-click > Open."
