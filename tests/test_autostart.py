"""Tests for smol integrate autostart."""

from pathlib import Path

from smol.cli import main
from smol.integrations.autostart import (
    AutostartIntegrator,
    get_autostart_dir,
)


def test_autostart_install_creates_desktop_file(tmp_path: Path):
    """Verify autostart install creates a valid .desktop file."""
    autostart_dir = tmp_path / "autostart"
    integrator = AutostartIntegrator(
        autostart_dir=autostart_dir,
        smol_bin="/custom/bin/smol",
    )

    result = integrator.install()
    assert result.ok is True
    assert "installed" in result.message.lower()

    desktop_file = autostart_dir / "smol.desktop"
    assert desktop_file.exists()

    content = desktop_file.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in content
    assert "Type=Application" in content
    assert "Name=smol daemon" in content
    assert "Exec=/custom/bin/smol daemon start" in content
    assert "Terminal=false" in content
    assert "X-GNOME-Autostart-enabled=true" in content


def test_autostart_install_idempotent(tmp_path: Path):
    """Verify calling install multiple times succeeds and keeps file consistent."""
    autostart_dir = tmp_path / "autostart"
    integrator = AutostartIntegrator(
        autostart_dir=autostart_dir,
        smol_bin="/custom/bin/smol",
    )

    # First install
    res1 = integrator.install()
    assert res1.ok is True

    # Second install
    res2 = integrator.install()
    assert res2.ok is True
    assert "installed" in res2.message.lower()

    desktop_file = autostart_dir / "smol.desktop"
    assert desktop_file.exists()
    content = desktop_file.read_text(encoding="utf-8")
    assert content.count("[Desktop Entry]") == 1


def test_autostart_uninstall_removes_cleanly(tmp_path: Path):
    """Verify uninstall removes the desktop file and reports clean removal."""
    autostart_dir = tmp_path / "autostart"
    integrator = AutostartIntegrator(
        autostart_dir=autostart_dir,
        smol_bin="/custom/bin/smol",
    )

    integrator.install()
    desktop_file = autostart_dir / "smol.desktop"
    assert desktop_file.exists()

    un_res = integrator.uninstall()
    assert un_res.ok is True
    assert "uninstalled" in un_res.message.lower()
    assert not desktop_file.exists()


def test_get_autostart_dir(monkeypatch, tmp_path: Path):
    """Verify get_autostart_dir honors XDG_CONFIG_HOME and default fallback."""
    custom_xdg = tmp_path / "custom_xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(custom_xdg))
    assert get_autostart_dir() == custom_xdg / "autostart"

    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    assert get_autostart_dir() == tmp_path / "home" / ".config" / "autostart"


def test_autostart_uninstall_idempotent(tmp_path: Path):
    """Verify calling uninstall when not installed succeeds without error."""
    autostart_dir = tmp_path / "autostart"
    integrator = AutostartIntegrator(
        autostart_dir=autostart_dir,
        smol_bin="/custom/bin/smol",
    )

    # When file does not exist
    desktop_file = autostart_dir / "smol.desktop"
    assert not desktop_file.exists()

    un_res = integrator.uninstall()
    assert un_res.ok is True
    msg = un_res.message.lower()
    assert "not installed" in msg or "uninstalled" in msg


def test_autostart_status(tmp_path: Path):
    """Verify status accurately reports installed vs not installed."""
    autostart_dir = tmp_path / "autostart"
    integrator = AutostartIntegrator(
        autostart_dir=autostart_dir,
        smol_bin="/custom/bin/smol",
    )

    status_before = integrator.status()
    assert status_before.installed is False

    integrator.install()
    status_after = integrator.status()
    assert status_after.installed is True
    assert str(status_after.desktop_file) == str(autostart_dir / "smol.desktop")


def test_cli_integrate_autostart(tmp_path: Path, monkeypatch, capsys):
    """Verify CLI routing for smol integrate autostart install/status/uninstall."""
    autostart_dir = tmp_path / "autostart"
    monkeypatch.setattr(
        "smol.integrations.autostart.get_autostart_dir",
        lambda: autostart_dir,
    )

    # Status when not installed
    code = main(["integrate", "autostart", "status"])
    assert code == 0
    captured = capsys.readouterr()
    msg = captured.out.lower()
    assert "not enabled" in msg or "not installed" in msg

    # Install
    code = main(["integrate", "autostart", "install"])
    assert code == 0
    captured = capsys.readouterr()
    assert "installed" in captured.out.lower() or "enabled" in captured.out.lower()
    assert (autostart_dir / "smol.desktop").exists()

    # Status when installed
    code = main(["integrate", "autostart", "status"])
    assert code == 0
    captured = capsys.readouterr()
    assert "installed" in captured.out.lower() or "enabled" in captured.out.lower()

    # Uninstall
    code = main(["integrate", "autostart", "uninstall"])
    assert code == 0
    captured = capsys.readouterr()
    assert "uninstalled" in captured.out.lower() or "removed" in captured.out.lower()
    assert not (autostart_dir / "smol.desktop").exists()

