from pathlib import Path

SAMPLE_RATE = 48000
BIT_DEPTH = 24
CHANNELS = 2

SUPPORTED_VIDEO_EXTS = {".mov", ".mxf", ".mp4"}

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

# YOLO walking heuristic — normalised to frame dimensions
ANKLE_VAR_THRESHOLD = 0.0003       # variance of normalised ankle-y over 1-sec window
HIP_DISPLACEMENT_THRESHOLD = 0.02  # |hip_x_end - hip_x_start| as fraction of width
ANKLE_CORR_THRESHOLD = -0.2        # max cross-correlation to be considered alternating
WALKING_WINDOW_SEC = 1.0
MIN_WALKING_DURATION_SEC = 0.5

MODELS_DIR = Path(__file__).parent.parent.parent.parent / "models"
YOLO_MODEL_ID = "yolo11n-pose.pt"

OLLAMA_BASE_URL = "http://localhost:11434"
VLM_PROMPT = (
    "How many people in this image are currently walking? "
    "Reply with a single integer only."
)
