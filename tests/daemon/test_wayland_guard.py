import pytest

import smol.cli
from smol.daemon.service import DaemonService

WAYLAND_REFUSAL_MSG = (
    "smol's hold-key donut needs an X11 session. Right-click integration and the smol "
    "CLI still work. Log out and choose an X11/Xorg session at the login screen, or "
    "use right-click."
)


def test_daemon_start_refuses_wayland(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`smol daemon start` detects XDG_SESSION_TYPE=wayland and exits 3."""
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.delenv("DISPLAY", raising=False)

    code = smol.cli.main(["daemon", "start"])
    assert code == 3

    captured = capsys.readouterr()
    err_out = captured.err + captured.out
    assert WAYLAND_REFUSAL_MSG in err_out


def test_daemon_run_refuses_wayland(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`smol daemon run` detects XDG_SESSION_TYPE=wayland and exits 3."""
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.delenv("DISPLAY", raising=False)

    code = smol.cli.main(["daemon", "run"])
    assert code == 3

    captured = capsys.readouterr()
    err_out = captured.err + captured.out
    assert WAYLAND_REFUSAL_MSG in err_out


def test_daemon_refuses_wayland_even_with_display(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Refuse even when DISPLAY exists (XWayland)."""
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

    code = smol.cli.main(["daemon", "start"])
    assert code == 3

    captured = capsys.readouterr()
    err_out = captured.err + captured.out
    assert WAYLAND_REFUSAL_MSG in err_out


def test_daemon_service_start_and_run_refuse_wayland(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path
) -> None:
    """DaemonService.start() and run() directly refuse when session is Wayland."""
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    service = DaemonService(state_dir=tmp_path / "state")

    assert service.start() == 3
    captured = capsys.readouterr()
    assert WAYLAND_REFUSAL_MSG in (captured.err + captured.out)

    assert service.run() == 3
    captured = capsys.readouterr()
    assert WAYLAND_REFUSAL_MSG in (captured.err + captured.out)


def test_doctor_shows_warning_for_wayland(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`smol doctor` outputs a warning row when session type is wayland."""
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")

    code = smol.cli.doctor()
    assert code == 0

    captured = capsys.readouterr()
    out = captured.out
    # Must show a warning row (not a tick ✓, not an error ✗)
    assert "! XDG_SESSION_TYPE (wayland" in out
    assert "hold-key donut needs X11" in out
