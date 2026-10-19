"""Tests for the OS-specific helpers that keep the app portable."""

from __future__ import annotations

import os
import sys

import pytest

from bg_spotter import platform_utils


@pytest.fixture()
def fake_popen(monkeypatch):
    calls = []

    class FakeProc:
        pass

    def popen(args, *a, **kw):
        calls.append(list(args))
        return FakeProc()

    monkeypatch.setattr(platform_utils.subprocess, "Popen", popen)
    return calls


def test_log_dir_macos(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setenv("HOME", str(tmp_path))
    got = platform_utils.log_dir()
    assert got == str(tmp_path / "Library" / "Logs" / "BG Spotter")


def test_log_dir_windows_uses_localappdata(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(os, "name", "nt")
    local = tmp_path / "AppData" / "Local"
    local.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    got = platform_utils.log_dir()
    assert got == str(local / "BG Spotter" / "Logs")
    # Must not be a bogus C:\Users\you\Library path.
    assert "Library" not in got


def test_log_dir_falls_back_instead_of_raising(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setenv("HOME", str(tmp_path))

    def boom(*a, **kw):
        raise OSError("read-only volume")

    monkeypatch.setattr(platform_utils.os, "makedirs", boom)
    assert platform_utils.log_dir() == str(tmp_path)


def test_reveal_macos_uses_open_dash_r(monkeypatch, fake_popen, tmp_path):
    f = tmp_path / "spots.aaf"
    f.write_bytes(b"x")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(os, "name", "posix")
    assert platform_utils.reveal_in_file_manager(str(f)) is True
    assert fake_popen == [["open", "-R", str(f)]]


def test_reveal_windows_uses_explorer_select(monkeypatch, fake_popen, tmp_path):
    f = tmp_path / "spots.aaf"
    f.write_bytes(b"x")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(os, "name", "nt")
    assert platform_utils.reveal_in_file_manager(str(f)) is True
    assert len(fake_popen) == 1
    cmd = fake_popen[0]
    assert cmd[0] == "explorer"
    assert cmd[1] == "/select,"
    assert cmd[2] == str(f)


def test_reveal_missing_path_does_nothing(monkeypatch, fake_popen, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(os, "name", "posix")
    assert platform_utils.reveal_in_file_manager(str(tmp_path / "gone.aaf")) is False
    assert fake_popen == []


def test_reveal_swallows_missing_helper(monkeypatch, tmp_path):
    """A desktop shell that isn't installed must not look like an export failure."""
    f = tmp_path / "spots.aaf"
    f.write_bytes(b"x")

    def boom(*a, **kw):
        raise OSError("no xdg-open")

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(platform_utils.subprocess, "Popen", boom)
    assert platform_utils.reveal_in_file_manager(str(f)) is False
