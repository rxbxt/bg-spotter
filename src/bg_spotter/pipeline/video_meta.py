"""ffprobe-based video metadata extraction."""

import json
import subprocess
from dataclasses import dataclass

from bg_spotter.config import FPS_RATES, FPS_NOMINAL, SAMPLE_RATE


@dataclass
class VideoMeta:
    path: str
    fps_string: str           # canonical key into FPS_RATES / FPS_NOMINAL
    fps_rational: tuple[int, int]  # (numerator, denominator)
    drop_frame: bool
    start_tc: str             # HH:MM:SS:FF
    duration_frames: int
    total_samples: int        # duration_frames → 48 kHz samples


def probe_video(path: str) -> VideoMeta:
    """Return a VideoMeta for the given video file.

    Uses ffprobe when available (best metadata, incl. embedded timecode);
    falls back to OpenCV — which ships with the app — so the application
    works on machines without ffmpeg installed.
    """
    try:
        return _probe_ffprobe(path)
    except Exception:
        return _probe_opencv(path)


def _probe_opencv(path: str) -> VideoMeta:
    """OpenCV fallback probe: fps + frame count, default 01:00:00:00 start."""
    import cv2

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video file: {path}")
    try:
        fps_num = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        cap.release()

    if fps_num <= 0 or frame_count <= 0:
        raise RuntimeError(f"Could not read video metadata from: {path}")

    # Snap to the nearest supported rate (handles 23.976/29.97 float drift)
    best_label, best_err = "24", float("inf")
    for label, (n, d) in FPS_RATES.items():
        err = abs(n / d - fps_num)
        if err < best_err:
            best_label, best_err = label, err
    fps_string = best_label
    fps_rational = FPS_RATES[fps_string]
    drop_frame = False  # undetectable without container TC metadata

    from bg_spotter.pipeline.timing import frames_to_samples
    total_samples = frames_to_samples(frame_count, fps_string, drop_frame)
    sep = ":"
    return VideoMeta(
        path=path,
        fps_string=fps_string,
        fps_rational=fps_rational,
        drop_frame=drop_frame,
        start_tc=f"01:00:00{sep}00",
        duration_frames=frame_count,
        total_samples=total_samples,
    )


def _probe_ffprobe(path: str) -> VideoMeta:
    """Run ffprobe and return a VideoMeta for the given video file."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    info = json.loads(result.stdout)

    video_stream = next(
        s for s in info.get("streams", []) if s.get("codec_type") == "video"
    )

    # Frame rate
    r_frame_rate = video_stream.get("r_frame_rate", "24/1")
    num_str, den_str = r_frame_rate.split("/")
    fps_num, fps_den = int(num_str), int(den_str)

    fps_string = _detect_fps_string(fps_num, fps_den)
    drop_frame = _detect_drop_frame(info, video_stream)

    # Duration in frames
    duration_str = video_stream.get("duration") or info.get("format", {}).get("duration", "0")
    duration_sec = float(duration_str)
    # Round to nearest frame to avoid off-by-one from container imprecision
    nom_fps = FPS_NOMINAL[fps_string]
    duration_frames = round(duration_sec * fps_num / fps_den)

    # Total samples at 48 kHz
    from bg_spotter.pipeline.timing import frames_to_samples
    total_samples = frames_to_samples(duration_frames, fps_string, drop_frame)

    # Start timecode
    start_tc = _extract_start_tc(info, video_stream, fps_string, drop_frame)

    return VideoMeta(
        path=path,
        fps_string=fps_string,
        fps_rational=(fps_num, fps_den),
        drop_frame=drop_frame,
        start_tc=start_tc,
        duration_frames=duration_frames,
        total_samples=total_samples,
    )


def _detect_fps_string(num: int, den: int) -> str:
    """Map a raw fps fraction to the canonical fps label."""
    # Normalise common pairs
    ratio = num / den
    for label, (n, d) in FPS_RATES.items():
        if abs(n / d - ratio) < 0.001:
            return label
    # Fallback: construct a label and use the nearest known rate
    return "24"


def _detect_drop_frame(info: dict, video_stream: dict) -> bool:
    """Heuristic: look for drop-frame markers in container metadata."""
    timecode = _raw_tc_string(info, video_stream)
    if timecode:
        return ";" in timecode
    # 29.97 material is almost always drop-frame in US broadcast
    r = video_stream.get("r_frame_rate", "")
    if r in ("30000/1001",):
        return True
    return False


def _raw_tc_string(info: dict, video_stream: dict) -> str | None:
    """Find a timecode string anywhere in the ffprobe output."""
    for key in ("timecode", "time_code"):
        val = video_stream.get("tags", {}).get(key)
        if val:
            return val
    fmt_tags = info.get("format", {}).get("tags", {})
    for key in ("timecode", "time_code", "TIMECODE"):
        val = fmt_tags.get(key)
        if val:
            return val
    return None


def _extract_start_tc(info: dict, video_stream: dict, fps_string: str, drop_frame: bool) -> str:
    raw = _raw_tc_string(info, video_stream)
    if raw:
        return raw
    sep = ";" if drop_frame else ":"
    nom = FPS_NOMINAL[fps_string]
    return f"01:00:00{sep}00"
