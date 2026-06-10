"""pyaaf2-based AAF construction.

Architecture
------------
Standard 3-level Pro Tools AAF hierarchy:
  CompositionMob (timeline) → MasterMob → SourceMob (file mob / essence)

One silent PCM WAV is embedded in the SourceMob. The MasterMob has a single
slot covering the full duration. CompositionMob tracks (BG A, BG B, Steps…)
contain Sequences of SourceClips (pointing to the MasterMob) and Fillers.
All positions are 48 kHz sample counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import aaf2
from aaf2.rational import AAFRational

from bg_spotter.config import SAMPLE_RATE, BIT_DEPTH, CHANNELS
from bg_spotter.pipeline.cut_detect import Edit
from bg_spotter.pipeline.foley_detect import WalkingRange
from bg_spotter.pipeline.timing import frames_to_samples
from bg_spotter.pipeline.video_meta import VideoMeta


# ---------------------------------------------------------------------------
# Internal region model
# ---------------------------------------------------------------------------

@dataclass
class _Region:
    """A contiguous span on an audio track (sample coordinates)."""
    start: int
    end: int
    is_gap: bool   # True → Filler; False → SourceClip

    @property
    def length(self) -> int:
        return self.end - self.start


# ---------------------------------------------------------------------------
# BG track construction
# ---------------------------------------------------------------------------

def _build_bg_regions(
    edits: list[Edit],
    total_samples: int,
    overlap_frames: int | float,
    fps_string: str,
    drop_frame: bool,
) -> tuple[list[_Region], list[_Region]]:
    """Compute the (BG A, BG B) clip lists with overlap applied."""
    half_overlap = frames_to_samples(Fraction(overlap_frames, 2), fps_string, drop_frame)

    edit_starts = [0] + [e.end_frame for e in edits]
    edit_ends   = [e.start_frame for e in edits] + [None]

    def s(frame: int | None) -> int:
        return total_samples if frame is None else frames_to_samples(frame, fps_string, drop_frame)

    base: list[tuple[int, int, str]] = []
    for i, (fs, fe) in enumerate(zip(edit_starts, edit_ends)):
        base.append((s(fs), s(fe), "A" if i % 2 == 0 else "B"))

    adjusted: list[tuple[int, int, str]] = list(base)

    for j, edit in enumerate(edits):
        prev_start, prev_end, prev_track = adjusted[j]
        next_start, next_end, next_track = adjusted[j + 1]

        if edit.kind == "hard":
            new_prev_end   = min(prev_end   + half_overlap, total_samples)
            new_next_start = max(next_start - half_overlap, 0)
        else:
            new_prev_end   = min(s(edit.end_frame),   total_samples)
            new_next_start = max(s(edit.start_frame), 0)

        adjusted[j]     = (prev_start,      new_prev_end,   prev_track)
        adjusted[j + 1] = (new_next_start,  next_end,       next_track)

    clips_a = [(cs, ce) for cs, ce, t in adjusted if t == "A"]
    clips_b = [(cs, ce) for cs, ce, t in adjusted if t == "B"]

    def _to_regions(clips: list[tuple[int, int]]) -> list[_Region]:
        regions: list[_Region] = []
        cursor = 0
        for cs, ce in sorted(clips):
            if cs > cursor:
                regions.append(_Region(cursor, cs, is_gap=True))
            regions.append(_Region(cs, ce, is_gap=False))
            cursor = ce
        if cursor < total_samples:
            regions.append(_Region(cursor, total_samples, is_gap=True))
        return regions

    return _to_regions(clips_a), _to_regions(clips_b)


# ---------------------------------------------------------------------------
# Steps track construction
# ---------------------------------------------------------------------------

def _build_steps_regions(
    walking_ranges: list[WalkingRange],
    total_samples: int,
    fps_string: str,
    drop_frame: bool,
) -> tuple[list[_Region], list[_Region], list[_Region]]:
    """Return (Steps1, Steps2, Steps3) region lists from WalkingRange objects."""

    def s(frame: int) -> int:
        return frames_to_samples(frame, fps_string, drop_frame)

    def _merge_and_build(min_layer: int) -> list[_Region]:
        clips = sorted(
            [(s(r.start_frame), s(r.end_frame)) for r in walking_ranges if r.layer_count >= min_layer],
            key=lambda x: x[0],
        )
        merged: list[tuple[int, int]] = []
        for start, end in clips:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        regions: list[_Region] = []
        cursor = 0
        for cs, ce in merged:
            if cs > cursor:
                regions.append(_Region(cursor, cs, is_gap=True))
            regions.append(_Region(cs, ce, is_gap=False))
            cursor = ce
        if cursor < total_samples:
            regions.append(_Region(cursor, total_samples, is_gap=True))
        return regions

    return _merge_and_build(1), _merge_and_build(2), _merge_and_build(3)


# ---------------------------------------------------------------------------
# AAF serialisation helpers
# ---------------------------------------------------------------------------

def _audio_rate() -> AAFRational:
    return AAFRational(SAMPLE_RATE, 1)


def _make_sequence(f, regions: list[_Region], master_mob, master_slot_id: int) -> object:
    """Build an aaf2 Sequence for one CompositionMob track.

    SourceClips reference the MasterMob (not the SourceMob directly).
    The Sequence.length is set to the sum of all component lengths so that
    Pro Tools correctly reports the track duration.
    """
    total_length = sum(r.length for r in regions)
    seq = f.create.Sequence(media_kind="sound", length=total_length)

    for region in regions:
        if region.is_gap:
            filler = f.create.Filler(media_kind="sound")
            filler.length = region.length
            seq.components.append(filler)
        else:
            clip = f.create.SourceClip(media_kind="sound")
            clip.length = region.length
            # start=0: every clip reads from position 0 in the master mob slot;
            # timeline position is determined by what precedes it in the sequence.
            clip.start = 0
            clip.mob = master_mob
            clip.slot_id = master_slot_id
            seq.components.append(clip)

    return seq


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def write_aaf(
    output_path: str,
    meta: VideoMeta,
    edits: list[Edit],
    walking_ranges: list[WalkingRange] | None,
    overlap_frames: int,
    include_steps: bool,
) -> None:
    """Write the guide-track AAF to *output_path*.

    Track order: BG A, BG B, [Steps 1, Steps 2, Steps 3].
    """
    audio_rate   = _audio_rate()
    total_samples = meta.total_samples
    block_align  = CHANNELS * (BIT_DEPTH // 8)   # 2 ch × 3 bytes = 6

    total_pcm_bytes = total_samples * CHANNELS * (BIT_DEPTH // 8)

    bg_a_regions, bg_b_regions = _build_bg_regions(
        edits, total_samples, overlap_frames, meta.fps_string, meta.drop_frame
    )

    steps_regions: tuple | None = None
    if include_steps and walking_ranges:
        steps_regions = _build_steps_regions(
            walking_ranges, total_samples, meta.fps_string, meta.drop_frame
        )

    with aaf2.open(output_path, "w") as f:

        # ------------------------------------------------------------------
        # 1. SourceMob (file mob) — embedded PCM silence
        # ------------------------------------------------------------------
        source_mob = f.create.SourceMob()
        source_mob.name = "BG Spotter Silence"
        f.content.mobs.append(source_mob)

        # PCMDescriptor is the correct subclass for raw PCM; Pro Tools requires it.
        desc = f.create.PCMDescriptor()
        desc["AudioSamplingRate"].value = audio_rate
        desc["Channels"].value          = CHANNELS
        desc["QuantizationBits"].value  = BIT_DEPTH
        desc["SampleRate"].value        = audio_rate
        desc["Length"].value            = total_samples
        desc["BlockAlign"].value        = block_align
        desc["AverageBPS"].value        = SAMPLE_RATE * block_align
        source_mob.descriptor = desc

        source_slot = source_mob.create_timeline_slot(edit_rate=audio_rate, slot_id=1)
        source_filler = f.create.Filler(media_kind="sound")
        source_filler.length = total_samples
        source_slot.segment = source_filler

        essence = f.create.EssenceData()
        essence.mob = source_mob
        f.content.essencedata.append(essence)
        stream = essence.open("w")
        # Write in 4 KB chunks — a single large write leaves CFB sectors
        # uninitialized on some pyaaf2 builds, producing audible noise in Pro Tools.
        chunk = bytes(4096)
        remaining = total_pcm_bytes
        while remaining > 0:
            n = min(4096, remaining)
            stream.write(chunk[:n])
            remaining -= n
        stream.close()

        # ------------------------------------------------------------------
        # 2. MasterMob — required intermediary for Pro Tools AAF import
        # ------------------------------------------------------------------
        master_mob = f.create.MasterMob()
        master_mob.name = "BG Spotter Silence"
        f.content.mobs.append(master_mob)

        master_slot = master_mob.create_timeline_slot(edit_rate=audio_rate, slot_id=1)
        master_clip = f.create.SourceClip(media_kind="sound")
        master_clip.length   = total_samples
        master_clip.start    = 0
        master_clip.mob      = source_mob
        master_clip.slot_id  = 1
        master_slot.segment  = master_clip

        # ------------------------------------------------------------------
        # 3. CompositionMob — the guide-track timeline
        # ------------------------------------------------------------------
        comp_mob = f.create.CompositionMob()
        comp_mob.name = "BG Spotter Output"
        f.content.mobs.append(comp_mob)

        track_definitions = [
            (bg_a_regions, "BG A"),
            (bg_b_regions, "BG B"),
        ]
        if steps_regions is not None:
            s1, s2, s3 = steps_regions
            track_definitions += [
                (s1, "Steps 1"),
                (s2, "Steps 2"),
                (s3, "Steps 3"),
            ]

        for slot_id, (regions, track_name) in enumerate(track_definitions, start=1):
            slot = comp_mob.create_timeline_slot(edit_rate=audio_rate, slot_id=slot_id)
            slot.name    = track_name
            slot.segment = _make_sequence(f, regions, master_mob, 1)
