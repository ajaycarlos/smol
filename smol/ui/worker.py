"""Worker thread for running smol compression jobs.

Executes core compression (shrink_image) off the UI thread without
blocking the Qt event loop, emitting progress updates and completion signals.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from PIL import Image
from PySide6.QtCore import QObject, QThread, Signal

from smol.core.image import shrink_image
from smol.core.result import Result

# Pre-initialize Pillow plugins to prevent import deadlocks in secondary threads
Image.init()


class ShrinkWorker(QThread):
    """QThread worker executing image compression off the UI thread."""

    # progress(current_1_based, total_files, status_or_filename)
    progress = Signal(int, int, str)
    # result_ready(Path, Result) emitted per file
    result_ready = Signal(object, object)
    # results_ready(list[tuple[Path, Result]]) emitted upon batch completion
    results_ready = Signal(list)

    def __init__(
        self,
        files: Sequence[Path | str],
        target_bytes: int,
        options: dict[str, Any] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.files = [Path(f) for f in files]
        self.target_bytes = target_bytes
        self.options = options or {}
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

            try:
                res = shrink_image(
                    src_path,
                    self.target_bytes,
                    options=self.options,
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
