"""BG Spotter — single-window UI (red/black).

One-shot flow: pick video → pick overlap sizes → Spot & Export AAF.
No review step; detected-cut count and written tracks are reported inline.
"""

from __future__ import annotations

import os
import subprocess

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from bg_spotter.config import (
    APP_NAME, COMPANY_NAME, OVERLAP_CHOICES, DEFAULT_OVERLAPS,
    SUPPORTED_VIDEO_EXTS, FPS_RATES,
)
from bg_spotter.pipeline.runner import (
    CancelledError, SpotConfig, SpotResults, default_output_path,
    run_pipeline, tracks_for_selections,
)
from bg_spotter.pipeline.video_meta import probe_video

# ---------------------------------------------------------------------------
# Palette — black foundation, red accent (Akahon Audio)
# ---------------------------------------------------------------------------
BG        = "#0B0D0E"   # near-black page
SURFACE   = "#141718"   # card surface
SURFACE_2 = "#1B1F20"   # raised control
BORDER    = "#2A2F30"
TEXT      = "#F2F5F5"   # warm white (matches composerrob.com text)
MUTED     = "#8FA0A0"
RED       = "#E03A3A"   # primary accent
RED_HOVER = "#F04B4B"
RED_DIM   = "#7A1F1F"
GREEN_OK  = "#5FBF7F"

STYLE = f"""
QMainWindow, QWidget {{ background: {BG}; color: {TEXT};
    font-family: -apple-system, 'Helvetica Neue', Helvetica, sans-serif;
    font-size: 13px; }}
QLabel#wordmark {{ color: {TEXT}; letter-spacing: 2px; }}
QLabel#wordmark-accent {{ color: {RED}; letter-spacing: 2px; }}
QLabel#subtitle {{ color: {MUTED}; font-size: 11px; }}
QLabel#status {{ color: {MUTED}; }}
QLabel#result-ok {{ color: {GREEN_OK}; }}
QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER};
    border-radius: 10px; }}
QLabel#cardtitle {{ color: {MUTED}; font-size: 11px; letter-spacing: 1.5px;
    font-weight: 600; }}
QLineEdit, QSpinBox, QComboBox {{ background: {SURFACE_2}; border: 1px solid {BORDER};
    border-radius: 6px; padding: 6px 8px; color: {TEXT}; selection-background-color: {RED};
    min-height: 18px; }}
QScrollArea {{ border: none; background: transparent; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {RED}; }}
QPushButton#secondary {{ background: {SURFACE_2}; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 14px; }}
QPushButton#secondary:hover {{ border-color: {RED_DIM}; }}
QPushButton#primary {{ background: {RED}; color: white; border: none;
    border-radius: 8px; padding: 12px 20px; font-size: 14px; font-weight: 700;
    letter-spacing: 0.5px; }}
QPushButton#primary:hover {{ background: {RED_HOVER}; }}
QPushButton#primary:disabled {{ background: {SURFACE_2}; color: {MUTED}; }}
QCheckBox {{ color: {TEXT}; spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid {BORDER}; background: {SURFACE_2}; }}
QCheckBox::indicator:checked {{ background: {RED}; border-color: {RED}; }}
QProgressBar {{ background: {SURFACE_2}; border: 1px solid {BORDER};
    border-radius: 6px; height: 10px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {RED}; border-radius: 5px; }}
QFrame#dropzone {{ background: {SURFACE}; border: 2px dashed {BORDER};
    border-radius: 10px; }}
QFrame#dropzone[dragOver="true"] {{ border-color: {RED}; }}
"""


def _log_file_path() -> str:
    base = os.path.expanduser("~/Library/Logs/BG Spotter")
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        base = os.path.expanduser("~")
    return os.path.join(base, "bgspotter.log")


def _log_exception(context: str) -> None:
    """Append the active traceback to a real file.

    Launched from Finder, stdout/stderr go to /dev/null, so an uncaught error is
    invisible and the app merely looks frozen - which is exactly how the
    insertWidget crash presented. Keep a trail on disk instead.
    """
    import time
    import traceback
    try:
        with open(_log_file_path(), "a", encoding="utf-8") as fh:
            fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {context} ===\n")
            traceback.print_exc(file=fh)
    except OSError:
        pass


def install_crash_log() -> None:
    """Route uncaught exceptions to the log file as well as stderr."""
    import sys
    import time
    import traceback

    def hook(etype, value, tb):
        try:
            with open(_log_file_path(), "a", encoding="utf-8") as fh:
                fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} uncaught ===\n")
                traceback.print_exception(etype, value, tb, file=fh)
        except OSError:
            pass
        traceback.print_exception(etype, value, tb)

    sys.excepthook = hook


