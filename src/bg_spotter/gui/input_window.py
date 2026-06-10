"""Screen 1 — video and parameter input dialog."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QSpinBox,
    QComboBox, QFileDialog, QGroupBox, QMessageBox,
)

from bg_spotter.config import FPS_RATES, SUPPORTED_VIDEO_EXTS
from bg_spotter.gui.progress import SpotConfig
from bg_spotter.pipeline.video_meta import probe_video
from bg_spotter.pipeline.vlm_detect import list_ollama_models


_FPS_LABELS = list(FPS_RATES.keys())


class InputWindow(QWidget):
    """Screen 1: video file selector, frame rate, TC, and spotting options."""

    spot_requested = Signal(object)  # emits SpotConfig

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)

        # ---- Video file ----
        file_group = QGroupBox("Video File")
        file_layout = QHBoxLayout(file_group)
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("Select a .mov, .mxf, or .mp4 file…")
        self._path_edit.setReadOnly(True)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse)
        file_layout.addWidget(self._path_edit)
        file_layout.addWidget(browse_btn)
        root.addWidget(file_group)

        # ---- Metadata ----
        meta_group = QGroupBox("Metadata")
        meta_form = QFormLayout(meta_group)

        self._fps_combo = QComboBox()
        self._fps_combo.addItems(_FPS_LABELS)
        self._fps_combo.currentTextChanged.connect(self._on_fps_changed)
        meta_form.addRow("Frame rate:", self._fps_combo)

        self._df_check = QCheckBox("Drop-frame")
        meta_form.addRow("", self._df_check)

        self._tc_edit = QLineEdit("01:00:00:00")
        meta_form.addRow("Start timecode:", self._tc_edit)

        root.addWidget(meta_group)

        # ---- Spotting categories ----
        cat_group = QGroupBox("Spotting Categories")
        cat_layout = QVBoxLayout(cat_group)

        # BG
        self._bg_check = QCheckBox("Backgrounds (BG)")
        self._bg_check.setChecked(True)
        self._bg_check.toggled.connect(self._update_visibility)
        cat_layout.addWidget(self._bg_check)

        self._bg_group = QWidget()
        bg_form = QFormLayout(self._bg_group)
        bg_form.setContentsMargins(24, 0, 0, 0)
        self._overlap_spin = QSpinBox()
        self._overlap_spin.setRange(0, 99)
        self._overlap_spin.setValue(2)
        self._overlap_spin.setSuffix(" frames")
        bg_form.addRow("Frame overlap:", self._overlap_spin)
        cat_layout.addWidget(self._bg_group)

        # Steps
        self._steps_check = QCheckBox("Footsteps (Steps)")
        self._steps_check.setChecked(False)
        self._steps_check.toggled.connect(self._update_visibility)
        cat_layout.addWidget(self._steps_check)

        self._steps_group = QWidget()
        steps_form = QFormLayout(self._steps_group)
        steps_form.setContentsMargins(24, 0, 0, 0)

        self._vlm_check = QCheckBox("Run optional VLM refinement pass")
        self._vlm_check.toggled.connect(self._update_visibility)
        steps_form.addRow(self._vlm_check)

        self._vlm_model_combo = QComboBox()
        self._vlm_model_label = QLabel("VLM model:")
        steps_form.addRow(self._vlm_model_label, self._vlm_model_combo)

        cat_layout.addWidget(self._steps_group)
        root.addWidget(cat_group)

        # ---- Spot button ----
        self._spot_btn = QPushButton("Spot")
        self._spot_btn.setDefault(True)
        self._spot_btn.clicked.connect(self._on_spot)
        root.addWidget(self._spot_btn)

        root.addStretch()
        self._update_visibility()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_browse(self) -> None:
        exts = " ".join(f"*{e}" for e in SUPPORTED_VIDEO_EXTS)
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File", "", f"Video Files ({exts});;All Files (*)"
        )
        if not path:
            return
        self._path_edit.setText(path)
        self._auto_detect_metadata(path)

    def _auto_detect_metadata(self, path: str) -> None:
        try:
            meta = probe_video(path)
            # Select fps in combo
            idx = self._fps_combo.findText(meta.fps_string)
            if idx >= 0:
                self._fps_combo.setCurrentIndex(idx)
            self._df_check.setChecked(meta.drop_frame)
            self._tc_edit.setText(meta.start_tc)
        except Exception:
            pass  # If ffprobe fails, leave defaults in place

    def _on_fps_changed(self, text: str) -> None:
        # Enable drop-frame checkbox only for applicable rates
        df_capable = text in ("29.97 NDF", "29.97 DF")
        self._df_check.setEnabled(df_capable)
        if not df_capable:
            self._df_check.setChecked(False)
        if text == "29.97 DF":
            self._df_check.setChecked(True)

    def _update_visibility(self) -> None:
        self._bg_group.setVisible(self._bg_check.isChecked())
        self._steps_group.setVisible(self._steps_check.isChecked())

        if self._steps_check.isChecked():
            vlm_visible = self._vlm_check.isChecked()
            self._vlm_model_label.setVisible(vlm_visible)
            self._vlm_model_combo.setVisible(vlm_visible)
            if vlm_visible and self._vlm_model_combo.count() == 0:
                self._populate_vlm_models()

    def _populate_vlm_models(self) -> None:
        models = list_ollama_models()
        if models:
            self._vlm_model_combo.addItems(models)
        else:
            self._vlm_model_combo.addItem("(no Ollama models found)")

    def _on_spot(self) -> None:
        path = self._path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "No File", "Please select a video file first.")
            return

        if not self._bg_check.isChecked() and not self._steps_check.isChecked():
            QMessageBox.warning(
                self, "Nothing to Do",
                "Please enable at least one spotting category."
            )
            return

        fps_string = self._fps_combo.currentText()
        drop_frame = self._df_check.isChecked()

        vlm_model = None
        if self._steps_check.isChecked() and self._vlm_check.isChecked():
            vlm_model = self._vlm_model_combo.currentText()
            if vlm_model.startswith("("):
                vlm_model = None

        config = SpotConfig(
            video_path=path,
            fps_string=fps_string,
            drop_frame=drop_frame,
            start_tc=self._tc_edit.text().strip(),
            include_bg=self._bg_check.isChecked(),
            include_steps=self._steps_check.isChecked(),
            overlap_frames=self._overlap_spin.value(),
            use_vlm=self._vlm_check.isChecked(),
            vlm_model=vlm_model,
        )
        self.spot_requested.emit(config)
