"""Unit tests for ShrinkWorker background execution and signals."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

# Ensure Qt can run in headless test environments
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from smol.core.result import Result
from smol.ui.worker import ShrinkWorker


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def wait_for_signal(worker: ShrinkWorker, timeout_ms: int = 5000) -> bool:
    """Helper to process events until worker finishes or times out."""
    import time

    start = time.time()
    while worker.isRunning():
        QCoreApplication.processEvents()
        time.sleep(0.01)
        if (time.time() - start) * 1000 > timeout_ms:
            return False
    # Process any final pending events
    for _ in range(5):
        QCoreApplication.processEvents()
    return True


def test_shrink_worker_success(qapp, samples_dir: Path, tmp_path: Path):
    portrait = tmp_path / "portrait.jpg"
    shutil.copy(samples_dir / "portrait.jpg", portrait)
    target_bytes = 100_000

    progress_events: list[tuple[int, int, str]] = []
    results_received: list[list[tuple[Path, Result]]] = []

    worker = ShrinkWorker(files=[portrait], target_bytes=target_bytes)
    worker.progress.connect(
        lambda cur, tot, msg: progress_events.append((cur, tot, msg))
    )
    worker.results_ready.connect(lambda res: results_received.append(res))

    worker.start()
    finished = wait_for_signal(worker)
    assert finished is True

    assert len(progress_events) >= 1
    assert progress_events[0][0] == 1
    assert progress_events[0][1] == 1

    assert len(results_received) == 1
    batch_results = results_received[0]
    assert len(batch_results) == 1
    src, res = batch_results[0]
    assert src == portrait
    assert res.ok is True
    assert res.final_bytes <= target_bytes
    assert res.output_path is not None
    assert res.output_path.exists()
    assert res.output_path.stat().st_size <= target_bytes


def test_shrink_worker_batch(qapp, samples_dir: Path, tmp_path: Path):
    portrait = tmp_path / "portrait.jpg"
    shutil.copy(samples_dir / "portrait.jpg", portrait)
    landscape = tmp_path / "landscape.jpg"
    shutil.copy(samples_dir / "landscape.jpg", landscape)
    target_bytes = 150_000

    progress_events: list[tuple[int, int, str]] = []
    results_received: list[list[tuple[Path, Result]]] = []

    worker = ShrinkWorker(files=[portrait, landscape], target_bytes=target_bytes)
    worker.progress.connect(
        lambda cur, tot, msg: progress_events.append((cur, tot, msg))
    )
    worker.results_ready.connect(lambda res: results_received.append(res))

    worker.start()
    finished = wait_for_signal(worker)
    assert finished is True

    assert len(progress_events) >= 2
    assert len(results_received) == 1
    assert len(results_received[0]) == 2
    for _src, res in results_received[0]:
        assert res.ok is True
        assert res.final_bytes <= target_bytes


def test_shrink_worker_honest_failure(qapp, samples_dir: Path, tmp_path: Path):
    noise = tmp_path / "noise_cannot_shrink.jpg"
    shutil.copy(samples_dir / "noise_cannot_shrink.jpg", noise)
    # Target 5 KB is impossible for incompressible noise at 200 px floor
    target_bytes = 5_000

    results_received: list[list[tuple[Path, Result]]] = []
    worker = ShrinkWorker(files=[noise], target_bytes=target_bytes)
    worker.results_ready.connect(lambda res: results_received.append(res))

    worker.start()
    finished = wait_for_signal(worker)
    assert finished is True

    assert len(results_received) == 1
    src, res = results_received[0][0]
    assert src == noise
    assert res.ok is False
    assert res.error is not None
    assert "Smallest I can make this is" in res.error
