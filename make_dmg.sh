#!/usr/bin/env bash
# Package dist/BG Spotter.app into a drag-to-Applications disk image.
# Version comes from the built bundle, so the DMG can never disagree with the app.
set -euo pipefail
cd "$(dirname "$0")"

APP="${DIST:-dist}/BG Spotter.app"
if [ ! -d "$APP" ]; then
  echo "No app bundle found at $APP. Run ./build_app.sh first." >&2
  exit 1
fi

VERSION=$(plutil -extract CFBundleShortVersionString raw "$APP/Contents/Info.plist")
# Tag the image with the architecture it actually contains, so an Intel build can
# never be mailed out as if it were Apple Silicon (or vice versa).
ARCHS="$(lipo -archs "$APP/Contents/MacOS/BG Spotter" 2>/dev/null | tr ' ' '-' || echo unknown)"
DMG="${DIST:-dist}/BG-Spotter-${VERSION}-${ARCHS}${DMG_SUFFIX:+$DMG_SUFFIX}.dmg"
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
