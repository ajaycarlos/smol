import os
import shutil
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
INSTALL_SH = ROOT_DIR / "install.sh"
UNINSTALL_SH = ROOT_DIR / "uninstall.sh"


def test_install_script_help():
    """install.sh --help exits with 0 and mentions dependencies."""
    proc = subprocess.run(
        [str(INSTALL_SH), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "Usage: ./install.sh" in proc.stdout
    assert "ghostscript" in proc.stdout
    assert "qpdf" in proc.stdout
    assert "libxcb-cursor0" in proc.stdout


def test_uninstall_script_help():
    """uninstall.sh --help exits with 0 and documents --purge."""
    proc = subprocess.run(
        [str(UNINSTALL_SH), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "Usage: ./uninstall.sh" in proc.stdout
    assert "--purge" in proc.stdout


def test_invalid_argument_handling():
    """Both scripts reject unknown arguments with exit code 2."""
    proc1 = subprocess.run(
        [str(INSTALL_SH), "--bogus-flag"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc1.returncode == 2

    proc2 = subprocess.run(
        [str(UNINSTALL_SH), "--bogus-flag"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc2.returncode == 2


def test_uninstall_purge_logic(tmp_path: Path):
    """uninstall.sh preserves config without --purge and deletes it with --purge."""
    custom_home = tmp_path / "home"
    custom_home.mkdir()
    config_dir = custom_home / ".config" / "smol"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "config.toml"
    config_file.write_text("trigger_key = 'Super'\n")

    autostart_file = custom_home / ".config" / "autostart" / "smol.desktop"
    autostart_file.parent.mkdir(parents=True, exist_ok=True)
    autostart_file.write_text("[Desktop Entry]\nType=Application\n")

    env = os.environ.copy()
    env["HOME"] = str(custom_home)
    env["XDG_CONFIG_HOME"] = str(custom_home / ".config")
    env["XDG_DATA_HOME"] = str(custom_home / ".local" / "share")
    env["XDG_STATE_HOME"] = str(custom_home / ".local" / "state")
    env["XDG_CACHE_HOME"] = str(custom_home / ".cache")

    # Run uninstall without --purge
    proc = subprocess.run(
        [str(UNINSTALL_SH), "-y"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert not autostart_file.exists()
    assert config_file.exists(), "Config file must be preserved without --purge"

    # Now run uninstall with --purge
    proc_purge = subprocess.run(
        [str(UNINSTALL_SH), "-y", "--purge"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_purge.returncode == 0
    assert not config_dir.exists(), "Config dir must be deleted with --purge"


def test_install_missing_uv_error(tmp_path: Path):
    """install.sh errors cleanly when uv is missing from PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Link standard utils needed by bash script (bash, dirname, readlink, etc.)
    for cmd in ["bash", "sh", "dirname", "cat", "id"]:
        cmd_path = shutil.which(cmd)
        if cmd_path:
            (bin_dir / cmd).symlink_to(cmd_path)

    env = os.environ.copy()
    env["PATH"] = str(bin_dir)
    proc = subprocess.run(
        [str(INSTALL_SH)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "'uv' is required" in proc.stderr


def test_install_wayland_skips_autostart(tmp_path: Path):
    """install.sh informs user and skips autostart when XDG_SESSION_TYPE=wayland."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    # Mock uv and smol to avoid real installation in this unit test
    fake_uv = bin_dir / "uv"
    fake_uv.write_text("#!/bin/sh\nexit 0\n")
    fake_uv.chmod(0o755)

    fake_smol = bin_dir / "smol"
    fake_smol.write_text("#!/bin/sh\nexit 0\n")
    fake_smol.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["XDG_SESSION_TYPE"] = "wayland"

    proc = subprocess.run(
        [str(INSTALL_SH), "-y"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "Autostart skipped: Current session is Wayland" in proc.stdout

