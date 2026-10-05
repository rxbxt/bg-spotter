# BG Spotter 2.0

Edit-point AAF guide-track generator for post-production sound.
Feed it a picture-locked video, pick one or more overlap sizes (1–6 frames),
and it exports an AAF with spotted-out guide tracks: for each selected size N,
a track pair **"Spots - N Frame Overlap A" / "... B"** whose clips alternate and
overlap by exactly N frames at every hard cut. Silence regions between clips
import into Pro Tools as true digital silence — no cleanup needed.

By **Akahon Audio LLC** · composerrob.com

## Using the app

Drag `BG Spotter.app` to your Applications folder and launch it.
(First launch of an unsigned build: right-click → **Open** → **Open**, because
Gatekeeper warns about apps not downloaded from the App Store.)

1. Drop a video (`.mov`, `.mp4`, `.mxf`) or press **Browse…**
2. Tick any combination of overlap sizes — each adds an A/B track pair
3. Frame rate / start timecode auto-fill from the file; override if needed
4. Press **Spot & Export AAF**

Import the resulting `.aaf` into Pro Tools: the guide tracks land on the
picture timeline with the same start timecode as the source.

No ffmpeg or Python install required — everything is bundled. (If `ffprobe`
happens to be installed, it's used for richer metadata; otherwise a built-in
OpenCV probe takes over.)

## Building from source

Requires Python 3.11+ and macOS (Apple Silicon or Intel):

```
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
./build_app.sh          # → dist/BG Spotter.app
pytest                  # 71 tests
```

The built app can be smoke-tested headlessly:

```
BGSPOTTER_SELFTEST=/path/to/video.mov BGSPOTTER_SELFTEST_OUT=/tmp/t.aaf \
  "./dist/BG Spotter.app/Contents/MacOS/BG Spotter"
```

## Sharing with collaborators

`dist/BG Spotter.app` is ad-hoc signed: it runs on any Mac, but recipients
must right-click → Open the first time (macOS quarantine). For frictionless
distribution, sign + notarize with an Apple Developer ID:

```
codesign --force --deep -s "Developer ID Application: Your Name (TEAMID)" "BG Spotter.app"
xcrun notarytool submit BG Spotter.zip --apple-id you@example.com --password <app-pw> --team-id TEAMID --staple
```

## What changed in 2.0

- **Multi-overlap export**: 1–6 frame sizes, any combination; track names
  `Spots - N Frame Overlap A/B`. Overlap is centred on each cut (odd N splits
  the half-frame at sample accuracy). Dissolves span their full transition.
- **Footsteps feature removed** (with YOLO/Ollama dependencies).
- **Silence fix**: the silent master is now embedded through pyaaf2's
  canonical `import_audio_essence()` path with a proper SourceClip file-mob
  structure. The old hand-rolled Filler-based file mob made Pro Tools decode
  garbage into every clip (the "loud glitch" you fixed with −96 dB gain).
- **New single-window UI** (red/black), drag-and-drop, live track preview,
  auto-named output, progress reporting.
- **Packaged as a standalone .app** — no Python needed on target machines.
