# BG Spotter 2.1

Edit-point AAF guide-track generator for post-production sound.
Feed it a picture-locked video, pick one or more overlap sizes (**0**–6 frames),
and it exports an AAF with spotted-out guide tracks: for each selected size N > 0,
a track pair **"Spots - N Frame Overlap A" / "... B"** whose clips alternate and
overlap by exactly N frames at every hard cut; **0 frames** adds no handle, so
clips meet exactly at each edit ("**Edit Points Only A/B**"). Silence regions
between clips import into Pro Tools as true digital silence — no cleanup needed.

Runs on Apple Silicon Macs, Intel Macs (macOS 13+) and Windows 10/11.

By **Akahon Audio LLC** · composerrob.com

## Using the app

Drag `BG Spotter.app` to your Applications folder and launch it.
(First launch of an unsigned build: on macOS 15+, double-click once, then
**System Settings → Privacy & Security → Open Anyway**; on macOS 14 or
earlier, right-click → **Open**. One time only — see *Sharing* below.)

1. Drop a video (`.mov`, `.mp4`, `.mxf`) or press **Browse…**
2. Tick any combination of overlap sizes — each adds an A/B track pair.
   **0 frames** spots the edit points themselves: clips meet exactly at each cut
   with no handle, labelled `Edit Points Only A/B` in Pro Tools.
3. Frame rate / start timecode auto-fill from the file; override if needed
4. Press **Spot & Export AAF**

Import the resulting `.aaf` into Pro Tools: the guide tracks land on the
picture timeline with the same start timecode as the source.

No ffmpeg or Python install required — everything is bundled. (If `ffprobe`
happens to be installed, it's used for richer metadata; otherwise a built-in
OpenCV probe takes over.)

## Building from source

Requires Python 3.9+ (validated on 3.9/Intel and 3.12/Apple Silicon). PySide6
needs macOS 13+ or Windows 10+:

```
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
pytest                  # 92 tests
./build_app.sh          # → dist/BG Spotter.app
./make_dmg.sh           # → dist/BG-Spotter-<version>-<arch>.dmg
```

PyInstaller **cannot cross-compile** — a bundle's architecture is whatever the
interpreter runs as. To ship both Mac flavours from one Apple Silicon machine,
build the Intel slice under Rosetta (no installer needed; macOS ships a
universal `/usr/bin/python3`):

```
arch -x86_64 /usr/bin/python3 -m venv .venv-intel
arch -x86_64 .venv-intel/bin/pip install -e ".[dev]"
PY=.venv-intel/bin/python TARGET_ARCH=x86_64 DIST=dist-intel ./build_app.sh
DIST=dist-intel ./make_dmg.sh      # → dist-intel/BG-Spotter-<version>-x86_64.dmg
```

A single universal2 app is impossible: `opencv-python` has never published a
universal2 wheel, so the two slices must ship as separate images.

### Windows

On a Windows 10/11 (64-bit) machine — creates its own venv, runs the tests, then
zips the result:

```
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
# → dist\BG-Spotter-<version>-win64.zip
```

No PC handy? The `build` GitHub Actions workflow runs the suite on Windows and
macOS and uploads a Windows zip plus arm64 and Intel DMGs as artifacts.

The built app can be smoke-tested headlessly:

```
BGSPOTTER_SELFTEST=/path/to/video.mov BGSPOTTER_SELFTEST_OUT=/tmp/t.aaf \
  "./dist/BG Spotter.app/Contents/MacOS/BG Spotter"
```

## Sharing with collaborators

Send the file that matches the recipient's machine — an image built for one CPU
will not run on the other, and PyInstaller cannot produce a combined binary:

| Recipient | Send |
| --- | --- |
| Apple Silicon Mac (M1–M4) | `dist/BG-Spotter-<version>-arm64.dmg` |
| Intel Mac (macOS 13 Ventura or later) | `dist-intel/BG-Spotter-<version>-x86_64.dmg` |
| Windows 10/11, 64-bit | `dist\BG-Spotter-<version>-win64.zip` |

Unsure which Mac they have? Click the Apple menu (top-left) → **About This
Mac**: "Chip: Apple M…" is Apple Silicon; "Processor: Intel …" is Intel. Each
DMG also records its architecture in the file name and in the bundle's version
string.

Builds are ad-hoc signed — no Apple Developer ID, so they can't be notarized.
They run fine on any Mac, but macOS Gatekeeper blocks the first launch:

- **macOS 14 and earlier:** right-click the app → **Open** → **Open**.
- **macOS 15 (Sequoia) or later:** double-click it once (it will refuse), then
  open **System Settings → Privacy & Security**, scroll to the Security
  section, click **Open Anyway**, and confirm. One time only per machine.

If you zip/dropbox the app, macOS tags it as quarantined — that's what
triggers the prompt. Copying it locally (e.g. from a USB drive formatted
Mac OS Extended) skips the prompt entirely.

Windows builds are unsigned too: SmartScreen may show "Windows protected your
PC" on first run — **More info → Run anyway**, once per machine.

For frictionless distribution later, an Apple Developer ID ($99/yr) enables:

```
codesign --force --deep -s "Developer ID Application: Your Name (TEAMID)" "BG Spotter.app"
xcrun notarytool submit BG Spotter.zip --apple-id you@example.com --password <app-pw> --team-id TEAMID --staple
```

## What changed in 2.1

- **Ticking regions fixed.** Pro Tools logged `Audio file "…" is multi-channel.
  Only the first channel will be referenced by Pro Tools.` against every embedded
  clip: the silent master was a **stereo** WAV, and on that path Pro Tools never
  filled the region buffers, so they replayed process memory (a consolidated
  bounce held four distinct non-zero constants, none of which occur anywhere in
  the AAF). The master is now **mono** (`MASTER_CHANNELS = 1`, `BlockAlign = 3`)
  and every region imports as true digital silence.
- **Export ran again.** `_on_go()` raised on every press — `QMainWindow.layout()`
  returns a `QMainWindowLayout`, which has no `insertWidget`. The window now keeps
  explicit root/content layout handles, so the button starts the job instead of
  killing the process.
- **0-frame overlap option** — spot edit points only (`Edit Points Only A/B`).
- **Intel Mac and Windows builds.** All OS-specific behaviour moved into
  `platform_utils.py` (log directory, Reveal in Finder / Explorer), and
  `scenedetect`'s position values are normalised so its 0.6 API (what Python 3.9
  installs) works as well as 0.7.
- **Layout no longer collapses**: the content scrolls, inputs keep a minimum
  height, and the Reveal button is created once instead of adding a row per export.
- Version numbers come from `pyproject.toml` in both build scripts, and DMG names
  carry the architecture inside them.

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
