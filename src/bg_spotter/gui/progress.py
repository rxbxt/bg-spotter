"""Background pipeline worker and progress dialog."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton, QSizePolicy,
)

from bg_spotter.pipeline.cut_detect import Edit, detect_cuts
from bg_spotter.pipeline.foley_detect import WalkingRange, detect_walking
from bg_spotter.pipeline.video_meta import VideoMeta, probe_video
from bg_spotter.pipeline.vlm_detect import refine_with_vlm, OllamaBackend


@dataclass
class SpotConfig:
    video_path: str
    fps_string: str
    drop_frame: bool
    start_tc: str
    include_bg: bool
    include_steps: bool
    overlap_frames: int
    use_vlm: bool
    vlm_model: str | None


@dataclass
class SpotResults:
    meta: VideoMeta
    edits: list[Edit]
    walking_ranges: list[WalkingRange] | None
    thumbnails: dict[int, str] = field(default_factory=dict)  # frame → path


class PipelineWorker(QThread):
    progress = Signal(str, int)   # (step_label, pct 0-100)
    completed = Signal(object)    # SpotResults
    failed = Signal(str)          # error message

    def __init__(self, config: SpotConfig):
        super().__init__()
        self._config = config
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            cfg = self._config

            self.progress.emit("Reading video metadata…", 2)
            meta = probe_video(cfg.video_path)
            # Override with user-edited values
            meta.fps_string = cfg.fps_string
            meta.drop_frame = cfg.drop_frame
            meta.start_tc   = cfg.start_tc

            self.progress.emit("Detecting cuts…", 10)

            def _cut_progress(current, total):
                pct = 10 + round(20 * current / max(total, 1))
                self.progress.emit(f"Detecting cuts… ({current}/{total} frames)", pct)

            edits = detect_cuts(cfg.video_path, on_progress=_cut_progress)

            walking_ranges: list[WalkingRange] | None = None

            if cfg.include_steps and not self._cancel:
                self.progress.emit("Running YOLO pose detection…", 30)

                def _yolo_progress(current, total):
                    pct = 30 + round(40 * current / max(total, 1))
                    self.progress.emit(
                        f"YOLO pose ({current}/{total} frames)", pct
                    )

                walking_ranges = detect_walking(
                    cfg.video_path, meta, on_progress=_yolo_progress
                )

                if cfg.use_vlm and cfg.vlm_model and not self._cancel:
                    self.progress.emit("Running VLM refinement…", 70)

                    def _vlm_progress(current, total):
                        pct = 70 + round(20 * current / max(total, 1))
                        self.progress.emit(
                            f"VLM refinement ({current}/{total} ranges)", pct
                        )

                    walking_ranges = refine_with_vlm(
                        cfg.video_path,
                        walking_ranges,
                        cfg.vlm_model,
                        backend=OllamaBackend(),
                        on_progress=_vlm_progress,
                    )

            if not self._cancel:
                self.progress.emit("Generating thumbnails…", 92)
                thumbnails = _extract_thumbnails(cfg.video_path, edits)
                self.progress.emit("Done", 100)
                self.completed.emit(
                    SpotResults(meta, edits, walking_ranges, thumbnails)
                )
        except Exception as exc:
            self.failed.emit(str(exc))


def _extract_thumbnails(video_path: str, edits: list[Edit]) -> dict[int, str]:
    """Extract a JPEG thumbnail near each edit's cut frame using OpenCV."""
    import os
    import tempfile
    import cv2

    cap = cv2.VideoCapture(video_path)
    thumbnails: dict[int, str] = {}
    tmp_dir = tempfile.mkdtemp(prefix="bgspotter_thumbs_")

    for edit in edits:
        frame_idx = max(0, edit.start_frame - 2)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            continue
        out_path = os.path.join(tmp_dir, f"thumb_{edit.start_frame:08d}.jpg")
        # Resize to thumbnail width
        h, w = frame.shape[:2]
        thumb_w = 96
        thumb_h = round(h * thumb_w / w)
        thumb = cv2.resize(frame, (thumb_w, thumb_h))
        cv2.imwrite(out_path, thumb)
        thumbnails[edit.start_frame] = out_path

    cap.release()
    return thumbnails


# ---------------------------------------------------------------------------
# Progress dialog (shown during pipeline execution)
# ---------------------------------------------------------------------------

class ProgressDialog(QDialog):
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("BG Spotter — Processing")
        self.setMinimumWidth(420)
        self.setModal(True)

        layout = QVBoxLayout(self)

        self._label = QLabel("Starting…")
        self._label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self._label)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        layout.addWidget(self._bar)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._on_cancel)
        layout.addWidget(self._cancel_btn)

    def update_progress(self, label: str, pct: int) -> None:
        self._label.setText(label)
        self._bar.setValue(pct)

    def _on_cancel(self) -> None:
        self._cancel_btn.setEnabled(False)
        self._label.setText("Cancelling…")
        self.cancelled.emit()
