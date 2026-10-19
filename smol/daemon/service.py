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

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from smol.core.config import get_config_path, get_daemon_config
from smol.daemon.listener import (
    ListenerCoordinator,
    X11EventListener,
    detect_session_type,
    ensure_ungrab,
    resolve_summon_mode,
)
from smol.ui.donut_window import DonutWindow


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

        listener: X11EventListener | None = None
        donut: DonutWindow | None = None

        def handle_signal(signum: int, frame: Any) -> None:
            logger.info("Received signal %s; shutting down...", signum)
            self._stop_event.set()
            ensure_ungrab()
            if listener is not None:
                listener.stop()
            app_inst = QApplication.instance()
            if app_inst is not None:
                app_inst.quit()

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        try:
            # Fallback to offscreen platform if no display server is present
            if (
                "DISPLAY" not in os.environ
                and "WAYLAND_DISPLAY" not in os.environ
                and "QT_QPA_PLATFORM" not in os.environ
            ):
                os.environ["QT_QPA_PLATFORM"] = "offscreen"

            app = QApplication.instance()
            if app is None:
                app = QApplication([sys.argv[0]])

            config = get_daemon_config(self.config_path)
            session_type = detect_session_type()
            summon_mode = resolve_summon_mode(config.get("path"), session_type)
            trigger_key = config.get("trigger_key", "Super")

            logger.info(
                "smol daemon started (pid %d, trigger_key=%s, mode=%s, "
                "session=%s, sizes=%s)",
                os.getpid(),
                trigger_key,
                summon_mode.value,
                session_type,
                config.get("sizes"),
            )

            donut = DonutWindow(files=[], config_path=self.config_path)

            # Pre-build native window surface and painter caches hidden
            # so the first user interaction has zero cold-start delay
            donut.show()
            app.processEvents()
            donut.hide()
            app.processEvents()

            def on_summon(x: int | None, y: int | None) -> None:
                donut.reset_state()
                if x is not None and y is not None:
                    donut.center_at(x, y)
                else:
                    donut.center_on_screen()
                donut.capture_desktop_background()
                donut.show()
                logger.info(
                    "Donut overlay summoned at x=%s, y=%s (mode=%s)",
                    x,
                    y,
                    summon_mode.value,
                )

            def on_dismiss(reason: str) -> None:
                donut.hide()
                donut.reset_state()
                logger.info("Donut overlay dismissed (reason=%s)", reason)

            coordinator = ListenerCoordinator(
                mode=summon_mode,
                target_key=trigger_key,
                on_summon=on_summon,
                on_dismiss=on_dismiss,
                on_log=logger.info,
            )

            def handle_donut_dismissed(reason: str) -> None:
                if reason == "esc":
                    coordinator.on_esc_pressed()
                else:
                    coordinator.on_click_outside()

            donut.drop_received.connect(coordinator.on_drop_received)
            donut.dismissed.connect(handle_donut_dismissed)
            donut.shrink_started.connect(
                lambda target: logger.info(
                    "Shrink job started for '%s' (target=%s bytes)",
                    donut.file_name,
                    target,
                )
            )
            donut.shrink_finished.connect(
                lambda results: logger.info(
                    "Shrink job finished: %s", donut.result_message
                )
            )
            donut.shrink_failed.connect(
                lambda err, retry: logger.info(
                    "Shrink job failed: %s (retry_target=%s)", err, retry
                )
            )

            if session_type == "x11":
                listener = X11EventListener(
                    target_key=trigger_key,
                    poll_interval=0.015,
                    idle_poll_interval=0.08,
                )
                listener.key_down.connect(coordinator.on_key_down)
                listener.key_up.connect(coordinator.on_key_up)
                listener.drag_started.connect(coordinator.on_drag_start)
                listener.drag_cancelled.connect(coordinator.on_drag_cancelled)
                listener.error_occurred.connect(
                    lambda err: logger.warning("Listener warning: %s", err)
                )
                listener.start()
            else:
                logger.info(
                    "Non-X11 session (%s); running in Path C mode without listener.",
                    session_type,
                )

            # Heartbeat timer ensuring Python signal handlers execute during Qt loop
            heartbeat = QTimer()
            heartbeat.timeout.connect(lambda: None)
            heartbeat.start(500)

            if not self._stop_event.is_set():
                app.exec()
        finally:
            ensure_ungrab()
            if listener is not None:
                listener.stop()
            if donut is not None:
                donut.close()
            logger.info("smol daemon stopped.")
            for handler in logger.handlers:
                handler.flush()
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

    def logs(self, lines: int = 20) -> int:
        """Print summary of daemon logs."""
        running, pid = self.status()
        status_str = f"Running (PID {pid})" if running else "Stopped"
        print(f"Daemon status: {status_str}")
        print(f"Log file:      {self.log_path}")

        if not self.log_path.exists() or self.log_path.stat().st_size == 0:
            print(f"No daemon logs found at {self.log_path}.")
            return 0

        try:
            content = self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"Error reading log file: {exc}", file=sys.stderr)
            return 1

        all_lines = [line.strip() for line in content.splitlines() if line.strip()]
        total_events = len(all_lines)

        drops = [line for line in all_lines if "Drop received:" in line]
        finished = [line for line in all_lines if "Shrink job finished:" in line]
        failed = [line for line in all_lines if "Shrink job failed:" in line]

        print(f"Total logged events: {total_events}")
        print(f"Drops received:      {len(drops)}")
        print(f"Shrink jobs:         {len(finished)} completed, {len(failed)} failed")
        print("-" * 60)
        show_count = min(lines, total_events)
        print(f"Recent log entries (last {show_count}):")
        for line in all_lines[-lines:]:
            print(f"  {line}")
        return 0