class _Worker(QThread):
    progress = Signal(str, int)
    completed = Signal(object)   # SpotResults
    failed = Signal(str)

    def __init__(self, config: SpotConfig):
        super().__init__()
        self._config = config
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            results = run_pipeline(
                self._config,
                on_progress=lambda label, pct: self.progress.emit(label, pct),
                cancel_check=lambda: self._cancel,
            )
            self.completed.emit(results)
        except CancelledError:
            self.failed.emit("__CANCELLED__")
        except Exception as exc:  # surfaced verbatim to the user
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — {COMPANY_NAME}")
        self.setMinimumSize(640, 560)
        self.setAcceptDrops(True)
        self._worker: _Worker | None = None
        self._video_path = ""
        self._build_ui()

    # ---------------------------------------------------------------- UI --
    def _build_ui(self) -> None:
        content = QWidget()
        root = QVBoxLayout(content)
        # Keep a handle on the content layout.  QMainWindow.layout() returns a
        # QMainWindowLayout, which PySide6 does not expose insertWidget /
        # insertLayout on - using it crashed _on_go before the worker ever
        # started, leaving the button stuck on "Working…" with nothing running.
        self._root = root
        self._content = content
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        # ---- Header ----------------------------------------------------
        header = QHBoxLayout()
        title = QLabel()
        mark = QLabel("BG ")
        mark.setObjectName("wordmark")
        mark_font = QFont(); mark_font.setPointSize(20); mark_font.setBold(True)
        mark.setFont(mark_font)
        accent = QLabel("SPOTTER")
        accent.setObjectName("wordmark-accent")
        accent.setFont(mark_font)
        head_inner = QHBoxLayout()
        head_inner.setSpacing(0)
        head_inner.addWidget(mark)
        head_inner.addWidget(accent)
        head_inner.addStretch()
        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)
        title_layout.addLayout(head_inner)
        subtitle = QLabel("Edit-point guide tracks for Pro Tools · " + COMPANY_NAME)
        subtitle.setObjectName("subtitle")
        title_layout.addWidget(subtitle)
        header.addLayout(title_layout)
        header.addStretch()
        root.addLayout(header)

        # ---- Video drop zone -------------------------------------------
        self._drop = QFrame()
        self._drop.setObjectName("dropzone")
        drop_layout = QVBoxLayout(self._drop)
        drop_layout.setContentsMargins(18, 20, 18, 20)
        self._drop_label = QLabel("Drop a video here, or")
        self._drop_label.setAlignment(Qt.AlignCenter)
        browse = QPushButton("Browse…")
        browse.setObjectName("secondary")
        browse.setCursor(Qt.PointingHandCursor)
        browse.clicked.connect(self._on_browse)
        row = QHBoxLayout(); row.setSpacing(10)
        row.addStretch()
        row.addWidget(self._drop_label)
        row.addWidget(browse)
        row.addStretch()
        drop_layout.addLayout(row)
        self._path_label = QLabel("")
        self._path_label.setAlignment(Qt.AlignCenter)
        self._path_label.setStyleSheet(f"color: {TEXT};")
        self._path_label.setWordWrap(True)
        drop_layout.addWidget(self._path_label)
        root.addWidget(self._drop)

        # ---- Overlap selection ------------------------------------------
        card_overlaps = self._card("OVERLAP SIZES  ·  each adds an A / B track pair")
        grid = QHBoxLayout()
        grid.setSpacing(18)
        self._overlap_checks: dict[int, QCheckBox] = {}
        for n in OVERLAP_CHOICES:
            cb = QCheckBox(f"{n} frame" + ("s" if n > 1 else ""))
            cb.setChecked(n in DEFAULT_OVERLAPS)
            grid.addWidget(cb)
            self._overlap_checks[n] = cb
        grid.addStretch()
        card_overlaps.layout().addLayout(grid)
        hint = QLabel("Overlap is centred on each hard cut — adjacent A/B clips "
                      "share N frames of handle. Pick any combination.")
        hint.setObjectName("status")
        hint.setWordWrap(True)
        card_overlaps.layout().addWidget(hint)
        root.addWidget(card_overlaps)

        # ---- Metadata (auto-filled, editable) ---------------------------
        card_meta = self._card("METADATA  ·  auto-detected from the file")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(14)
        self._fps_combo = QComboBox()
        self._fps_combo.addItem("Auto")
        self._fps_combo.addItems(list(FPS_RATES.keys()))
        self._df_check = QCheckBox("Drop-frame")
        self._tc_edit = QLineEdit("01:00:00:00")
        form.addRow("Frame rate:", self._fps_combo)
        form.addRow("", self._df_check)
        form.addRow("Start TC:", self._tc_edit)
        card_meta.layout().addLayout(form)
        root.addWidget(card_meta)

        # ---- Output ------------------------------------------------------
        card_out = self._card("OUTPUT")
        out_row = QHBoxLayout()
        self._out_edit = QLineEdit()
        self._out_edit.setPlaceholderText("AAF path — auto-named from the video once selected")
        out_browse = QPushButton("Save As…")
        out_browse.setObjectName("secondary")
        out_browse.clicked.connect(self._on_out_browse)
        out_row.addWidget(self._out_edit)
        out_row.addWidget(out_browse)
        card_out.layout().addLayout(out_row)
        self._tracks_preview = QLabel("")
        self._tracks_preview.setObjectName("status")
        self._tracks_preview.setWordWrap(True)
        card_out.layout().addWidget(self._tracks_preview)
        root.addWidget(card_out)

        # ---- Action ------------------------------------------------------
        self._go_btn = QPushButton("Spot & Export AAF")
        self._go_btn.setObjectName("primary")
        self._go_btn.setCursor(Qt.PointingHandCursor)
        self._go_btn.clicked.connect(self._on_go)
        root.addWidget(self._go_btn)

        # ---- Progress / result ------------------------------------------
        self._bar = None
        self._cancel_btn = None
        self._reveal_btn = None
        self._status = QLabel(" ")
        self._status.setObjectName("status")
        self._status.setWordWrap(True)
        root.addWidget(self._status)
        root.addStretch()

        # Scroll rather than squeeze.  Without this, every row added at runtime
        # (progress bar, Reveal in Finder) competes for a fixed window height and
        # Qt shrinks the line edits below their size hint until the text clips.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        self.setCentralWidget(scroll)

        self._refresh_tracks_preview()
        for cb in self._overlap_checks.values():
            cb.toggled.connect(self._refresh_tracks_preview)

    def _card(self, title: str) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)
        t = QLabel(title)
        t.setObjectName("cardtitle")
        lay.addWidget(t)
        return card

    # ------------------------------------------------------- drag & drop --
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._video_event_ok(event):
            self._drop.setProperty("dragOver", "true")
            self._drop.style().unpolish(self._drop); self._drop.style().polish(self._drop)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._drop.setProperty("dragOver", "false")
        self._drop.style().unpolish(self._drop); self._drop.style().polish(self._drop)

    def dropEvent(self, event: QDropEvent) -> None:
        self._drop.setProperty("dragOver", "false")
        self._drop.style().unpolish(self._drop); self._drop.style().polish(self._drop)
        if self._video_event_ok(event):
            path = event.mimeData().urls()[0].toLocalFile()
            event.acceptProposedAction()
            self._set_video(path)

    @staticmethod
    def _video_event_ok(event) -> bool:
        md = event.mimeData()
        if not md.hasUrls():
            return False
        path = md.urls()[0].toLocalFile()
        return os.path.splitext(path)[1].lower() in SUPPORTED_VIDEO_EXTS

    # ------------------------------------------------------------ slots --
    def _on_browse(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(SUPPORTED_VIDEO_EXTS))
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File", "", f"Video ({exts});;All Files (*)")
        if path:
            self._set_video(path)

    def _set_video(self, path: str) -> None:
        self._video_path = path
        self._path_label.setText(os.path.basename(path))
        self._drop_label.setText("Video selected — drop another to replace")
        try:
            meta = probe_video(path)
            idx = self._fps_combo.findText(meta.fps_string)
            if idx >= 0:
                self._fps_combo.setCurrentIndex(idx)
            self._df_check.setChecked(meta.drop_frame)
            self._tc_edit.setText(meta.start_tc)
        except Exception:
            pass  # leave defaults; detection will surface any real problem
        self._refresh_output_default()

    def _refresh_output_default(self) -> None:
        if not self._video_path:
            return
        sel = self._selected_overlaps()
        if sel:
            self._out_edit.setText(default_output_path(self._video_path, sel))

    def _on_out_browse(self) -> None:
        sel = self._selected_overlaps()
        suggestion = ""
        if self._video_path and sel:
            suggestion = default_output_path(self._video_path, sel)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save AAF", suggestion, "AAF Files (*.aaf)")
        if path:
            if not path.lower().endswith(".aaf"):
                path += ".aaf"
            self._out_edit.setText(path)

    def _selected_overlaps(self) -> list[int]:
        return [n for n, cb in self._overlap_checks.items() if cb.isChecked()]

    def _refresh_tracks_preview(self) -> None:
        sel = self._selected_overlaps()
        self._refresh_output_default()
        if not sel:
            self._tracks_preview.setText("No overlap sizes selected.")
            return
        names = tracks_for_selections(sel)
        self._tracks_preview.setText(
            f"{len(names)} tracks → " + ", ".join(names))

    def _on_go(self) -> None:
        if not self._video_path:
            QMessageBox.warning(self, "No Video", "Drop or browse to a video file first.")
            return
        sel = self._selected_overlaps()
        if not sel:
            QMessageBox.warning(
                self, "No Overlaps",
                "Select at least one overlap size (1–6 frames).")
            return
        out = self._out_edit.text().strip()
        if not out:
            self._on_out_browse()
            out = self._out_edit.text().strip()
            if not out:
                return

        fps = None if self._fps_combo.currentText() == "Auto" else self._fps_combo.currentText()
        config = SpotConfig(
            video_path=self._video_path,
            output_path=out,
            overlap_selections=sel,
            fps_string=fps,
            drop_frame=self._df_check.isChecked(),
            start_tc=self._tc_edit.text().strip() or None,
        )

        self._go_btn.setEnabled(False)
        self._go_btn.setText("Working…")
        try:
            if self._bar is None:
                self._bar = QProgressBar()
                self._bar.setRange(0, 100)
                self._root.insertWidget(self._root.indexOf(self._status), self._bar)
            self._bar.show()
            self._bar.setValue(0)
        except Exception as exc:      # never leave the button stuck on "Working…"
            self._reset_action()
            self._status.setStyleSheet(f"color: {RED};")
            self._status.setText(f"✗  Failed to start: {exc}")
            _log_exception("progress bar setup")
            return
        self._status.setText("Starting…")
        self._status.setStyleSheet("")

        self._worker = _Worker(config)
        self._worker.progress.connect(self._on_progress)
        self._worker.completed.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        try:
            self._worker.start()
        except Exception as exc:
            self._reset_action()
            self._status.setStyleSheet(f"color: {RED};")
            self._status.setText(f"✗  Failed to start worker: {exc}")
            _log_exception("worker start")

    def _on_progress(self, label: str, pct: int) -> None:
        if self._bar is not None:
            self._bar.setValue(pct)
        self._status.setText(label)

    def _on_done(self, results: SpotResults) -> None:
        self._reset_action()
        self._status.setObjectName("result-ok")
        self._status.setStyleSheet(f"color: {GREEN_OK};")
        self._status.setText(
            f"✓  {len(results.edits)} edits spotted · {len(results.track_names)} tracks written to\n"
            f"{results.output_path}")
        if os.path.isfile(results.output_path):
            self._reveal_button(results.output_path)

    def _on_failed(self, message: str) -> None:
        self._reset_action()
        if message == "__CANCELLED__":
            self._status.setText("Cancelled.")
            return
        self._status.setStyleSheet(f"color: {RED};")
        self._status.setText(f"✗  Failed: {message}")

    def _reveal_button(self, path: str) -> None:
        """Create the row once, then only retarget it.

        Inserting a fresh row on every success stacked up over repeated runs and
        squeezed the rest of the window until fields collapsed.
        """
        if self._reveal_btn is None:
            btn = QPushButton("Reveal in Finder")
            btn.setObjectName("secondary")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(self._reveal_in_finder)
            row = QHBoxLayout()
            row.addWidget(btn)
            row.addStretch()
            self._root.insertLayout(self._root.indexOf(self._status) + 1, row)
            self._reveal_btn = btn
        self._reveal_path = path
        self._reveal_btn.show()

    def _reveal_in_finder(self) -> None:
        path = getattr(self, "_reveal_path", "")
        if path and os.path.exists(path):
            subprocess.Popen(["open", "-R", os.path.abspath(path)])

    def _reset_action(self) -> None:
        self._go_btn.setEnabled(True)
        self._go_btn.setText("Spot & Export AAF")
        if self._bar is not None:
            self._bar.hide()

    # ------------------------------------------------------------- close --
    def closeEvent(self, event) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        super().closeEvent(event)


def main() -> None:
    import sys
    install_crash_log()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(COMPANY_NAME)
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
