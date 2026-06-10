"""Application entry point.

Run with:
    python -m bg_spotter
or, after `pip install -e .`:
    bg-spotter
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QMessageBox

from bg_spotter.gui.input_window import InputWindow
from bg_spotter.gui.progress import ProgressDialog, PipelineWorker, SpotConfig, SpotResults
from bg_spotter.gui.review_window import ReviewWindow


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BG Spotter")
        self.setMinimumSize(700, 500)

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._input_page = InputWindow()
        self._stack.addWidget(self._input_page)

        self._input_page.spot_requested.connect(self._on_spot_requested)

        self._worker: PipelineWorker | None = None
        self._progress_dialog: ProgressDialog | None = None
        self._config: SpotConfig | None = None

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def _on_spot_requested(self, config: SpotConfig) -> None:
        self._config = config
        self._start_pipeline(config)

    def _start_pipeline(self, config: SpotConfig) -> None:
        self._worker = PipelineWorker(config)
        self._worker.progress.connect(self._on_progress)
        self._worker.completed.connect(self._on_pipeline_done)
        self._worker.failed.connect(self._on_pipeline_failed)

        self._progress_dialog = ProgressDialog(self)
        self._progress_dialog.cancelled.connect(self._on_cancel)
        self._progress_dialog.show()

        self._worker.start()

    def _on_progress(self, label: str, pct: int) -> None:
        if self._progress_dialog:
            self._progress_dialog.update_progress(label, pct)

    def _on_pipeline_done(self, results: SpotResults) -> None:
        if self._progress_dialog:
            self._progress_dialog.accept()
            self._progress_dialog = None

        review = ReviewWindow(results, self._config, self)
        review.back_requested.connect(self._on_back_to_input)
        review.generate_done.connect(self._on_aaf_written)

        # Remove any previous review page before adding a new one
        if self._stack.count() > 1:
            old = self._stack.widget(1)
            self._stack.removeWidget(old)
            old.deleteLater()

        self._stack.addWidget(review)
        self._stack.setCurrentIndex(1)

    def _on_pipeline_failed(self, message: str) -> None:
        if self._progress_dialog:
            self._progress_dialog.reject()
            self._progress_dialog = None
        QMessageBox.critical(self, "Processing Failed", message)

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()

    def _on_back_to_input(self) -> None:
        self._stack.setCurrentIndex(0)

    def _on_aaf_written(self, path: str) -> None:
        # Stay on the review page; user may want to tweak and regenerate
        pass


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("BG Spotter")
    app.setOrganizationName("ComposeRob")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
