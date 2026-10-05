"""pyaaf2-based AAF construction.

Architecture
------------
Standard 3-level Pro Tools AAF hierarchy:
  CompositionMob (timeline) → MasterMob → SourceMob (file mob / essence)

One silent WAV is embedded via ``SourceMob.import_audio_essence()`` — the
canonical pyaaf2 path (same as its production embed tool).  This produces a
proper SourceClip segment and descriptor on the file mob; the previous
hand-rolled version put a Filler in the slot, which Pro Tools could not map,
and it decoded uninitialised buffers as audio ("loud glitch" regions that
only went quiet after -96 dB gain).

For each selected overlap size N (1–6 frames) two tracks are emitted:
  "Spots - N Frame Overlap A" and "Spots - N Frame Overlap B"
containing Sequences of SourceClips (pointing to the MasterMob) and Fillers.
All positions are 48 kHz sample counts.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from fractions import Fraction

import aaf2
from aaf2.rational import AAFRational

from bg_spotter.aaf.silence import generate_silent_wav
from bg_spotter.config import SAMPLE_RATE, BIT_DEPTH, CHANNELS
from bg_spotter.pipeline.cut_detect import Edit
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
    """Compute the (A, B) clip lists with overlap applied.

    The overlap is centred on each hard cut: N/2 frames of handle are added
    to the end of the outgoing clip and N/2 frames to the start of the
    incoming clip, so adjacent segments on alternating tracks genuinely
    overlap by N frames.  Dissolves receive no extension (the transition
    region itself separates the clips).
    """
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


def track_name(overlap_frames: int, ab: str) -> str:
    """Canonical Pro Tools track label for one spotted track."""
    return f"Spots - {overlap_frames} Frame Overlap {ab}"


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
    overlap_selections: list[int],
) -> None:
    """Write the guide-track AAF to *output_path*.

    For each N in *overlap_selections* (ascending), two tracks are written:
    "Spots - N Frame Overlap A" then "... B".  All tracks share one embedded
    silent master (imported through pyaaf2's canonical WAV path so Pro Tools
    maps it to true digital silence).
    """
    if not overlap_selections:
        raise ValueError("At least one overlap selection is required.")

    audio_rate    = _audio_rate()
    total_samples = meta.total_samples

    # Region sets per selected overlap size.
    track_definitions: list[tuple[list[_Region], str]] = []
    for n in sorted(overlap_selections):
        regions_a, regions_b = _build_bg_regions(
            edits, total_samples, n, meta.fps_string, meta.drop_frame
        )
        track_definitions.append((regions_a, track_name(n, "A")))
        track_definitions.append((regions_b, track_name(n, "B")))

    # ------------------------------------------------------------------
    # 1. SourceMob (file mob) — silent WAV imported the canonical way.
    #    import_audio_essence() creates: EssenceData with raw PCM frames,
    #    a PCMDescriptor populated from the WAV header, and a SourceClip
    #    segment (NOT a Filler) in slot 1.  This is the structure Pro
    #    Tools expects for embedded essence; the old hand-rolled version
    #    imported as garbage audio.
    # ------------------------------------------------------------------
    wav_fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="bgspotter_silence_")
    os.close(wav_fd)
    try:
        with open(wav_path, "wb") as wf:
            wf.write(generate_silent_wav(
                total_samples,
                sample_rate=SAMPLE_RATE,
                channels=CHANNELS,
                bit_depth=BIT_DEPTH,
            ))

        with aaf2.open(output_path, "w") as f:

            source_mob = f.create.SourceMob()
            source_mob.name = "BG Spotter Silence"
            f.content.mobs.append(source_mob)
            source_mob.import_audio_essence(wav_path, edit_rate=audio_rate)

            # --------------------------------------------------------------
            # 2. MasterMob — required intermediary for Pro Tools AAF import
            # --------------------------------------------------------------
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

            # --------------------------------------------------------------
            # 3. CompositionMob — the guide-track timeline
            # --------------------------------------------------------------
            comp_mob = f.create.CompositionMob()
            comp_mob.name = "BG Spotter Output"
            f.content.mobs.append(comp_mob)

            for slot_id, (regions, tname) in enumerate(track_definitions, start=1):
                slot = comp_mob.create_timeline_slot(edit_rate=audio_rate, slot_id=slot_id)
                slot.name    = tname
                slot.segment = _make_sequence(f, regions, master_mob, 1)
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass
