"""CLI entry point for smol: smol shrink, smol donut, smol daemon, etc."""

import argparse
import os
import shutil
import subprocess
import sys


def _which(cmd: str) -> bool:
    """Return True if *cmd* is on PATH (mimics `shutil.which` behaviour)."""
    return shutil.which(cmd) is not None


def _find_file_manager() -> tuple[str | None, str | None]:
    """Check if nautilus, dolphin, nemo, or thunar is running or installed.

    Returns (manager_name, status) where status is 'running' or 'installed',
    or (None, None) if none is found.
    """
    fms = ("nautilus", "dolphin", "nemo", "thunar")
    # Check if running first
    for fm in fms:
        try:
            res = subprocess.run(
                ["pgrep", "-x", fm],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0:
                return fm, "running"
        except (subprocess.SubprocessError, OSError):
            continue

    # Check if installed on PATH
    for fm in fms:
        if shutil.which(fm):
            return fm, "installed"

    return None, None


def doctor() -> int:
    """Print a system-health checklist with ✓/✗ and install hints."""
    lines: list[str] = []

    # 1. Python version (need 3.12+)
    major, minor, micro = sys.version_info[:3]
    py_ver = f"{major}.{minor}.{micro}"
    if (major, minor) >= (3, 12):
        lines.append(f"✓ Python ({py_ver})")
    else:
        lines.append(f"✗ Python ({py_ver}, need 3.12+)  (install Python 3.12+)")

    # 2. Command-line tools
    tools = [
        (
            "uv",
            "uv",
            (
                "install uv: curl -LsSf https://astral.sh/uv/install.sh | sh "
                "or pip install uv"
            ),
        ),
        ("ffmpeg", "ffmpeg", "install ffmpeg: sudo apt install ffmpeg"),
        ("ffprobe", "ffprobe", "install ffprobe: sudo apt install ffmpeg"),
        ("gs (Ghostscript)", "gs", "install ghostscript: sudo apt install ghostscript"),
        ("qpdf", "qpdf", "install qpdf: sudo apt install qpdf"),
        ("git", "git", "install git: sudo apt install git"),
    ]
    for label, binary, hint in tools:
        if shutil.which(binary):
            lines.append(f"✓ {label}")
        else:
            lines.append(f"✗ {label}  ({hint})")

    # 3. Environment variables
    session_type = os.environ.get("XDG_SESSION_TYPE")
    if session_type:
        lines.append(f"✓ XDG_SESSION_TYPE ({session_type})")
    else:
        lines.append(
            "✗ XDG_SESSION_TYPE  (set $XDG_SESSION_TYPE, e.g. wayland or x11)"
        )

    desktop = os.environ.get("XDG_CURRENT_DESKTOP")
    if desktop:
        lines.append(f"✓ XDG_CURRENT_DESKTOP ({desktop})")
    else:
        lines.append(
            "✗ XDG_CURRENT_DESKTOP  (set $XDG_CURRENT_DESKTOP, e.g. GNOME, KDE)"
        )

    # 4. Best-guess file manager
    fm, fm_status = _find_file_manager()
    if fm:
        lines.append(f"✓ file manager: {fm} ({fm_status})")
    else:
        lines.append(
            "✗ default file manager  "
            "(install nautilus / dolphin / nemo / thunar or ensure one is on PATH)"
        )

    # 5. notify-send
    if shutil.which("notify-send"):
        lines.append("✓ notify-send")
    else:
        lines.append(
            "✗ notify-send  "
            "(install libnotify-bin: sudo apt install libnotify-bin)"
        )

    print("\n".join(lines))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="smol",
        description="Shrink any file to at most a chosen size",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="smol 0.1.0",
    )

    # Default: show help if no subcommand given
    if argv is None:
        argv = sys.argv[1:]
    if not argv or argv[0] in ("--help", "-h"):
        parser.print_help()
        return 0

    # Handle known global flags
    if not argv or argv[0] in ("--help", "-h"):
        parser.print_help()
        return 0
    if argv[0] == "--version":
        print("smol 0.1.0")
        return 0

    # Handle subcommands
    if argv[0] == "doctor":
        return doctor()

    # Handle unknown commands gracefully
    if argv and argv[0] not in ("shrink", "donut", "daemon", "integrate", "doctor"):
        print(f"Unknown command: {argv[0]}", file=sys.stderr)
        parser.print_help()
        return 2

    print("No command specified. Use `smol --help` to see available commands.")
    return 0


if __name__ == "__main__":
    sys.exit(main())