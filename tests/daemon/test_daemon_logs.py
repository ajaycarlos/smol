"""Tests for smol daemon logs summary command."""

from __future__ import annotations

from pathlib import Path

from smol.cli import daemon
from smol.daemon.service import DaemonService


def test_daemon_logs_no_file(tmp_path: Path, capsys) -> None:
    """Verify daemon logs output when log file does not exist."""
    service = DaemonService(state_dir=tmp_path)
    res = service.logs()
    assert res == 0
    captured = capsys.readouterr()
    assert "No daemon logs found" in captured.out


def test_daemon_logs_with_entries(tmp_path: Path, capsys) -> None:
    """Verify daemon logs parses entries and summarizes activity."""
    service = DaemonService(state_dir=tmp_path)
    log_file = tmp_path / "daemon.log"
    sample_log = (
        "2026-10-19 15:00:00,000 [INFO] [pid 1234] smol daemon started.\n"
        "2026-10-19 15:00:01,000 [INFO] [pid 1234] Trigger key 'Super' pressed.\n"
        "2026-10-19 15:00:02,000 [INFO] [pid 1234] Donut overlay summoned "
        "at x=100, y=200 (mode=Path A (cursor overlay on drag))\n"
        "2026-10-19 15:00:03,000 [INFO] [pid 1234] Drop received: 1 files "
        "([PosixPath('/path/photo.jpg')]).\n"
        "2026-10-19 15:00:04,000 [INFO] [pid 1234] Shrink job started for "
        "'photo.jpg' (target=100000 bytes)\n"
        "2026-10-19 15:00:05,000 [INFO] [pid 1234] Shrink job finished: "
        "1.20 MB → 98.50 KB\n"
    )
    log_file.write_text(sample_log, encoding="utf-8")

    res = service.logs()
    assert res == 0
    captured = capsys.readouterr()
    assert "Daemon status:" in captured.out
    assert "Log file:" in captured.out
    assert "Total logged events: 6" in captured.out
    assert "Drops received:      1" in captured.out
    assert "Shrink jobs:         1 completed" in captured.out
    assert "photo.jpg" in captured.out


def test_cli_daemon_logs_command(tmp_path: Path, capsys) -> None:
    """Verify `smol daemon logs` subcommand via CLI entry point."""
    log_file = tmp_path / "daemon.log"
    log_file.write_text(
        "2026-10-19 15:10:00,000 [INFO] [pid 5678] smol daemon started.\n",
        encoding="utf-8",
    )

    exit_code = daemon(["logs", "--state-dir", str(tmp_path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "smol daemon started." in captured.out
