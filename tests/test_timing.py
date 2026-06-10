"""Unit tests for pipeline/timing.py.

Focus areas:
- Round-trip frame ↔ sample conversion across all supported fps strings.
- Drop-frame timecode TC → frame_index and frame_index → TC, including the
  known skip-minute boundary cases.
- Fractional frame counts (used by odd overlap values).
"""

import pytest

from bg_spotter.pipeline.timing import (
    frames_to_samples,
    samples_to_frames,
    tc_to_frame_index,
    frame_index_to_tc,
    tc_to_samples,
    samples_to_tc,
)


SAMPLE_RATE = 48000

# ---------------------------------------------------------------------------
# frames_to_samples / samples_to_frames round-trips
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fps_string,frames,expected_samples", [
    ("24",     1,    2000),
    ("24",     24,   48000),
    ("25",     1,    1920),
    ("25",     25,   48000),
    ("23.976", 1,    2002),   # 48000 * 1001 / 24000 = 2002.0 exactly
    ("23.976", 24,   48048),
    ("30",     1,    1600),
    ("30",     30,   48000),
    # 29.97: 48000 * 1001 / 30000 = 1601.6 — rounds to nearest
    ("29.97 NDF", 1,  1602),
    ("29.97 DF",  1,  1602),
])
def test_frames_to_samples(fps_string, frames, expected_samples):
    assert frames_to_samples(frames, fps_string) == expected_samples


@pytest.mark.parametrize("fps_string", ["24", "25", "23.976", "30", "29.97 NDF"])
def test_round_trip_frame_sample(fps_string):
    """Round-trip: frame_count → samples → frame_count."""
    for frame in [0, 1, 100, 1000, 86400]:
        s = frames_to_samples(frame, fps_string)
        recovered = samples_to_frames(s, fps_string)
        assert recovered == frame, f"{fps_string}: frame {frame} → {s} samples → {recovered}"


def test_fractional_frame_overlap():
    """Odd overlap of 3 frames → 1.5 frames each side, sample-accurate at 24fps."""
    half = frames_to_samples(1.5, "24")
    assert half == 3000   # 1.5 × 2000


# ---------------------------------------------------------------------------
# Non-drop-frame TC → frame_index
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tc,fps_string,expected_frame", [
    ("00:00:00:00", "24",  0),
    ("00:00:01:00", "24",  24),
    ("00:01:00:00", "24",  1440),
    ("01:00:00:00", "24",  86400),
    ("00:00:00:00", "25",  0),
    ("00:00:01:00", "25",  25),
    ("01:00:00:00", "25",  90000),
    ("00:00:00:00", "30",  0),
    ("00:01:00:00", "30",  1800),
])
def test_tc_to_frame_ndf(tc, fps_string, expected_frame):
    assert tc_to_frame_index(tc, fps_string, drop_frame=False) == expected_frame


# ---------------------------------------------------------------------------
# Drop-frame TC → frame_index  (SMPTE 29.97 DF)
# ---------------------------------------------------------------------------
# At 29.97 DF frame-numbering skips frames 00 and 01 at the start of every
# minute that is NOT a multiple of 10.

@pytest.mark.parametrize("tc,expected_frame", [
    ("00:00:00;00", 0),
    ("00:00:00;01", 1),
    ("00:00:59;29", 1799),
    # Minute 1: first *displayed* frame is ;02, which is actual frame 1800
    ("00:01:00;02", 1800),
    ("00:01:00;03", 1801),
    # Minute 2: another two frames dropped → 1798 actual frames for minute 1
    ("00:02:00;02", 3598),
    # Minute 10: no drop (every 10th minute is exempt)
    ("00:10:00;00", 17982),
    # Hour boundary
    ("01:00:00;00", 107892),
])
def test_tc_to_frame_df(tc, expected_frame):
    assert tc_to_frame_index(tc, "29.97 DF", drop_frame=True) == expected_frame


# ---------------------------------------------------------------------------
# frame_index → TC (drop-frame)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("frame_index,expected_tc", [
    (0,      "00:00:00;00"),
    (1799,   "00:00:59;29"),
    (1800,   "00:01:00;02"),
    (1801,   "00:01:00;03"),
    (3598,   "00:02:00;02"),
    (17982,  "00:10:00;00"),
    (107892, "01:00:00;00"),
])
def test_frame_index_to_tc_df(frame_index, expected_tc):
    assert frame_index_to_tc(frame_index, "29.97 DF", drop_frame=True) == expected_tc


# ---------------------------------------------------------------------------
# Round-trip TC → frame → TC (NDF and DF)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tc,fps_string,drop_frame", [
    ("01:00:00:00", "24",      False),
    ("01:00:00:00", "25",      False),
    ("01:00:00:00", "30",      False),
    ("00:01:00;02", "29.97 DF", True),
    ("00:10:00;00", "29.97 DF", True),
    ("01:00:00;00", "29.97 DF", True),
])
def test_tc_round_trip(tc, fps_string, drop_frame):
    frame = tc_to_frame_index(tc, fps_string, drop_frame)
    recovered = frame_index_to_tc(frame, fps_string, drop_frame)
    assert recovered == tc


# ---------------------------------------------------------------------------
# tc_to_samples convenience wrapper
# ---------------------------------------------------------------------------

def test_tc_to_samples_24fps():
    # 00:00:01:00 at 24fps = 24 frames = 48000 samples
    assert tc_to_samples("00:00:01:00", "24") == SAMPLE_RATE
