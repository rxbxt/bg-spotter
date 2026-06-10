"""Tests for aaf/builder.py.

Validates the region-building logic (BG and Steps tracks) without requiring
a real video file.  The AAF write test is marked `slow` since it requires
pyaaf2 and writes to disk.
"""

import pytest

from bg_spotter.aaf.builder import (
    _build_bg_regions,
    _build_steps_regions,
    _Region,
)
from bg_spotter.pipeline.cut_detect import Edit
from bg_spotter.pipeline.foley_detect import WalkingRange
from bg_spotter.pipeline.timing import frames_to_samples


SAMPLE_RATE = 48000
FPS = "24"
DF  = False

# 10-second video at 24fps → 240 frames → 480000 samples
TOTAL_SAMPLES = frames_to_samples(240, FPS, DF)


# ---------------------------------------------------------------------------
# BG region building
# ---------------------------------------------------------------------------

class TestBuildBgRegions:
    def test_no_edits_produces_single_clip_on_a(self):
        a, b = _build_bg_regions([], TOTAL_SAMPLES, overlap_frames=2, fps_string=FPS, drop_frame=DF)
        # BG A gets one clip covering the full timeline
        clips_a = [r for r in a if not r.is_gap]
        clips_b = [r for r in b if not r.is_gap]
        assert len(clips_a) == 1
        assert clips_a[0].start == 0
        assert clips_a[0].end == TOTAL_SAMPLES
        # BG B is all gap
        assert all(r.is_gap for r in b)

    def test_single_hard_cut_alternates_tracks(self):
        cut_frame = 120  # midpoint of 10-second clip
        cut_sample = frames_to_samples(cut_frame, FPS, DF)
        edits = [Edit(start_frame=cut_frame, end_frame=cut_frame, kind="hard")]
        a, b = _build_bg_regions(edits, TOTAL_SAMPLES, overlap_frames=2, fps_string=FPS, drop_frame=DF)

        clips_a = [r for r in a if not r.is_gap]
        clips_b = [r for r in b if not r.is_gap]
        assert len(clips_a) == 1
        assert len(clips_b) == 1

    def test_overlap_extends_clips(self):
        cut_frame = 120
        edits = [Edit(start_frame=cut_frame, end_frame=cut_frame, kind="hard")]
        a, b = _build_bg_regions(edits, TOTAL_SAMPLES, overlap_frames=2, fps_string=FPS, drop_frame=DF)

        half_overlap = frames_to_samples(1, FPS, DF)  # 1 frame = 2000 samples at 24fps
        cut_sample = frames_to_samples(cut_frame, FPS, DF)

        clips_a = [r for r in a if not r.is_gap]
        clips_b = [r for r in b if not r.is_gap]

        # BG A clip should end PAST the cut
        assert clips_a[0].end == cut_sample + half_overlap
        # BG B clip should start BEFORE the cut
        assert clips_b[0].start == cut_sample - half_overlap

    def test_odd_overlap_is_sample_accurate(self):
        """Overlap=3 frames → 1.5 frames per side, no rounding to integer frames."""
        cut_frame = 120
        edits = [Edit(start_frame=cut_frame, end_frame=cut_frame, kind="hard")]
        a, b = _build_bg_regions(edits, TOTAL_SAMPLES, overlap_frames=3, fps_string=FPS, drop_frame=DF)

        # 1.5 frames at 24fps/48kHz = 3000 samples
        half_overlap = frames_to_samples(1.5, FPS, DF)
        assert half_overlap == 3000

        cut_sample = frames_to_samples(cut_frame, FPS, DF)
        clips_a = [r for r in a if not r.is_gap]
        assert clips_a[0].end == cut_sample + 3000

    def test_dissolve_overlap_uses_full_transition(self):
        dissolve_start = 100
        dissolve_end   = 124  # 24-frame dissolve
        edits = [Edit(start_frame=dissolve_start, end_frame=dissolve_end, kind="dissolve")]
        a, b = _build_bg_regions(edits, TOTAL_SAMPLES, overlap_frames=2, fps_string=FPS, drop_frame=DF)

        ds_sample = frames_to_samples(dissolve_start, FPS, DF)
        de_sample = frames_to_samples(dissolve_end,   FPS, DF)

        clips_a = [r for r in a if not r.is_gap]
        clips_b = [r for r in b if not r.is_gap]

        assert clips_a[0].end   == de_sample
        assert clips_b[0].start == ds_sample

    def test_regions_are_contiguous(self):
        """Every track must cover [0, TOTAL_SAMPLES) with no gaps or overlaps."""
        edits = [
            Edit(start_frame=60,  end_frame=60,  kind="hard"),
            Edit(start_frame=120, end_frame=120, kind="hard"),
            Edit(start_frame=180, end_frame=180, kind="hard"),
        ]
        for regions in _build_bg_regions(edits, TOTAL_SAMPLES, overlap_frames=2, fps_string=FPS, drop_frame=DF):
            cursor = 0
            for r in regions:
                assert r.start == cursor
                cursor = r.end
            assert cursor == TOTAL_SAMPLES


# ---------------------------------------------------------------------------
# Steps region building
# ---------------------------------------------------------------------------

class TestBuildStepsRegions:
    def _ranges(self):
        return [
            WalkingRange(start_frame=0,   end_frame=60,  layer_count=3),
            WalkingRange(start_frame=60,  end_frame=120, layer_count=2),
            WalkingRange(start_frame=120, end_frame=180, layer_count=1),
        ]

    def test_steps1_covers_all(self):
        s1, s2, s3 = _build_steps_regions(self._ranges(), TOTAL_SAMPLES, FPS, DF)
        clips1 = [r for r in s1 if not r.is_gap]
        # All three ranges have layer_count >= 1
        assert sum(r.length for r in clips1) > 0

    def test_steps3_covers_only_high_layer(self):
        s1, s2, s3 = _build_steps_regions(self._ranges(), TOTAL_SAMPLES, FPS, DF)
        clips3 = [r for r in s3 if not r.is_gap]
        # Only the first range (layer_count=3) qualifies
        total3 = sum(r.length for r in clips3)
        expected = frames_to_samples(60, FPS, DF)
        assert total3 == expected

    def test_empty_ranges_all_gap(self):
        s1, s2, s3 = _build_steps_regions([], TOTAL_SAMPLES, FPS, DF)
        for track in (s1, s2, s3):
            assert all(r.is_gap for r in track)


# ---------------------------------------------------------------------------
# AAF write test (requires pyaaf2)
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_write_aaf_roundtrip(tmp_path):
    """Write an AAF and verify it can be reopened with pyaaf2."""
    import aaf2
    from bg_spotter.aaf.builder import write_aaf
    from bg_spotter.pipeline.video_meta import VideoMeta

    meta = VideoMeta(
        path="fake.mov",
        fps_string="24",
        fps_rational=(24, 1),
        drop_frame=False,
        start_tc="01:00:00:00",
        duration_frames=240,
        total_samples=TOTAL_SAMPLES,
    )
    edits = [Edit(start_frame=120, end_frame=120, kind="hard")]
    out = str(tmp_path / "test.aaf")

    write_aaf(out, meta, edits, walking_ranges=None, overlap_frames=2, include_steps=False)

    with aaf2.open(out, "r") as f:
        mob_names = [m.name for m in f.content.mobs]
        assert "BG Spotter Output" in mob_names
        comp_mob = next(m for m in f.content.mobs if m.name == "BG Spotter Output")
        track_names = [slot.name for slot in comp_mob.slots]
        assert "BG A" in track_names
        assert "BG B" in track_names
