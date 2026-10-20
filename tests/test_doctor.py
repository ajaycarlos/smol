import shutil
import subprocess
import sys
from unittest.mock import MagicMock

import pytest

import smol.cli


def test_doctor_all_present(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """When dependencies and env vars are present, all items show ✓."""
    monkeypatch.setattr(sys, "version_info", (3, 12, 3, "final", 0))
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")

    # Mock shutil.which to find any binary
    monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

    # Mock subprocess.run for pgrep so nautilus appears as running
    def fake_subprocess_run(cmd, *args, **kwargs):
        mock_res = MagicMock()
        if cmd[0] == "pgrep" and "nautilus" in cmd:
            mock_res.returncode = 0
            mock_res.stdout = "1234\n"
        else:
            mock_res.returncode = 1
            mock_res.stdout = ""
        return mock_res

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    exit_code = smol.cli.doctor()
    assert exit_code == 0

    captured = capsys.readouterr()
    output = captured.out

    assert "✓ Python" in output
    assert "✓ uv" in output
    assert "✓ ffmpeg" in output
    assert "✓ ffprobe" in output
    assert "✓ gs (Ghostscript)" in output or "✓ ghostscript" in output.lower()
    assert "✓ qpdf" in output
    assert "✓ git" in output
    assert "✓ XDG_SESSION_TYPE" in output
    assert "✓ XDG_CURRENT_DESKTOP" in output
    assert "✓ file manager: nautilus (running)" in output or "✓ file manager" in output
    assert "✓ notify-send" in output
    assert "✗" not in output


def test_doctor_all_missing_and_hints(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """When tools are missing and env vars unset, ✗ is shown with hints."""
    monkeypatch.setattr(sys, "version_info", (3, 10, 5, "final", 0))
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)

    monkeypatch.setattr(shutil, "which", lambda cmd: None)

    def fake_subprocess_run(cmd, *args, **kwargs):
        mock_res = MagicMock()
        mock_res.returncode = 1
        mock_res.stdout = ""
        return mock_res

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    exit_code = smol.cli.doctor()
    assert exit_code == 0

    captured = capsys.readouterr()
    output = captured.out

    assert "✗ Python" in output
    assert "✗ uv" in output
    assert "ffmpeg (optional" in output
    assert "ffprobe (optional" in output
    assert "✗ ffmpeg" not in output
    assert "✗ ffprobe" not in output
    assert "✗ gs" in output
    assert "✗ qpdf" in output
    assert "✗ git" in output
    assert "✗ XDG_SESSION_TYPE" in output
    assert "✗ XDG_CURRENT_DESKTOP" in output
    assert "✗ default file manager" in output
    assert "✗ notify-send" in output


def test_doctor_file_manager_installed_not_running(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """When file manager is not running but on PATH, report as installed."""
    monkeypatch.setattr(sys, "version_info", (3, 12, 1, "final", 0))
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "XFCE")

    # pgrep fails (nothing running)
    def fake_subprocess_run(cmd, *args, **kwargs):
        mock_res = MagicMock()
        mock_res.returncode = 1
        return mock_res

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    # only thunar is installed
    known_tools = ("uv", "git", "ffmpeg", "ffprobe", "gs", "qpdf", "notify-send")

    def fake_which(cmd: str):
        if cmd == "thunar":
            return "/usr/bin/thunar"
        return f"/usr/bin/{cmd}" if cmd in known_tools else None

    monkeypatch.setattr(shutil, "which", fake_which)

    exit_code = smol.cli.doctor()
    assert exit_code == 0

    captured = capsys.readouterr()
    output = captured.out
    assert "thunar (installed)" in output


def test_doctor_main_cli_dispatch(capsys: pytest.CaptureFixture[str]) -> None:
    """`smol.cli.main(['doctor'])` correctly invokes doctor and returns 0."""
    code = smol.cli.main(["doctor"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Python" in captured.out
