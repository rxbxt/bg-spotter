from pathlib import Path

SAMPLE_RATE = 48000
BIT_DEPTH = 24
CHANNELS = 2

# Channels of the embedded guide-track master.  MUST be 1: Pro Tools logs
# "Audio file … is multi-channel. Only the first channel will be referenced by
# Pro Tools." for interleaved stereo essence and leaves the imported regions
# filled with its own uninitialised memory instead of the embedded samples
# (the audible ticking).  Guide tracks are mono markers, so mono is also the
# correct format — and it halves the embedded payload on long reels.
MASTER_CHANNELS = 1

SUPPORTED_VIDEO_EXTS = {".mov", ".mxf", ".mp4"}

# Overlap sizes (frames) offered in the UI. Each selected size produces
# two tracks: "Spots - N Frame Overlap A" / "... B".
OVERLAP_CHOICES = [1, 2, 3, 4, 5, 6]
DEFAULT_OVERLAPS = [2]

# Maps fps label → (numerator, denominator) for the actual frame rate
FPS_RATES: dict[str, tuple[int, int]] = {
    "15":     (15, 1),
    "23.976": (24000, 1001),
    "24":     (24, 1),
    "25":     (25, 1),
    "29.97 NDF": (30000, 1001),
    "29.97 DF":  (30000, 1001),
    "30":     (30, 1),
}

# Nominal integer fps used for drop-frame TC arithmetic
FPS_NOMINAL: dict[str, int] = {
    "15":     15,
    "23.976": 24,
    "24":     24,
    "25":     25,
    "29.97 NDF": 30,
    "29.97 DF":  30,
    "30":     30,
}

# Cut detection
CONTENT_DETECTOR_THRESHOLD = 27.0  # PySceneDetect default

APP_NAME = "BG Spotter"
COMPANY_NAME = "Akahon Audio LLC"
WEBSITE = "https://www.composerrob.com"
