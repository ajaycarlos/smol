"""Worker thread for running smol compression jobs.

Executes core compression (shrink_image) off the UI thread without
blocking the Qt event loop, emitting progress updates and completion signals.
"""

from __future__ import annotations

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

    def cancel(self) -> None:
        """Request cooperative cancellation."""
        self._is_cancelled = True

    def run(self) -> None:
        """Process files in background thread."""
        total = len(self.files)
        results: list[tuple[Path, Result]] = []

        for idx, src_path in enumerate(self.files, start=1):
            if self._is_cancelled:
                break

            self.progress.emit(idx, total, src_path.name)
            ext = src_path.suffix.lower()

            # Stub progress for video formats (M8 engine)
            if ext in (".mp4", ".mov", ".mkv", ".webm", ".avi"):
                orig_bytes = src_path.stat().st_size if src_path.exists() else 0
                stub_steps = [0.25, 0.50, 0.75, 1.0]
                for frac in stub_steps:
                    if self._is_cancelled:
                        break
                    diff = orig_bytes - min(orig_bytes, self.target_bytes)
                    cand_bytes = int(orig_bytes - diff * frac)
                    self.step_progress.emit(frac, max(1, cand_bytes))
                    if self.pace_steps:
                        time.sleep(self.step_pace_s)

                res = Result(
                    ok=False,
                    original_bytes=orig_bytes,
                    error=(
                        "Video compression engine coming in future milestone (M8); "
                        "skipped."
                    ),
                )
                results.append((src_path, res))
                self.result_ready.emit(src_path, res)
                continue

            def on_step(frac: float, cur_bytes: int) -> None:
                if self._is_cancelled:
                    return
                self.step_progress.emit(frac, cur_bytes)
                if self.pace_steps:
                    time.sleep(self.step_pace_s)

            opts = dict(self.options)
            opts["step_callback"] = on_step

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

            results.append((src_path, res))
            self.result_ready.emit(src_path, res)

        if not self._is_cancelled:
            self.results_ready.emit(results)
