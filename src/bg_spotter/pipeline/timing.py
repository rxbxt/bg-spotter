"""Frame ↔ sample conversion and timecode arithmetic.

All public functions operate with 48 kHz sample counts as the canonical unit.
Drop-frame timecode follows the SMPTE 12M-1-2008 standard (2 frames dropped
per minute, except every 10th minute) for 29.97 fps material.
"""
from fractions import Fraction

from bg_spotter.config import FPS_RATES, FPS_NOMINAL, SAMPLE_RATE

_DROPPED_PER_MINUTE = 2  # DF frames dropped at each non-10th-minute boundary


def _fps_frac(fps_string: str) -> Fraction:
    n, d = FPS_RATES[fps_string]
    return Fraction(n, d)


def frames_to_samples(frame_count: int | float, fps_string: str, drop_frame: bool = False) -> int:
    """Convert a frame count to a 48 kHz sample count.

    Uses exact rational arithmetic so fractional frame counts (e.g. overlap/2
    when overlap is an odd integer) never accumulate floating-point error.
    """
    fps = _fps_frac(fps_string)
    return round(Fraction(frame_count) * SAMPLE_RATE / fps)


def samples_to_frames(sample_count: int, fps_string: str, drop_frame: bool = False) -> int:
    """Convert a 48 kHz sample count to the nearest frame index."""
    fps = _fps_frac(fps_string)
    return round(Fraction(sample_count) * fps / SAMPLE_RATE)


# ---------------------------------------------------------------------------
# Timecode ↔ frame index
# ---------------------------------------------------------------------------

def tc_to_frame_index(tc: str, fps_string: str, drop_frame: bool = False) -> int:
    """Convert HH:MM:SS:FF (or HH:MM:SS;FF) timecode to an absolute frame index.

    The frame index is the zero-based count of actual media frames from the
    start of the reel, independent of TC numbering conventions.
    """
    clean = tc.replace(";", ":")
    parts = clean.split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid timecode: {tc!r}")
    h, m, s, f = (int(p) for p in parts)

    nom = FPS_NOMINAL[fps_string]
    frame_index = (h * 3600 + m * 60 + s) * nom + f

    if drop_frame:
        # Subtract the cumulative dropped-frame offsets.
        # DF drops 2 frame numbers at the start of each minute except every 10th.
        total_minutes = h * 60 + m
        frame_index -= _DROPPED_PER_MINUTE * (total_minutes - total_minutes // 10)

    return frame_index


def frame_index_to_tc(frame_index: int, fps_string: str, drop_frame: bool = False) -> str:
    """Convert an absolute frame index back to HH:MM:SS:FF timecode."""
    nom = FPS_NOMINAL[fps_string]

    if not drop_frame:
        ff = frame_index % nom
        rem = frame_index // nom
        ss = rem % 60
        rem //= 60
        mm = rem % 60
        hh = rem // 60
        return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"

    # Drop-frame reconstruction.
    D = _DROPPED_PER_MINUTE
    frames_per_10min = nom * 60 * 10 - D * 9   # e.g. 17982 for 29.97 DF
    frames_per_1min  = nom * 60                  # e.g. 1800

    hh = frame_index // (frames_per_10min * 6)
    remaining = frame_index % (frames_per_10min * 6)

    tens_of_min = remaining // frames_per_10min
    remaining   = remaining % frames_per_10min

    if remaining < frames_per_1min:
        # First minute of each 10-minute group — no frames were dropped here
        odd_min = 0
        ss = remaining // nom
        ff = remaining % nom
    else:
        remaining -= frames_per_1min
        # Each subsequent minute has (frames_per_1min - D) actual frames
        odd_min = remaining // (frames_per_1min - D) + 1
        remaining = remaining % (frames_per_1min - D)
        # The +D accounts for the two frame numbers that were skipped at the
        # top of this minute in the TC display
        ss = (remaining + D) // nom
        ff = (remaining + D) % nom

    mm = tens_of_min * 10 + odd_min
    return f"{hh:02d}:{mm:02d}:{ss:02d};{ff:02d}"


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------

def tc_to_samples(tc: str, fps_string: str, drop_frame: bool = False) -> int:
    return frames_to_samples(
        tc_to_frame_index(tc, fps_string, drop_frame), fps_string, drop_frame
    )


def samples_to_tc(samples: int, fps_string: str, drop_frame: bool = False) -> str:
    return frame_index_to_tc(
        samples_to_frames(samples, fps_string, drop_frame), fps_string, drop_frame
    )
