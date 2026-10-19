"""Headless regression tests for the main window's export path.

Why these exist: the v2 GUI crashed inside _on_go at
QMainWindow.layout().insertWidget(...) - PySide6 does not expose insertWidget /
insertLayout on QMainWindowLayout. The exception fired AFTER the button was set
to "Working…" and BEFORE the QThread was created, so every double-click export
silently did nothing (stdout went to /dev/null under Finder launch). No test
ever called _on_go, so it shipped.

These run offscreen; no display required.
"""

from __future__ import annotations

import os
import sys
import time

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from bg_spotter.gui.main_window import MainWindow  # noqa: E402
from bg_spotter.aaf.silence import generate_silent_wav  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def qapp():
    """Any QWidget needs a QApplication first, or Qt aborts the process."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def tiny_video(tmp_path):
    """A short real .mov if one is available, else skip.

    Uses the repo's e2e clip when present; otherwise skips rather than faking a
    video file, because _on_go runs the real pipeline.
    """
    cand = os.path.join(os.path.dirname(__file__), "..", "tmp", "cuts4.mov")
    cand = os.path.abspath(cand)
    if not os.path.isfile(cand):
        pytest.skip("no test video available (tmp/cuts4.mov)")
    return cand


def test_content_layout_is_stored():
    """_on_go inserts the progress bar into self._root, never QMainWindow.layout()."""
    w = MainWindow()
    assert hasattr(w, "_root"), "MainWindow must keep a reference to its content layout"
    # The crash was calling methods that do not exist on QMainWindowLayout.
    win_layout = w.layout()
    if win_layout is not None and not hasattr(win_layout, "insertWidget"):
        # Expected on PySide6: proves _root (a QVBoxLayout) is required.
        assert hasattr(w._root, "insertWidget")


def test_on_go_starts_worker_and_completes(qapp, tiny_video, tmp_path):
    w = MainWindow()
    w._video_path = tiny_video
    out = str(tmp_path / "gui_export.aaf")
    w._out_edit.setText(out)

    w._on_go()

    status = w._status.text()
    assert "Failed" not in status, f"_on_go failed instead of starting: {status}"
    assert w._worker is not None, "_on_go never created a worker (this was the bug)"
    assert w._worker.isRunning(), "worker was created but never started"

    deadline = time.time() + 240
    while time.time() < deadline:
        qapp.processEvents()
        if not w._worker.isRunning():
            break
        time.sleep(0.1)
    qapp.processEvents()

    final = w._status.text()
    assert "Failed" not in final, f"export reported failure: {final}"
    assert os.path.isfile(out), f"no AAF written; status was {final!r}"
    # Button must return to its idle label - never stuck on "Working…".
    assert w._go_btn.text() == "Spot & Export AAF"

    # And the file must be a valid, silent guide-track AAF.
    aaf2 = pytest.importorskip("aaf2")
    with aaf2.open(out) as f:
        mobs = list(f.content.mobs)
        kinds = [type(m).__name__ for m in mobs]
        assert "CompositionMob" in kinds
        comp = next(m for m in mobs if type(m).__name__ == "CompositionMob")
        assert len(list(comp.slots)) >= 2
        src = next(m for m in mobs if type(m).__name__ == "SourceMob")
        seg = list(src.slots)[0].segment
        assert type(seg).__name__ == "SourceClip", (
            "file-mob slot must hold a SourceClip, not a Filler - see ROOT_CAUSE.md")


def test_fields_stay_readable_after_repeated_runs(qapp, tiny_video, tmp_path):
    """Regression: runtime rows used to squeeze line edits until text clipped.

    The window had no scroll area, so every row added at runtime (progress bar,
    and Reveal in Finder - inserted afresh on each success) competed for a fixed
    height and Qt shrank the inputs below their size hint.
    """
    from PySide6.QtWidgets import QPushButton

    w = MainWindow()
    w.resize(640, 560)          # minimum size: worst case for squeezing
    w.show()
    qapp.processEvents()

    out = str(tmp_path / "layout_probe.aaf")
    for _ in range(2):          # two successes would have stacked the reveal row
        w._video_path = tiny_video
        w._out_edit.setText(out)
        w._on_go()
        deadline = time.time() + 240
        while time.time() < deadline:
            qapp.processEvents()
            if not w._worker.isRunning():
                break
            time.sleep(0.1)
        qapp.processEvents()

    reveals = [c for c in w._content.findChildren(QPushButton)
               if c.text() == "Reveal in Finder"]
    assert len(reveals) == 1, f"reveal row stacked {len(reveals)} times"

    # Shrink hard: the scroll area must absorb it rather than clip fields.
    w.resize(640, 380)
    qapp.processEvents()
    for name in ("_out_edit", "_tc_edit", "_fps_combo"):
        h = getattr(w, name).height()
        assert h >= 22, f"{name} collapsed to {h}px - text would be unreadable"


def test_zero_frame_option_offered_with_explanatory_label(qapp):
    """0 frames must be selectable and self-explanatory in the UI."""
    from bg_spotter.config import OVERLAP_CHOICES

    w = MainWindow()
    assert 0 in OVERLAP_CHOICES
    assert 0 in w._overlap_checks, "no checkbox for edit-points-only (0 frames)"
    text = w._overlap_checks[0].text().lower()
    assert "0 frames" in text and "edit point" in text

    # Every offered size gets a checkbox, and none of them share an object.
    assert set(w._overlap_checks) == set(OVERLAP_CHOICES)
    widgets = [cb for cb in w._overlap_checks.values()]
    assert len({id(cb) for cb in widgets}) == len(widgets)


def test_zero_frame_export_runs_end_to_end(qapp, tiny_video, tmp_path):
    """The GUI must honour a 0-frame selection, not silently fall back.

    Mirrors real usage: pick the overlaps first, then let the window name the
    file (toggling a checkbox rewrites the suggested path, so a path set before
    the toggles gets replaced).
    """
    import shutil

    video = tmp_path / os.path.basename(tiny_video)
    shutil.copyfile(tiny_video, video)      # keep artifacts out of the repo

    w = MainWindow()
    w._video_path = str(video)
    for n, cb in w._overlap_checks.items():
        cb.setChecked(n == 0)

    out = w._out_edit.text().strip()
    assert out.lower().endswith(".aaf"), "auto-naming produced no path"
    assert "0" in os.path.basename(out), (
        f"output name does not reflect the 0-frame selection: {out!r}")

    w._on_go()
    deadline = time.time() + 240
    while time.time() < deadline:
        qapp.processEvents()
        if not w._worker.isRunning():
            break
        time.sleep(0.1)
    qapp.processEvents()

    assert "Failed" not in w._status.text(), w._status.text()
    aaf2 = pytest.importorskip("aaf2")
    with aaf2.open(out) as f:
        comp = [m for m in f.content.mobs
                if type(m).__name__ == "CompositionMob"][0]
        names = [s.name for s in comp.slots]
    assert names == ["Edit Points Only A", "Edit Points Only B"], names
