"""Screen 2 — cut-list review and AAF generation."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QMessageBox, QGroupBox,
    QDialog, QLineEdit, QDialogButtonBox, QSizePolicy,
)

from bg_spotter.aaf.builder import write_aaf
from bg_spotter.gui.progress import SpotConfig, SpotResults
from bg_spotter.pipeline.cut_detect import Edit
from bg_spotter.pipeline.timing import samples_to_tc


class _AddCutDialog(QDialog):
    """Small dialog for manually entering a cut timecode."""

    def __init__(self, fps_string: str, drop_frame: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Cut")
        self._fps_string = fps_string
        self._drop_frame = drop_frame

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Enter cut timecode (HH:MM:SS:FF):"))
        self._tc_edit = QLineEdit()
        self._tc_edit.setPlaceholderText("01:00:10:00")
        layout.addWidget(self._tc_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def timecode(self) -> str:
        return self._tc_edit.text().strip()


class ReviewWindow(QWidget):
    """Screen 2: review detected cuts, then generate AAF."""

    generate_done = Signal(str)   # emits output path when AAF is written
    back_requested = Signal()

    def __init__(self, results: SpotResults, config: SpotConfig, parent=None):
        super().__init__(parent)
        self._results = results
        self._config  = config
        self._edits   = list(results.edits)  # mutable copy
        self._build_ui()
        self._populate_table()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ---- Cut list ----
        cut_group = QGroupBox("Detected Cuts")
        cut_layout = QVBoxLayout(cut_group)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Timecode", "Kind", "Thumbnail"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setDefaultSectionSize(56)
        cut_layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        del_btn = QPushButton("Delete Selected")
        del_btn.clicked.connect(self._on_delete)
        add_btn = QPushButton("+ Add Cut…")
        add_btn.clicked.connect(self._on_add_cut)
        btn_row.addWidget(del_btn)
        btn_row.addWidget(add_btn)
        btn_row.addStretch()
        cut_layout.addLayout(btn_row)
        root.addWidget(cut_group)

        # ---- Steps summary ----
        if self._results.walking_ranges:
            steps_group = QGroupBox("Footstep Detection Summary (rough guidance)")
            steps_layout = QVBoxLayout(steps_group)
            steps_layout.addWidget(QLabel(self._build_steps_summary()))
            root.addWidget(steps_group)

        # ---- Actions ----
        action_row = QHBoxLayout()
        back_btn = QPushButton("← Back")
        back_btn.clicked.connect(self.back_requested)
        self._gen_btn = QPushButton("Generate AAF…")
        self._gen_btn.setDefault(True)
        self._gen_btn.clicked.connect(self._on_generate)
        action_row.addWidget(back_btn)
        action_row.addStretch()
        action_row.addWidget(self._gen_btn)
        root.addLayout(action_row)

    # ------------------------------------------------------------------
    # Table population
    # ------------------------------------------------------------------

    def _tc_for_frame(self, frame: int) -> str:
        meta = self._results.meta
        return samples_to_tc(
            round(frame * 48000 * meta.fps_rational[1] / meta.fps_rational[0]),
            meta.fps_string, meta.drop_frame
        )

    def _populate_table(self) -> None:
        self._table.setRowCount(0)
        for edit in self._edits:
            row = self._table.rowCount()
            self._table.insertRow(row)

            tc_item = QTableWidgetItem(self._tc_for_frame(edit.start_frame))
            tc_item.setData(Qt.UserRole, edit.start_frame)
            self._table.setItem(row, 0, tc_item)

            kind_item = QTableWidgetItem(edit.kind.capitalize())
            self._table.setItem(row, 1, kind_item)

            # Thumbnail
            thumb_path = self._results.thumbnails.get(edit.start_frame)
            if thumb_path:
                pix = QPixmap(thumb_path)
                if not pix.isNull():
                    label = QLabel()
                    label.setPixmap(pix.scaledToHeight(52, Qt.SmoothTransformation))
                    label.setAlignment(Qt.AlignCenter)
                    self._table.setCellWidget(row, 2, label)
            else:
                self._table.setItem(row, 2, QTableWidgetItem(""))

    def _build_steps_summary(self) -> str:
        from bg_spotter.pipeline.foley_detect import WalkingRange
        ranges = self._results.walking_ranges or []
        meta = self._results.meta

        def _dur(layer: int) -> str:
            total_frames = sum(
                r.end_frame - r.start_frame
                for r in ranges if r.layer_count >= layer
            )
            fps = meta.fps_rational[0] / meta.fps_rational[1]
            secs = total_frames / fps
            m = int(secs // 60)
            s = int(secs % 60)
            return f"{m}m{s:02d}s"

        total = len(ranges)
        return (
            f"{total} walking range(s) detected.  "
            f"Steps 1: {_dur(1)}   Steps 2: {_dur(2)}   Steps 3: {_dur(3)}"
        )

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_delete(self) -> None:
        rows = sorted(
            {idx.row() for idx in self._table.selectedIndexes()}, reverse=True
        )
        for row in rows:
            frame = self._table.item(row, 0).data(Qt.UserRole)
            self._edits = [e for e in self._edits if e.start_frame != frame]
            self._table.removeRow(row)

    def _on_add_cut(self) -> None:
        meta = self._results.meta
        dlg = _AddCutDialog(meta.fps_string, meta.drop_frame, self)
        if dlg.exec() != QDialog.Accepted:
            return

        tc = dlg.timecode
        if not tc:
            return

        try:
            from bg_spotter.pipeline.timing import tc_to_frame_index
            frame = tc_to_frame_index(tc, meta.fps_string, meta.drop_frame)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Timecode", str(exc))
            return

        new_edit = Edit(start_frame=frame, end_frame=frame, kind="hard")
        self._edits.append(new_edit)
        self._edits.sort(key=lambda e: e.start_frame)
        self._populate_table()

    def _on_generate(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save AAF", "", "AAF Files (*.aaf)"
        )
        if not path:
            return

        try:
            self._gen_btn.setEnabled(False)
            self._gen_btn.setText("Writing…")
            write_aaf(
                output_path=path,
                meta=self._results.meta,
                edits=self._edits,
                walking_ranges=self._results.walking_ranges,
                overlap_frames=self._config.overlap_frames,
                include_steps=self._config.include_steps,
            )
            self._gen_btn.setText("Generate AAF…")
            self._gen_btn.setEnabled(True)
            QMessageBox.information(self, "Done", f"AAF written to:\n{path}")
            self.generate_done.emit(path)
        except Exception as exc:
            self._gen_btn.setText("Generate AAF…")
            self._gen_btn.setEnabled(True)
            QMessageBox.critical(self, "Error Writing AAF", str(exc))
