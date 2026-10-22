import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from smol.cli import main
from smol.core.config import get_daemon_config
from smol.daemon.service import DaemonService, get_log_path, get_pid_path


def test_daemon_config_defaults(tmp_path: Path) -> None:
    nonexistent = tmp_path / "nonexistent.toml"
    cfg = get_daemon_config(nonexistent)
    assert cfg["trigger_key"] == "Super"
    assert cfg["sizes"] == [
        20_000,
        50_000,
        100_000,
        200_000,
        500_000,
        1_000_000,
        2_000_000,
    ]
    assert cfg["custom_sizes"] == []

    custom_cfg = tmp_path / "custom.toml"
    custom_cfg.write_text(
        'trigger_key = "Ctrl+Alt"\nsizes = [50000, 100000]\ncustom_sizes = [75000]\n',
        encoding="utf-8",
    )
    cfg2 = get_daemon_config(custom_cfg)
    assert cfg2["trigger_key"] == "Ctrl+Alt"
    assert cfg2["sizes"] == [50_000, 100_000]
    assert cfg2["custom_sizes"] == [75_000]


def test_daemon_logging_and_rotation(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    service = DaemonService(state_dir=state_dir)
    logger = service.setup_logging()

    log_file = get_log_path(state_dir)
    assert log_file.parent.exists()

    logger.info("Test log entry")
    for handler in logger.handlers:
        handler.flush()

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Test log entry" in content

    # Verify RotatingFileHandler is used
    import logging.handlers

    rotating_handlers = [
        h
        for h in logger.handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(rotating_handlers) >= 1
    assert rotating_handlers[0].maxBytes > 0
    assert rotating_handlers[0].backupCount > 0


def test_daemon_single_instance(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    service1 = DaemonService(state_dir=state_dir)
    service2 = DaemonService(state_dir=state_dir)

    assert service1.acquire_lock() is True
    assert service2.acquire_lock() is False

    service1.release_lock()
    assert service2.acquire_lock() is True
    service2.release_lock()


def test_daemon_status(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    service = DaemonService(state_dir=state_dir)

    running, pid = service.status()
    assert running is False
    assert pid is None

    # Stale PID file without held lock
    pid_file = get_pid_path(state_dir)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text("999999\n", encoding="utf-8")

    running, pid = service.status()
    assert running is False
    assert pid is None
    # Stale PID should be cleared
    assert not pid_file.exists()


def test_daemon_start_and_stop(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    config_file = tmp_path / "config.toml"
    service = DaemonService(state_dir=state_dir, config_path=config_file)

    try:
        # 1. Start daemon
        code = service.start()
        assert code == 0

        # Wait briefly for daemon process to initialize and write PID
        for _ in range(50):
            running, pid = service.status()
            if running:
                break
            time.sleep(0.05)

        assert running is True
        assert pid is not None
        assert pid > 0

        # 2. Starting again should report already running (exit code 1)
        code2 = service.start()
        assert code2 == 1

        # 3. Stop daemon
        stop_code = service.stop()
        assert stop_code == 0

        running_after, _ = service.status()
        assert running_after is False

        # 4. Stopping again when not running should return 1
        stop_code2 = service.stop()
        assert stop_code2 == 1
    finally:
        # Cleanup if test failed mid-way
        service.stop()


def test_daemon_clean_shutdown_on_sigterm(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    config_file = tmp_path / "config.toml"

    # Launch daemon run directly via subprocess
    cmd = [
        sys.executable,
        "-m",
        "smol.cli",
        "daemon",
        "run",
        "--state-dir",
        str(state_dir),
        "--config",
        str(config_file),
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        # Wait for daemon to be ready
        service = DaemonService(state_dir=state_dir, config_path=config_file)
        ready = False
        for _ in range(50):
            running, pid = service.status()
            if running and pid == proc.pid:
                ready = True
                break
            time.sleep(0.05)

        assert ready is True

        # Send SIGTERM
        proc.send_signal(signal.SIGTERM)
        ret = proc.wait(timeout=3.0)
        assert ret == 0

        # Check PID file is removed and status is stopped
        running, _ = service.status()
        assert running is False

        # Check daemon.log logged clean shutdown
        log_file = get_log_path(state_dir)
        content = log_file.read_text(encoding="utf-8")
        assert "stopped" in content.lower()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_cli_daemon_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_dir = tmp_path / "cli_state"
    config_file = tmp_path / "cli_config.toml"

    monkeypatch.setenv("SMOL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("SMOL_CONFIG_PATH", str(config_file))

    # Help
    ret = main(["daemon", "--help"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "start" in out
    assert "stop" in out
    assert "status" in out
    assert "run" in out

    # Status when stopped
    ret = main(["daemon", "status"])
    assert ret == 1
    out = capsys.readouterr().out
    assert "not running" in out.lower()

    # Start
    ret = main(["daemon", "start"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "started" in out.lower()

    try:
        # Start again -> already running
        ret = main(["daemon", "start"])
        assert ret == 1
        out = capsys.readouterr().out
        assert "already running" in out.lower()

        # Status -> running
        ret = main(["daemon", "status"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "running" in out.lower()

        # Stop
        ret = main(["daemon", "stop"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "stopped" in out.lower()

        # Stop again -> not running
        ret = main(["daemon", "stop"])
        assert ret == 1
        out = capsys.readouterr().out
        assert "not running" in out.lower()
    finally:
        DaemonService(state_dir=state_dir, config_path=config_file).stop()


def test_daemon_start_command_frozen_and_appimage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Daemon start detects frozen binary and APPIMAGE to avoid '-m smol.cli'."""
    service = DaemonService(state_dir=tmp_path / "state", config_path=tmp_path / "config.toml")
    spawned_cmds = []

    def fake_popen(cmd, **kwargs):
        spawned_cmds.append(cmd)
        return None

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    # Return (False, None) on initial check, then (True, 1234) on startup poll
    status_calls = []
    def fake_status():
        if len(status_calls) % 2 == 0:
            status_calls.append(False)
            return (False, None)
        else:
            status_calls.append(True)
            return (True, 1234)
    monkeypatch.setattr(service, "status", fake_status)

    # Case 1: Standard python
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delenv("APPIMAGE", raising=False)
    service.start()
    assert spawned_cmds[-1][:3] == [sys.executable, "-m", "smol.cli"]

    # Case 2: PyInstaller frozen
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/opt/smol/smol")
    service.start()
    assert spawned_cmds[-1][:2] == ["/opt/smol/smol", "daemon"]
    assert "-m" not in spawned_cmds[-1]

    # Case 3: AppImage
    appimage_path = tmp_path / "test.AppImage"
    appimage_path.touch()
    monkeypatch.setenv("APPIMAGE", str(appimage_path))
    service.start()
    assert spawned_cmds[-1][:2] == [str(appimage_path), "daemon"]
    assert "-m" not in spawned_cmds[-1]

