"""Tests for aaf/builder.py — multi-overlap track construction + AAF writing."""

import os
import tempfile

import pytest

from bg_spotter.aaf.builder import (
    _build_bg_regions,
    track_name,
    write_aaf,
)
from bg_spotter.config import MASTER_CHANNELS
from bg_spotter.pipeline.cut_detect import Edit
from bg_spotter.pipeline.timing import frames_to_samples
from bg_spotter.pipeline.video_meta import VideoMeta


SAMPLE_RATE = 48000
FPS = "24"
DF = False

# 10-second video at 24fps → 240 frames → 480000 samples
TOTAL_SAMPLES = frames_to_samples(240, FPS, DF)


def _meta(total_samples: int = TOTAL_SAMPLES) -> VideoMeta:
    return VideoMeta(
        path="fake.mov",
        fps_string=FPS,
        fps_rational=(24, 1),
        drop_frame=False,
        start_tc="01:00:00:00",
        duration_frames=240,
        total_samples=total_samples,
    )


class TestBuildBgRegions:
    def test_no_edits_produces_single_clip_on_a(self):
        a, b = _build_bg_regions([], TOTAL_SAMPLES, overlap_frames=2, fps_string=FPS, drop_frame=DF)
        clips_a = [r for r in a if not r.is_gap]
        clips_b = [r for r in b if not r.is_gap]
        assert len(clips_a) == 1
        assert clips_a[0].start == 0
        assert clips_a[0].end == TOTAL_SAMPLES
        assert all(r.is_gap for r in b)

    def test_single_hard_cut_alternates_tracks(self):
        cut_frame = 120
        edits = [Edit(start_frame=cut_frame, end_frame=cut_frame, kind="hard")]
        a, b = _build_bg_regions(edits, TOTAL_SAMPLES, overlap_frames=2, fps_string=FPS, drop_frame=DF)
        clips_a = [r for r in a if not r.is_gap]
        clips_b = [r for r in b if not r.is_gap]
        assert len(clips_a) == 1
        assert len(clips_b) == 1

    def test_overlap_extends_clips_by_half_each_side(self):
        cut_frame = 120
        edits = [Edit(start_frame=cut_frame, end_frame=cut_frame, kind="hard")]
        a, b = _build_bg_regions(edits, TOTAL_SAMPLES, overlap_frames=2, fps_string=FPS, drop_frame=DF)
        half = frames_to_samples(1, FPS, DF)  # 2-frame overlap → 1 frame each side
        cut_sample = frames_to_samples(cut_frame, FPS, DF)
        clip_a = [r for r in a if not r.is_gap][0]
        clip_b = [r for r in b if not r.is_gap][0]
        assert clip_a.end == cut_sample + half
        assert clip_b.start == cut_sample - half

    @pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6])
    def test_overlap_amount_matches_selection(self, n):
        """Adjacent A/B clips must overlap by exactly N frames (±1 sample)."""
        cut_frame = 120
        edits = [Edit(start_frame=cut_frame, end_frame=cut_frame, kind="hard")]
        a, b = _build_bg_regions(edits, TOTAL_SAMPLES, overlap_frames=n, fps_string=FPS, drop_frame=DF)
        clip_a = [r for r in a if not r.is_gap][0]
        clip_b = [r for r in b if not r.is_gap][0]
        overlap_samples = clip_a.end - clip_b.start
        expected = frames_to_samples(n, FPS, DF)
        assert abs(overlap_samples - expected) <= 1

    def test_odd_overlap_centered(self):
        cut_frame = 120
        edits = [Edit(start_frame=cut_frame, end_frame=cut_frame, kind="hard")]
        a, b = _build_bg_regions(edits, TOTAL_SAMPLES, overlap_frames=3, fps_string=FPS, drop_frame=DF)
        clip_a = [r for r in a if not r.is_gap][0]
        clip_b = [r for r in b if not r.is_gap][0]
        cut_sample = frames_to_samples(cut_frame, FPS, DF)
        three = frames_to_samples(3, FPS, DF)
        assert clip_a.end - clip_b.start == three
        assert abs((clip_a.end - cut_sample) - three / 2) <= 1
        assert abs((cut_sample - clip_b.start) - three / 2) <= 1

    def test_dissolve_uses_full_transition_region(self):
        """A dissolve spans [start,end]; the A clip runs to the transition and
        the B clip starts at its beginning — no extra handle extension."""
        edits = [Edit(start_frame=100, end_frame=110, kind="dissolve")]
        a, b = _build_bg_regions(edits, TOTAL_SAMPLES, overlap_frames=4, fps_string=FPS, drop_frame=DF)
        clip_a = [r for r in a if not r.is_gap][0]
        clip_b = [r for r in b if not r.is_gap][0]
        assert clip_a.end == frames_to_samples(110, FPS, DF)
        assert clip_b.start == frames_to_samples(100, FPS, DF)

    def test_multiple_cuts_alternation(self):
        edits = [
            Edit(start_frame=60, end_frame=60, kind="hard"),
            Edit(start_frame=120, end_frame=120, kind="hard"),
            Edit(start_frame=180, end_frame=180, kind="hard"),
        ]
        a, b = _build_bg_regions(edits, TOTAL_SAMPLES, overlap_frames=2, fps_string=FPS, drop_frame=DF)
        assert len([r for r in a if not r.is_gap]) == 2
        assert len([r for r in b if not r.is_gap]) == 2

    def test_regions_are_contiguous(self):
        """Every track must cover [0, TOTAL_SAMPLES) with no gaps or overlaps."""
        edits = [
            Edit(start_frame=60, end_frame=60, kind="hard"),
            Edit(start_frame=120, end_frame=120, kind="hard"),
            Edit(start_frame=180, end_frame=180, kind="hard"),
        ]
        for regions in _build_bg_regions(edits, TOTAL_SAMPLES, overlap_frames=2, fps_string=FPS, drop_frame=DF):
            cursor = 0
            for r in regions:
                assert r.start == cursor
                cursor = r.end
            assert cursor == TOTAL_SAMPLES


