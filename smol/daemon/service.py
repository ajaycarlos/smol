"""Daemon service controller for smol.

Manages daemon process lifecycle (start, stop, status, run),
single-instance enforcement via file locks, rotating logs in
~/.local/state/smol/daemon.log, and clean shutdown on SIGTERM / SIGINT.
"""

from __future__ import annotations

import fcntl
import logging
import logging.handlers
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from smol.core.config import get_config_path, get_daemon_config


def get_state_dir(override_dir: Path | str | None = None) -> Path:
    """Return the absolute path to the smol state directory."""
    if override_dir is not None:
        return Path(override_dir)

    env_state = os.environ.get("SMOL_STATE_DIR")
    if env_state:
        return Path(env_state)

    xdg_state = os.environ.get("XDG_STATE_HOME")
    if xdg_state:
        base = Path(xdg_state)
    else:
        base = Path.home() / ".local" / "state"

    return base / "smol"


def get_log_path(state_dir: Path | str | None = None) -> Path:
    """Return the absolute path to the daemon log file."""
    return get_state_dir(state_dir) / "daemon.log"


def get_pid_path(state_dir: Path | str | None = None) -> Path:
    """Return the absolute path to the daemon PID file."""
    return get_state_dir(state_dir) / "daemon.pid"


def get_lock_path(state_dir: Path | str | None = None) -> Path:
    """Return the absolute path to the daemon lock file."""
    return get_state_dir(state_dir) / "daemon.lock"


class DaemonService:
    """Manages the lifecycle of the smol daemon."""

    def __init__(
        self,
        state_dir: Path | str | None = None,
        config_path: Path | str | None = None,
    ) -> None:
        self.state_dir = get_state_dir(state_dir)
        self.config_path = get_config_path(config_path)
        self.log_path = get_log_path(self.state_dir)
        self.pid_path = get_pid_path(self.state_dir)
        self.lock_path = get_lock_path(self.state_dir)

        self._lock_file: Any = None
        self._stop_event = threading.Event()
        self._logger: logging.Logger | None = None

    def setup_logging(self, console: bool = False) -> logging.Logger:
        """Configure rotating log file and optional console logging."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger("smol.daemon")
        logger.setLevel(logging.INFO)

        # Clear existing handlers to prevent duplicates if called repeatedly
        logger.handlers.clear()

        handler = logging.handlers.RotatingFileHandler(
            self.log_path,
            maxBytes=1_048_576,  # 1 MB
            backupCount=3,
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [pid %(process)d] %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        if console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)

        self._logger = logger
        return logger

    def acquire_lock(self) -> bool:
        """Acquire single-instance lock file.

        Returns True if acquired, False otherwise.
        """
        self.state_dir.mkdir(parents=True, exist_ok=True)
        try:
            # Persistent lock handle kept open during daemon execution
            lock_file = open(self.lock_path, "a+", encoding="utf-8")  # noqa: SIM115
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_file = lock_file
            # Write current PID
            self.pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
            return True
        except (BlockingIOError, OSError):
            return False

    def release_lock(self) -> None:
        """Release single-instance lock and remove PID file."""
        try:
            if self.pid_path.exists():
                self.pid_path.unlink(missing_ok=True)
        except OSError:
            pass

        if self._lock_file is not None:
            try:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_file.close()
            except OSError:
                pass
            self._lock_file = None

    def status(self) -> tuple[bool, int | None]:
        """Check whether the daemon is running. Returns (is_running, pid)."""
        if not self.lock_path.exists():
            if self.pid_path.exists():
                try:
                    pid = int(self.pid_path.read_text(encoding="utf-8").strip())
                    os.kill(pid, 0)
                except (OSError, ValueError):
                    self.pid_path.unlink(missing_ok=True)
            return False, None

        # Check if lock can be acquired
        try:
            with open(self.lock_path, "a+", encoding="utf-8") as test_fd:
                try:
                    fcntl.flock(test_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # Acquired successfully -> daemon is not running
                    fcntl.flock(test_fd.fileno(), fcntl.LOCK_UN)
                    if self.pid_path.exists():
                        self.pid_path.unlink(missing_ok=True)
                    return False, None
                except (BlockingIOError, OSError):
                    # Lock held by running daemon
                    pass
        except OSError:
            pass

        # Daemon is running, read PID
        if self.pid_path.exists():
            try:
                pid = int(self.pid_path.read_text(encoding="utf-8").strip())
                return True, pid
            except ValueError:
                return True, None

        return True, None

    def run(self, console_log: bool = False) -> int:
        """Run daemon in foreground until SIGTERM or SIGINT is received."""
        logger = self.setup_logging(console=console_log)

        if not self.acquire_lock():
            logger.error("Failed to acquire lock; smol daemon is already running.")
            print("smol daemon is already running.", file=sys.stderr)
            return 1

        self._stop_event.clear()

        def handle_signal(signum: int, frame: Any) -> None:
            logger.info("Received signal %s; shutting down...", signum)
            self._stop_event.set()

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        config = get_daemon_config(self.config_path)
        logger.info(
            "smol daemon started (pid %d, trigger_key=%s, sizes=%s)",
            os.getpid(),
            config.get("trigger_key"),
            config.get("sizes"),
        )

        try:
            while not self._stop_event.is_set():
                self._stop_event.wait(timeout=0.5)
        finally:
            logger.info("smol daemon stopped.")
            self.release_lock()

        return 0

    def start(self) -> int:
        """Start daemon in background.

        Returns 0 on success, 1 on failure or already running.
        """
        running, pid = self.status()
        if running:
            print(f"smol daemon is already running (PID {pid}).")
            return 1

        cmd = [
            sys.executable,
            "-m",
            "smol.cli",
            "daemon",
            "run",
            "--state-dir",
            str(self.state_dir),
            "--config",
            str(self.config_path),
        ]

        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )

        # Wait briefly for daemon to initialize and acquire lock
        start_time = time.time()
        while time.time() - start_time < 3.0:
            running, pid = self.status()
            if running:
                print(f"smol daemon started (PID {pid}).")
                return 0
            time.sleep(0.05)

        print("Error: smol daemon failed to start within timeout.", file=sys.stderr)
        return 1

    def stop(self) -> int:
        """Stop running daemon. Returns 0 on success, 1 if not running."""
        running, pid = self.status()
        if not running or pid is None:
            print("smol daemon is not running.")
            return 1

        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            self.release_lock()
            print("smol daemon is not running.")
            return 1

        # Poll status until process exits
        start_time = time.time()
        while time.time() - start_time < 3.0:
            running, _ = self.status()
            if not running:
                print("smol daemon stopped.")
                return 0
            time.sleep(0.05)

        # Force kill if still running after timeout
        try:
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.1)
        except OSError:
            pass

        self.release_lock()
        print("smol daemon stopped (force killed).")
        return 0
