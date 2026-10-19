"""OS-specific behaviour, isolated so the rest of the app stays portable.

Everything platform-dependent lives here: where crash logs go, and how to reveal
a file in the desktop shell. macOS-only calls (``open -R``, ``~/Library/Logs``)
used to be inline in the GUI, which meant a Windows build would raise on the
Reveal button and write logs into a meaningless ``C:\\Users\\you\\Library``.
"""

from __future__ import annotations

import os
import subprocess
import sys


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_windows() -> bool:
    return os.name == "nt"


def log_dir() -> str:
    """Per-user directory for crash logs, created if possible.

    Falls back to the home directory rather than raising: a log path that cannot
    be written must never take down an export.
    """
    if is_windows():
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        base = os.path.join(base, "BG Spotter", "Logs")
    elif is_macos():
        base = os.path.join(os.path.expanduser("~"), "Library", "Logs", "BG Spotter")
    else:
        base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
        base = os.path.join(base, "bgspotter", "logs")

    try:
        os.makedirs(base, exist_ok=True)
        return base
    except OSError:
        return os.path.expanduser("~")


def reveal_in_file_manager(path: str) -> bool:
    """Select *path* in the desktop file manager. Returns False if unsupported.

    Never raises: this runs from a button click, and a missing helper binary
    should not look like an export failure.
    """
    abspath = os.path.abspath(path)
    if not os.path.exists(abspath):
        return False
    try:
        if is_windows():
            # explorer.exe exits non-zero even when it succeeds, so do not check.
            subprocess.Popen(["explorer", "/select,", abspath])
            return True
        if is_macos():
            subprocess.Popen(["open", "-R", abspath])
            return True
        # Linux/BSD: no "select" concept in xdg-open; open the containing folder.
        subprocess.Popen(["xdg-open", os.path.dirname(abspath)])
        return True
    except OSError:
        return False