class TestTrackName:
    def test_label_format(self):
        assert track_name(2, "A") == "Spots - 2 Frame Overlap A"
        assert track_name(5, "B") == "Spots - 5 Frame Overlap B"


def _read_back(path):
    import aaf2
    with aaf2.open(path, "r") as f:
        comp = next(m for m in f.content.mobs if type(m).__name__ == "CompositionMob")
        slots = {}
        for slot in comp.slots:
            seg = slot.segment
            clips = [c for c in seg.components if type(c).__name__ == "SourceClip"]
            gaps = [c for c in seg.components if type(c).__name__ == "Filler"]
            slots[slot.name] = {
                "clips": [(c.start, c.length) for c in clips],
                "gaps": len(gaps),
                "length": seg.length,
            }
    return slots


class TestWriteAaf:
    def test_single_overlap_two_tracks(self):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "one.aaf")
            edits = [Edit(start_frame=120, end_frame=120, kind="hard")]
            write_aaf(out, _meta(), edits, overlap_selections=[2])
            slots = _read_back(out)
            assert list(slots.keys()) == [
                "Spots - 2 Frame Overlap A", "Spots - 2 Frame Overlap B"]

    def test_multi_overlap_track_pairs_ascending(self):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "multi.aaf")
            edits = [Edit(start_frame=120, end_frame=120, kind="hard")]
            write_aaf(out, _meta(), edits, overlap_selections=[4, 2])
            slots = _read_back(out)
            assert list(slots.keys()) == [
                "Spots - 2 Frame Overlap A", "Spots - 2 Frame Overlap B",
                "Spots - 4 Frame Overlap A", "Spots - 4 Frame Overlap B",
            ]

    def test_all_six_overlaps(self):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "all.aaf")
            write_aaf(out, _meta(), [], overlap_selections=[1, 2, 3, 4, 5, 6])
            slots = _read_back(out)
            assert len(slots) == 12

    def test_track_lengths_cover_timeline(self):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "len.aaf")
            edits = [Edit(start_frame=120, end_frame=120, kind="hard")]
            write_aaf(out, _meta(), edits, overlap_selections=[3])
            slots = _read_back(out)
            for name, info in slots.items():
                assert info["length"] == TOTAL_SAMPLES, name

    def test_essence_is_all_zeros(self):
        """The embedded master must be true digital silence (fix for the
        -96dB gain workaround)."""
        import olefile
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "sil.aaf")
            write_aaf(out, _meta(), [], overlap_selections=[2])
            data_streams = []
            with olefile.OleFileIO(out) as ole:
                for e in ole.listdir():
                    # essence payload lives at .../EssenceData-xxxx{0}/Data-2702
                    if e[-1].startswith("Data-") and any(
                        p.startswith("EssenceData-") for p in e
                    ):
                        data_streams.append(ole.openstream(e).read())
            assert len(data_streams) == 1
            payload = data_streams[0]
            assert len(payload) == TOTAL_SAMPLES * MASTER_CHANNELS * 3
            assert not any(payload), "essence must contain only zero bytes"

    def test_master_is_mono_not_multichannel(self):
        """Regression: Pro Tools logs 'Audio file … is multi-channel. Only the
        first channel will be referenced by Pro Tools.' for interleaved stereo
        essence and imports the regions as uninitialised memory (the ticking).
        The embedded master must therefore be single-channel."""
        import aaf2
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "mono.aaf")
            write_aaf(out, _meta(), [], overlap_selections=[2])
            with aaf2.open(out, "r") as f:
                src = [m for m in f.content.mobs
                       if type(m).__name__ == "SourceMob"][0]
                d = src.descriptor
                assert d["Channels"].value == 1, (
                    "embedded master must be mono or Pro Tools references only "
                    "its first channel and leaves the regions unfilled")
                assert d["BlockAlign"].value == 3

    def test_source_mob_slot_is_sourceclip_not_filler(self):
        """Regression: the old builder put a Filler in the file-mob slot;
        Pro Tools could not map it and imported garbage audio."""
        import aaf2
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "struct.aaf")
            write_aaf(out, _meta(), [], overlap_selections=[1])
            with aaf2.open(out, "r") as f:
                source_mobs = [m for m in f.content.mobs if type(m).__name__ == "SourceMob"]
                assert len(source_mobs) == 1
                seg = source_mobs[0].slots[0].segment
                assert type(seg).__name__ == "SourceClip"

    def test_empty_selection_raises(self):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "bad.aaf")
            with pytest.raises(ValueError):
                write_aaf(out, _meta(), [], overlap_selections=[])
