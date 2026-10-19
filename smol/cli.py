"""CLI entry point for smol: smol shrink, smol donut, smol daemon, etc."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from smol.core.image import shrink_image
from smol.core.size import format_size, parse_size
from smol.integrations.autostart import AutostartIntegrator
from smol.integrations.manager import get_integrator
from smol.integrations.notifier import (
    JobNotifier,
    send_notification,
)


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
        lines.append("✗ XDG_SESSION_TYPE  (set $XDG_SESSION_TYPE, e.g. wayland or x11)")

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
            "✗ notify-send  (install libnotify-bin: sudo apt install libnotify-bin)"
        )

    print("\n".join(lines))
    return 0


def shrink(argv: list[str]) -> int:
    """Handle `smol shrink FILE... --max 100KB` subcommand."""
    parser = argparse.ArgumentParser(
        prog="smol shrink",
        description="Shrink files to at most a chosen size",
    )
    parser.add_argument(
        "files",
        nargs="+",
        metavar="FILE",
        help="Files to shrink",
    )
    parser.add_argument(
        "--max",
        dest="max_size",
        required=True,
        help="Target maximum size (e.g. 100KB, 1.5MB)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable JSON output",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Predict output size and dimensions without writing files",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default=None,
        help="Output directory (default: next to original file)",
    )
    parser.add_argument(
        "--allow-convert",
        action="store_true",
        help="Allow format conversion (e.g. PNG to JPEG)",
    )
    parser.add_argument(
        "--keep-metadata",
        action="store_true",
        help="Keep metadata (EXIF/GPS) instead of stripping",
    )
    parser.add_argument(
        "--min-side",
        type=int,
        default=200,
        help="Minimum dimension for the short side in pixels (default: 200)",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Send desktop notification upon completion",
    )

    if "--help" in argv or "-h" in argv:
        parser.print_help()
        return 0

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    try:
        target_bytes = parse_size(args.max_size)
    except (ValueError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.min_side <= 0:
        print("Error: --min-side must be a positive integer", file=sys.stderr)
        return 2

    options = {
        "strip_metadata": not args.keep_metadata,
        "allow_convert": args.allow_convert,
        "min_dim": args.min_side,
        "dry_run": args.dry_run,
        "out_dir": args.out_dir,
    }

    results = []
    with JobNotifier(notify=args.notify) as notifier:
        for f in args.files:
            src_path = Path(f)
            res = shrink_image(src_path, target_bytes, options=options)
            results.append((src_path, res))
        notifier.notify_results(results)

    if args.json:
        json_data = [
            {
                "src": str(src_path),
                "ok": res.ok,
                "output_path": str(res.output_path) if res.output_path else None,
                "original_bytes": res.original_bytes,
                "final_bytes": res.final_bytes,
                "width": res.width,
                "height": res.height,
                "scale": res.scale,
                "quality": res.quality,
                "steps": res.steps,
                "warning": res.warning,
                "error": res.error,
            }
            for src_path, res in results
        ]
        print(json.dumps(json_data, indent=2))
    else:
        for src_path, res in results:
            if res.ok:
                orig_str = format_size(res.original_bytes, spaced=True)
                final_str = format_size(res.final_bytes, spaced=True)
                if (
                    res.output_path is None
                    and res.warning
                    and "already" in res.warning.lower()
                ):
                    detail_str = "(already ≤ target)"
                else:
                    dim_str = (
                        f"{res.width}\u00d7{res.height}"
                        if res.width and res.height
                        else ""
                    )
                    if res.quality is not None:
                        q_str = f" q{res.quality}" if dim_str else f"q{res.quality}"
                    else:
                        q_str = ""
                    inner = f"{dim_str}{q_str}".strip()
                    detail_str = f"({inner})" if inner else ""
                if detail_str:
                    print(f"{src_path.name}  {orig_str} → {final_str}  {detail_str}")
                else:
                    print(f"{src_path.name}  {orig_str} → {final_str}")
            else:
                print(f"{src_path.name}  ✗ {res.error}")

    return 0 if all(res.ok for _, res in results) else 1


def _send_notification(summary: str, body: str, urgency: str = "normal") -> None:
    """Send a desktop notification using notify-send if available."""
    send_notification(summary, body, urgency=urgency)


def _notify_results(results: list[tuple[Path, Any]]) -> None:
    """Send desktop notification summarizing shrink results."""
    JobNotifier(notify=True).notify_results(results)


def integrate_autostart(argv: list[str]) -> int:
    """Handle `smol integrate autostart install|uninstall|status` subcommand."""
    parser = argparse.ArgumentParser(
        prog="smol integrate autostart",
        description="Manage XDG autostart desktop entry for smol daemon",
    )
    parser.add_argument(
        "action",
        choices=["install", "uninstall", "status"],
        help="Action to perform: install, uninstall, or status",
    )

    if "--help" in argv or "-h" in argv or not argv:
        parser.print_help()
        return 0

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    integrator = AutostartIntegrator()
    if args.action == "install":
        res = integrator.install()
        if res.ok:
            print(f"✓ {res.message}")
            return 0
        else:
            print(f"✗ {res.message}", file=sys.stderr)
            return 1

    if args.action == "uninstall":
        res = integrator.uninstall()
        if res.ok:
            print(f"✓ {res.message}")
            return 0
        else:
            print(f"✗ {res.message}", file=sys.stderr)
            return 1

    if args.action == "status":
        stat = integrator.status()
        status_text = "Installed (enabled)" if stat.installed else "Not installed"
        print(f"Autostart: {status_text}")
        print(f"File:      {stat.desktop_file}")
        print(f"Details:   {stat.details}")
        return 0

    return 0


def integrate(argv: list[str]) -> int:
    """Handle `smol integrate [autostart] install|uninstall|status` subcommand."""
    if argv and argv[0] == "autostart":
        return integrate_autostart(argv[1:])

    parser = argparse.ArgumentParser(
        prog="smol integrate",
        description=(
            "Manage file manager right-click context menu integration "
            "or desktop autostart"
        ),
        epilog=(
            "Use 'smol integrate autostart [install|uninstall|status]' "
            "to manage desktop autostart."
        ),
    )
    parser.add_argument(
        "action",
        choices=["install", "uninstall", "status", "autostart"],
        help="Action to perform: install, uninstall, status (or 'autostart')",
    )
    parser.add_argument(
        "--file-manager",
        dest="file_manager",
        choices=["nemo", "nautilus", "dolphin", "thunar"],
        default=None,
        help="Target file manager (default: auto-detected)",
    )

    if "--help" in argv or "-h" in argv or not argv:
        parser.print_help()
        return 0

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    if args.action == "autostart":
        return integrate_autostart([])

    try:
        integrator = get_integrator(args.file_manager)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.action == "install":
        res = integrator.install()
        if res.ok:
            print(f"✓ {res.message}")
            return 0
        else:
            print(f"✗ {res.message}", file=sys.stderr)
            return 1

    if args.action == "uninstall":
        res = integrator.uninstall()
        if res.ok:
            print(f"✓ {res.message}")
            return 0
        else:
            print(f"✗ {res.message}", file=sys.stderr)
            return 1

    if args.action == "status":
        stat = integrator.status()
        status_text = (
            "Installed"
            if stat.installed
            else ("Partially installed" if stat.partial else "Not installed")
        )
        print(f"File manager: {stat.file_manager}")
        print(f"Status:       {status_text}")
        print(f"Details:      {stat.details}")
        if stat.installed_sizes:
            print(f"Sizes:        {', '.join(stat.installed_sizes)}")
        return 0

    return 0



def donut(argv: list[str]) -> int:
    """Handle `smol donut --files FILE...` subcommand."""
    parser = argparse.ArgumentParser(
        prog="smol donut",
        description="Open the donut size menu at the cursor",
    )
    parser.add_argument(
        "--files",
        nargs="+",
        required=True,
        metavar="FILE",
        help="One or more files to shrink",
    )

    if "--help" in argv or "-h" in argv:
        parser.print_help()
        return 0

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    paths = [Path(f) for f in args.files]
    for p in paths:
        if not p.exists():
            print(f"Error: File not found: {p}", file=sys.stderr)
            return 1

    from PySide6.QtWidgets import QApplication

    from smol.ui.donut_window import DonutWindow

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv[:1])

    def on_select(label: str) -> None:
        print(label, flush=True)

    window = DonutWindow(files=paths, on_select=on_select)
    window.run_overlay()
    return 0


def daemon(argv: list[str]) -> int:
    """Handle `smol daemon start|stop|status|run|logs` subcommand."""
    parser = argparse.ArgumentParser(
        prog="smol daemon",
        description="Manage the background smol daemon service",
    )
    parser.add_argument(
        "action",
        choices=["start", "stop", "status", "run", "logs"],
        help="Daemon action: start, stop, status, run, or logs",
    )
    parser.add_argument(
        "--state-dir",
        type=str,
        default=None,
        help="State directory for PID and log files",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to smol config.toml",
    )
    parser.add_argument(
        "--lines",
        "-n",
        type=int,
        default=20,
        help="Number of log entries to display (default: 20)",
    )

    if "--help" in argv or "-h" in argv or not argv:
        parser.print_help()
        return 0

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    from smol.daemon.service import DaemonService

    service = DaemonService(state_dir=args.state_dir, config_path=args.config)

    if args.action == "start":
        return service.start()
    if args.action == "stop":
        return service.stop()
    if args.action == "status":
        running, pid = service.status()
        if running:
            print(f"smol daemon is running (PID {pid}).")
            return 0
        else:
            print("smol daemon is not running.")
            return 1
    if args.action == "run":
        return service.run()
    if args.action == "logs":
        return service.logs(lines=args.lines)

    return 2


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="smol",
        description="Shrink any file to at most a chosen size",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="smol 0.4.0",
    )

    # Default: show help if no subcommand given
    if argv is None:
        argv = sys.argv[1:]
    if not argv or argv[0] in ("--help", "-h"):
        parser.print_help()
        return 0

    if argv[0] == "--version":
        print("smol 0.4.0")
        return 0

    # Handle subcommands
    if argv[0] == "doctor":
        return doctor()
    if argv[0] == "shrink":
        return shrink(argv[1:])
    if argv[0] == "integrate":
        return integrate(argv[1:])
    if argv[0] == "donut":
        return donut(argv[1:])
    if argv[0] == "daemon":
        return daemon(argv[1:])

    # Handle unknown commands gracefully
    if argv and argv[0] not in ("shrink", "donut", "daemon", "integrate", "doctor"):
        print(f"Unknown command: {argv[0]}", file=sys.stderr)
        parser.print_help()
        return 2

    print("No command specified. Use `smol --help` to see available commands.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
