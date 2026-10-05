"""End-to-end pipeline: video in, spotted AAF out.

Deliberately GUI-free so it can be driven from tests or a CLI without Qt.
Progress and cancellation are injected as callables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from bg_spotter.aaf.builder import track_name, write_aaf
from bg_spotter.pipeline.cut_detect import Edit, detect_cuts
from bg_spotter.pipeline.video_meta import VideoMeta, probe_video

ProgressFn = Callable[[str, int], None]


class CancelledError(Exception):
    """Raised when the user cancels mid-pipeline."""


@dataclass
class SpotConfig:
    video_path: str
    output_path: str
    overlap_selections: list[int]
    fps_string: str | None = None      # None → auto-detect from the file
    drop_frame: bool | None = None
    start_tc: str | None = None


@dataclass
class SpotResults:
    meta: VideoMeta
    edits: list[Edit]
    output_path: str
    track_names: list[str] = field(default_factory=list)


def tracks_for_selections(overlap_selections: list[int]) -> list[str]:
    """Track labels in the order they are written to the AAF."""
    names: list[str] = []
    for n in sorted(set(overlap_selections)):
        names += [track_name(n, "A"), track_name(n, "B")]
    return names


def default_output_path(video_path: str, overlap_selections: list[int]) -> str:
    """Suggested AAF path next to the source video, named from the selections."""
    base, _ = os.path.splitext(video_path)
    sel = sorted(set(overlap_selections)) or [2]
    suffix = "-".join(str(n) for n in sel)
    return f"{base}_Spots_{suffix}Frame.aaf"


def run_pipeline(
    config: SpotConfig,
    on_progress: ProgressFn | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> SpotResults:
    """Detect picture edits in the video and write the guide-track AAF."""

    def report(label: str, pct: int) -> None:
        if on_progress:
            on_progress(label, max(0, min(100, pct)))

    def check_cancel() -> None:
        if cancel_check and cancel_check():
            raise CancelledError("Cancelled by user.")

    selections = sorted(set(config.overlap_selections))
    if not selections:
        raise ValueError("Select at least one overlap size.")

    report("Reading video metadata…", 2)
    meta = probe_video(config.video_path)
    if config.fps_string:
        meta.fps_string = config.fps_string
    if config.drop_frame is not None:
        meta.drop_frame = config.drop_frame
    if config.start_tc:
        meta.start_tc = config.start_tc

    check_cancel()
    report("Detecting cuts…", 10)

    def _cut_progress(current: int, total: int) -> None:
        pct = 10 + round(60 * current / max(total, 1))
        report(f"Detecting cuts… {current:,} / {total:,} frames", pct)
        if cancel_check and cancel_check():
            raise CancelledError("Cancelled by user.")

    edits = detect_cuts(config.video_path, on_progress=_cut_progress)

    check_cancel()
    report("Writing AAF…", 78)
    write_aaf(
        output_path=config.output_path,
        meta=meta,
        edits=edits,
        overlap_selections=selections,
    )

    names = tracks_for_selections(selections)
    report(f"Done — {len(edits)} edits, {len(names)} tracks", 100)
    return SpotResults(
        meta=meta,
        edits=edits,
        output_path=config.output_path,
        track_names=names,
    )
