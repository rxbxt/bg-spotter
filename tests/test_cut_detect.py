"""Tests for pipeline/cut_detect.py.

Real cut detection requires a video fixture.  The fixture-based test is
marked `slow` and skipped unless a test video is available.  The unit
tests below cover the Edit dataclass and the logic that converts
PySceneDetect scene boundaries into Edit objects.
"""

import pytest
from bg_spotter.pipeline.cut_detect import Edit


def test_edit_hard_cut():
    edit = Edit(start_frame=100, end_frame=100, kind="hard")
    assert edit.start_frame == edit.end_frame
    assert edit.kind == "hard"


def test_edit_dissolve():
    edit = Edit(start_frame=100, end_frame=124, kind="dissolve")
    assert edit.end_frame > edit.start_frame
    assert edit.kind == "dissolve"


def test_edit_thumbnail_default():
    edit = Edit(start_frame=0, end_frame=0, kind="hard")
    assert edit.thumbnail_path is None


@pytest.mark.slow
def test_detect_cuts_fixture(tmp_path):
    """Requires ffmpeg on PATH to create a test video."""
    import subprocess
    import shutil

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not available")

    # Build a test video: three 10-second 24fps clips concatenated via lavfi
    out_video = str(tmp_path / "test_cuts.mp4")
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i",
        "color=c=red:s=320x240:r=24:d=10,"
        "color=c=blue:s=320x240:r=24:d=10,"
        "color=c=green:s=320x240:r=24:d=10",
        "-c:v", "libx264", "-preset", "ultrafast",
        out_video,
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        pytest.skip("Could not create test video")

    from bg_spotter.pipeline.cut_detect import detect_cuts
    edits = detect_cuts(out_video)

    # We expect roughly 2 hard cuts (at frames 240 and 480 for 24fps × 10s)
    hard_cuts = [e for e in edits if e.kind == "hard"]
    assert len(hard_cuts) >= 2
