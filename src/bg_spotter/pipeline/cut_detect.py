"""PySceneDetect-based cut and dissolve detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector, AdaptiveDetector

from bg_spotter.config import CONTENT_DETECTOR_THRESHOLD


@dataclass
class Edit:
    """Represents a picture edit (hard cut or dissolve).

    start_frame: first frame of the transition (== end_frame for hard cuts).
    end_frame:   last frame of the transition (== start_frame for hard cuts).
    kind:        'hard' or 'dissolve'.
    """
    start_frame: int
    end_frame: int
    kind: Literal["hard", "dissolve"]
    thumbnail_path: str | None = field(default=None, repr=False)


def _as_frames(value, fps: float) -> int:
    """Normalise scenedetect position values across library versions.

    scenedetect 0.7 hands back ``FrameTimecode`` (``.frame_num``, or the
    deprecated ``.get_frames()``); 0.6 passes plain **seconds** as a float/int —
    notably in the progress callback. The Intel/Python 3.9 build resolves to
    0.6.x because 0.7 requires Python >= 3.10, so shipped builds hit both shapes.
    Calling ``.get_frames()`` unconditionally raised "'int' object has no
    attribute 'get_frames'" and failed the export on that build.
    """
    frame_num = getattr(value, "frame_num", None)
    if frame_num is not None:
        return int(frame_num)

    getter = getattr(value, "get_frames", None)
    if callable(getter):
        return int(getter())

    try:
        return int(round(float(value) * fps))
    except (TypeError, ValueError):
        return 0


def detect_cuts(
    video_path: str,
    threshold: float = CONTENT_DETECTOR_THRESHOLD,
    on_progress=None,
) -> list[Edit]:
    """Detect hard cuts and dissolves in *video_path*.

    Returns a list of Edit objects sorted by start_frame.
    *on_progress* is called with (frames_processed, total_frames) if provided.
    """
    video = open_video(video_path)
    manager = SceneManager()

    # ContentDetector finds hard cuts; AdaptiveDetector finds gradual transitions
    manager.add_detector(ContentDetector(threshold=threshold))
    manager.add_detector(AdaptiveDetector())

    fps = float(getattr(video, "frame_rate", 0.0) or 0.0)

    if on_progress:
        total_frames = _as_frames(video.duration, fps) if video.duration else 0

        def _cb(frame, timecode):
            on_progress(_as_frames(timecode, fps), total_frames)

        manager.detect_scenes(video, callback=_cb)
    else:
        manager.detect_scenes(video)

    scene_list = manager.get_scene_list()

    edits: list[Edit] = []

    for i, (start_tc, end_tc) in enumerate(scene_list):
        # The boundary between scene[i] and scene[i+1] is an edit.
        # start_tc of scene[i+1] == end_tc of scene[i].
        if i == 0:
            continue
        prev_end = scene_list[i - 1][1]   # FrameTimecode of previous scene end
        curr_start = start_tc              # FrameTimecode of current scene start

        prev_end_frame = _as_frames(prev_end, fps)
        curr_start_frame = _as_frames(curr_start, fps)

        # PySceneDetect reports dissolves as scenes that span the transition.
        # A dissolve is indicated when consecutive scenes overlap in frame count
        # or when AdaptiveDetector marks the boundary.
        if curr_start_frame > prev_end_frame:
            # Dissolve: the gap between scenes is the transition region
            edits.append(Edit(
                start_frame=prev_end_frame,
                end_frame=curr_start_frame,
                kind="dissolve",
            ))
        else:
            # Hard cut: instantaneous
            edits.append(Edit(
                start_frame=curr_start_frame,
                end_frame=curr_start_frame,
                kind="hard",
            ))

    return sorted(edits, key=lambda e: e.start_frame)
