import os
import shutil
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
BUILD_DEB_SH = ROOT_DIR / "packaging" / "build_deb.sh"
DEB_PATH = ROOT_DIR / "dist" / "smol_0.9.0_amd64.deb"


def test_build_deb_script_exists_and_executable():
    """packaging/build_deb.sh exists and has execute permissions."""
    assert BUILD_DEB_SH.is_file()
    assert os.access(BUILD_DEB_SH, os.X_OK)


def test_deb_package_metadata():
    """dpkg-deb -I verifies package control metadata, architecture, and dependencies."""
    if not shutil.which("dpkg-deb"):
        return
    if not DEB_PATH.is_file():
        # Build if not already present
        proc = subprocess.run(
            [str(BUILD_DEB_SH)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0

    proc = subprocess.run(
        ["dpkg-deb", "-I", str(DEB_PATH)],
        capture_output=True,
        text=True,
        check=True,
    )
    info = proc.stdout
    assert "Package: smol" in info
    assert "Architecture: amd64" in info
    assert "Section: utils" in info
    assert "Depends:" in info
    # Core dependencies specified in requirements
    assert "ghostscript" in info
    assert "qpdf" in info
    assert "libxcb-cursor0" in info
    assert "libx11-xcb1" in info
    assert "libxcb-icccm4" in info
    assert "libxcb-image0" in info
    assert "libxcb-keysyms1" in info
    assert "libxcb-render-util0" in info
    assert "libxkbcommon-x11-0" in info
    assert "Recommends: libnotify-bin" in info
    assert "postinst" in info
    assert "postrm" in info


def test_deb_package_contents_layout():
    """dpkg-deb -c verifies /opt/smol/, symlink /usr/bin/smol, desktop, and icons."""
    if not shutil.which("dpkg-deb"):
        return
    assert DEB_PATH.is_file()

    proc = subprocess.run(
        ["dpkg-deb", "-c", str(DEB_PATH)],
        capture_output=True,
        text=True,
        check=True,
    )
    contents = proc.stdout

    # Application payload in /opt/smol/
    assert "./opt/smol/smol" in contents
    # Symlink /usr/bin/smol -> /opt/smol/smol
    assert "./usr/bin/smol -> /opt/smol/smol" in contents
    # Desktop entry in /usr/share/applications/
    assert "./usr/share/applications/smol.desktop" in contents
    # Hicolor icon theme
    assert "./usr/share/icons/hicolor/scalable/apps/smol.svg" in contents
    for size in [16, 24, 32, 48, 64, 128, 256, 512]:
        assert f"./usr/share/icons/hicolor/{size}x{size}/apps/smol.png" in contents


def test_deb_maintainer_scripts_safety():
    """postinst and postrm refresh system caches without touching user files."""
    if not shutil.which("dpkg-deb"):
        return
    assert DEB_PATH.is_file()

    # Extract control directory
    ctrl_dir = ROOT_DIR / "build" / "deb_test_ctrl"
    shutil.rmtree(ctrl_dir, ignore_errors=True)
    subprocess.run(
        ["dpkg-deb", "-e", str(DEB_PATH), str(ctrl_dir)],
        capture_output=True,
        text=True,
        check=True,
    )
    ctrl_dir = ROOT_DIR / "build" / "deb_test_ctrl"
    try:
        postinst = (ctrl_dir / "postinst").read_text()
        postrm = (ctrl_dir / "postrm").read_text()

        # Both refresh desktop and icon caches safely
        for script in [postinst, postrm]:
            assert "update-desktop-database" in script
            assert "gtk-update-icon-cache" in script
            assert "$HOME" not in script
            assert ".config" not in script
            assert "rm -rf" not in script
    finally:
        shutil.rmtree(ctrl_dir, ignore_errors=True)
