"""Application entry point.

Run with:
    python -m bg_spotter
or, after `pip install -e .`:
    bg-spotter

Self-test hook (used to verify frozen bundles): set BGSPOTTER_SELFTEST to a
video path and BGSPOTTER_SELFTEST_OUT to the target .aaf; the pipeline runs
headless and exits 0/1 without opening a window.
"""

import os
import sys


def _selftest() -> int:
    video = os.environ["BGSPOTTER_SELFTEST"]
    out = os.environ["BGSPOTTER_SELFTEST_OUT"]
    from bg_spotter.pipeline.runner import SpotConfig, run_pipeline

    try:
        res = run_pipeline(SpotConfig(
            video_path=video,
            output_path=out,
            overlap_selections=[2, 4],
        ))
        print(f"SELFTEST OK edits={len(res.edits)} tracks={len(res.track_names)}")
        return 0
    except Exception as exc:
        print(f"SELFTEST FAIL {exc}")
        return 1


if __name__ == "__main__":
    if os.environ.get("BGSPOTTER_SELFTEST"):
        sys.exit(_selftest())
    from bg_spotter.gui.main_window import main
    main()
