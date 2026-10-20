import subprocess
from unittest.mock import MagicMock

import pytest

import smol


def test_smol_importable():
    """Verify the smol package can be imported."""
    assert smol is not None


def test_cli_version():
    """Verify `smol --version` runs without error."""
    result = subprocess.run(
        ["smol", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "0.9.0" in result.stdout


def test_cli_doctor_no_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify `smol doctor` runs without error."""
    result = subprocess.run(
        ["smol", "doctor"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


def test_cli_doctor_with_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify `smol doctor` respects environment variables."""
    # when a required var is set, the check should pass
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    result = subprocess.run(
        ["smol", "doctor"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    output = result.stdout
    # XDG_SESSION_TYPE and XDG_CURRENT_DESKTOP should show ✓
    assert "✓ XDG_SESSION_TYPE" in output
    assert "✓ XDG_CURRENT_DESKTOP" in output


def test_cli_doctor_mock_which(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify `smol doctor` works when `which` is mocked and env vars are unset."""
    import smol.cli

    monkeypatch.setattr(smol.cli.shutil, "which", lambda cmd: None)
    monkeypatch.setattr(
        smol.cli.subprocess, "run", lambda *a, **k: MagicMock(returncode=1)
    )
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)

    exit_code = smol.cli.doctor()
    assert exit_code == 0

    output = capsys.readouterr().out
    assert "✓ Python" in output
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
