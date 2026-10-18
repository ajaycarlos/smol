"""Prediction service and worker for Donut segment hover.

Computes shrunken file predictions using `shrink_image(..., dry_run=True)`
in a dedicated background QThread (never on the UI thread).
Provides a 150 ms debounce, cancellation of stale in-flight calculations,
and per-(file, target_bytes) caching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, QThread, QTimer, Signal

from smol.core.image import shrink_image
from smol.core.result import Result
from smol.core.size import format_size

# Pre-initialize Pillow plugins to avoid dynamic import lock in background threads
Image.init()


@dataclass(frozen=True)
class Prediction:
    """Estimated shrink result for display."""

    ok: bool
    text: str
    target_bytes: int
    final_bytes: int = 0
    width: int | None = None
    height: int | None = None
    quality: int | None = None
    scale: float | None = None
    error: str | None = None


def format_prediction(res: Result) -> str:
    """Format an engine Result into a clean prediction string for the donut center."""
    if res.ok:
        size_str = format_size(res.final_bytes, spaced=True)
        if res.width and res.height:
            return f"~{size_str}, {res.width}×{res.height}"
        return f"~{size_str}"

    if res.error:
        # Extract concise summary from honest failure message if present
        # e.g. "Smallest I can make this is ~120 KB at 200 px; try a larger target."
        m = re.search(r"Smallest[^~]*~([0-9.]+\s*[A-Za-z]+)", res.error)
        if m:
            return f"Smallest ~{m.group(1)}"
        return res.error

    return "Cannot shrink"


class PredictionWorker(QThread):
    """Background QThread executing `shrink_image(..., dry_run=True)`."""

    finished_result = Signal(int, str, int, Prediction)

    def __init__(
        self,
        request_id: int,
        file_path: Path | str,
        target_bytes: int,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.request_id = request_id
        self.file_path = Path(file_path).resolve()
        self.target_bytes = target_bytes

    def run(self) -> None:
        """Run engine dry_run compression in worker thread."""
        self.worker_thread = QThread.currentThread()
        try:
            res = shrink_image(
                self.file_path, self.target_bytes, options={"dry_run": True}
            )
            text = format_prediction(res)
            prediction = Prediction(
                ok=res.ok,
                text=text,
                target_bytes=self.target_bytes,
                final_bytes=res.final_bytes,
                width=res.width,
                height=res.height,
                quality=res.quality,
                scale=res.scale,
                error=res.error,
            )
        except Exception as exc:  # noqa: BLE001
            prediction = Prediction(
                ok=False,
                text="Failed",
                target_bytes=self.target_bytes,
                error=str(exc),
            )

        self.finished_result.emit(
            self.request_id,
            str(self.file_path),
            self.target_bytes,
            prediction,
        )


class PredictionService(QObject):
    """Coordinates debounce timer, background workers, and result caching."""

    prediction_ready = Signal(str, int, Prediction)
    prediction_cleared = Signal()

    def __init__(self, debounce_ms: int = 150, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.debounce_ms = debounce_ms
        self.cache: dict[tuple[Path, int], Prediction] = {}

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)

        self._active_request_id = 0
        self._pending_request: tuple[int, Path, int] | None = None
        self._active_workers: list[PredictionWorker] = []

    def request(self, file_path: Path | str, target_bytes: int | None) -> None:
        """Request a prediction for file_path at target_bytes with debounce."""
        if target_bytes is None:
            self.cancel()
            return

        resolved = Path(file_path).resolve()
        cache_key = (resolved, target_bytes)

        # 1. If result is already cached, return immediately without debounce or thread
        if cache_key in self.cache:
            self.cancel()
            pred = self.cache[cache_key]
            self.prediction_ready.emit(str(resolved), target_bytes, pred)
            return

        # 2. Reset timer and mark previous in-flight requests as stale
        self._active_request_id += 1
        req_id = self._active_request_id
        self._pending_request = (req_id, resolved, target_bytes)
        self._timer.stop()
        self._timer.start(self.debounce_ms)

    def cancel(self) -> None:
        """Cancel pending debounce and invalidate any in-flight workers."""
        self._timer.stop()
        self._pending_request = None
        self._active_request_id += 1
        self.prediction_cleared.emit()

    def wait_for_workers(self, timeout_ms: int = 2000) -> None:
        """Wait for any running background worker threads to finish."""
        for worker in list(self._active_workers):
            if worker.isRunning():
                worker.wait(timeout_ms)

    def _on_timeout(self) -> None:
        """Debounce timer expired: spawn worker thread if request is still current."""
        if self._pending_request is None:
            return

        req_id, resolved, target_bytes = self._pending_request
        if req_id != self._active_request_id:
            return

        cache_key = (resolved, target_bytes)
        if cache_key in self.cache:
            self.prediction_ready.emit(
                str(resolved), target_bytes, self.cache[cache_key]
            )
            return

        worker = PredictionWorker(req_id, resolved, target_bytes)
        worker.finished_result.connect(self._on_worker_finished)
        self._active_workers.append(worker)
        worker.start()

    def _on_worker_finished(
        self,
        req_id: int,
        path_str: str,
        target_bytes: int,
        prediction: Prediction,
    ) -> None:
        """Handle finished worker: save to cache, emit if still current request."""
        # Always save to cache so subsequent hovers benefit from completed calculation
        path = Path(path_str)
        self.cache[(path, target_bytes)] = prediction

        # Worker cleanup
        sender = self.sender()
        if isinstance(sender, PredictionWorker) and sender in self._active_workers:
            self._active_workers.remove(sender)

        # Drop stale results if pointer moved on
        if req_id == self._active_request_id:
            self.prediction_ready.emit(path_str, target_bytes, prediction)
