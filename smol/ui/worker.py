"""Worker thread for running smol compression jobs.

Executes core compression (shrink_image) off the UI thread without
blocking the Qt event loop, emitting progress updates and completion signals.
"""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from PIL import Image
from PySide6.QtCore import QObject, QThread, Signal

from smol.core.result import Result
from smol.core.router import shrink_file

# Pre-initialize Pillow plugins to prevent import deadlocks in secondary threads
Image.init()


class ShrinkWorker(QThread):
    """QThread worker executing image and PDF compression off the UI thread."""

    # progress(current_1_based, total_files, status_or_filename)
    progress = Signal(int, int, str)
    # step_progress(progress_fraction, current_bytes) emitted during compression steps
    step_progress = Signal(float, int)
    # result_ready(Path, Result) emitted per file
    result_ready = Signal(object, object)
    # results_ready(list[tuple[Path, Result]]) emitted upon batch completion
    results_ready = Signal(list)

    def __init__(
        self,
        files: Sequence[Path | str],
        target_bytes: int,
        options: dict[str, Any] | None = None,
        pace_steps: bool = True,
        step_pace_s: float = 0.035,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.files = [Path(f) for f in files]
        self.target_bytes = target_bytes
        self.options = dict(options or {})
        self.pace_steps = (
            bool(self.options["pace_steps"])
            if "pace_steps" in self.options
            else pace_steps
        )
        self.step_pace_s = float(self.options.get("step_pace_s", step_pace_s))
        self._is_cancelled = False
        self._active_proc: subprocess.Popen | None = None
        self._proc_lock = threading.Lock()

    def cancel(self) -> None:
        """Request cooperative cancellation and kill active child subprocess."""
        self._is_cancelled = True
        with self._proc_lock:
            if self._active_proc is not None:
                try:
                    self._active_proc.kill()
                except OSError:
                    pass

    def _set_active_proc(self, proc: subprocess.Popen | None) -> None:
        """Register active child process or kill immediately if already cancelled."""
        with self._proc_lock:
            self._active_proc = proc
            if self._is_cancelled and proc is not None:
                try:
                    proc.kill()
                except OSError:
                    pass

    def run(self) -> None:
        """Process files in background thread."""
        total = len(self.files)
        results: list[tuple[Path, Result]] = []

        for idx, src_path in enumerate(self.files, start=1):
            if self._is_cancelled:
                break

            self.progress.emit(idx, total, src_path.name)

            def on_step(frac: float, cur_bytes: int) -> None:
                if self._is_cancelled:
                    return
                self.step_progress.emit(frac, cur_bytes)
                if self.pace_steps:
                    time.sleep(self.step_pace_s)

            opts = dict(self.options)
            opts["step_callback"] = on_step
            opts["cancel_check"] = lambda: self._is_cancelled
            opts["on_process_started"] = self._set_active_proc

            try:
                res = shrink_file(
                    src_path,
                    self.target_bytes,
                    options=opts,
                )
            except Exception as exc:  # noqa: BLE001
                res = Result(
                    ok=False,
                    original_bytes=src_path.stat().st_size if src_path.exists() else 0,
                    error=f"Unexpected error: {exc}",
                )

            if self._is_cancelled:
                # Clean up any partial output file if cancelled
                if (
                    res.output_path
                    and res.output_path != src_path
                    and res.output_path.exists()
                ):
                    try:
                        res.output_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                break

            results.append((src_path, res))
            self.result_ready.emit(src_path, res)

        if not self._is_cancelled:
            self.results_ready.emit(results)

