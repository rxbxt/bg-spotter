"""PySceneDetect-based cut and dissolve detection."""

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

    if on_progress:
        # In scenedetect 0.7 the callback signature is (frame: np.ndarray, timecode: FrameTimecode).
        # video.duration is a FrameTimecode; .get_frames() gives the integer frame count.
        total_frames = video.duration.get_frames() if video.duration else 0

        def _cb(frame, timecode):
            on_progress(timecode.get_frames(), total_frames)

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

        prev_end_frame = prev_end.get_frames()
        curr_start_frame = curr_start.get_frames()

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
