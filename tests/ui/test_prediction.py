import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QThread
from PySide6.QtWidgets import QApplication

from smol.core.result import Result
from smol.ui.prediction import (
    PredictionService,
    PredictionWorker,
    format_prediction,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def wait_events(ms: int) -> None:
    """Wait for ms milliseconds while running the Qt event loop."""
    app = QApplication.instance()
    end_time = time.time() + (ms / 1000.0)
    while time.time() < end_time:
        time.sleep(0.01)
        if app:
            app.processEvents()


def test_format_prediction():
    res_ok = Result(
        ok=True,
        original_bytes=200_000,
        final_bytes=96_000,
        width=600,
        height=800,
    )
    text = format_prediction(res_ok)
    assert text == "~96 KB, 600×800"

    res_fail = Result(
        ok=False,
        original_bytes=200_000,
        error="Smallest I can make this is ~120 KB at 200 px; try a larger target.",
    )
    text_fail = format_prediction(res_fail)
    assert "120 KB" in text_fail


def test_prediction_worker_dry_run_thread(qapp, samples_dir):
    portrait = samples_dir / "portrait.jpg"
    target_bytes = 100_000

    main_thread = QThread.currentThread()
    worker_threads = []

    worker = PredictionWorker(
        request_id=1,
        file_path=portrait,
        target_bytes=target_bytes,
    )

    results = []

    def on_finished(req_id, path_str, tgt, pred):
        worker_threads.append(QThread.currentThread())
        results.append((req_id, path_str, tgt, pred))

    worker.finished_result.connect(on_finished)
    worker.start()

    # Wait for worker thread to finish
    assert worker.wait(5000)
    QCoreApplication.processEvents()

    assert len(results) == 1
    req_id, path_str, tgt, pred = results[0]
    assert req_id == 1
    assert Path(path_str) == portrait.resolve()
    assert tgt == target_bytes
    assert pred.ok is True
    assert pred.final_bytes <= target_bytes
    assert pred.width is not None and pred.height is not None
    assert "~" in pred.text
    assert "×" in pred.text
    assert worker.worker_thread != main_thread

    # Verify no file was written to disk
    assert not (portrait.parent / f"{portrait.stem}_100KB.jpg").exists()
    assert not (portrait.parent / f"{portrait.stem}_100000.jpg").exists()


def test_prediction_service_debounce(qapp, samples_dir):
    portrait = samples_dir / "portrait.jpg"
    service = PredictionService(debounce_ms=150)

    emitted = []
    service.prediction_ready.connect(lambda p, t, r: emitted.append((p, t, r)))

    # Request prediction
    service.request(portrait, 100_000)

    # Immediately: nothing should have emitted
    QCoreApplication.processEvents()
    assert len(emitted) == 0

    # Wait 80 ms (< 150 ms debounce): still nothing
    wait_events(80)
    assert len(emitted) == 0

    # Wait remaining time (> 150 ms debounce + worker execution)
    timeout_at = time.time() + 3.0
    while len(emitted) == 0 and time.time() < timeout_at:
        wait_events(30)

    service.wait_for_workers()

    assert len(emitted) == 1
    _p, t, r = emitted[0]
    assert t == 100_000
    assert r.ok is True
    assert r.final_bytes <= 100_000


def test_prediction_service_debounce_resets_on_new_request(qapp, samples_dir):
    portrait = samples_dir / "portrait.jpg"
    service = PredictionService(debounce_ms=150)

    emitted = []
    service.prediction_ready.connect(lambda p, t, r: emitted.append((p, t, r)))

    # 1. Request 20 KB
    service.request(portrait, 20_000)
    wait_events(80)

    # 2. Before 150 ms expires, request 50 KB (cancels 20 KB timer)
    service.request(portrait, 50_000)

    # Wait for 50 KB to complete
    timeout_at = time.time() + 3.0
    while len(emitted) == 0 and time.time() < timeout_at:
        wait_events(30)

    service.wait_for_workers()

    # Only 50 KB should be emitted, never 20 KB
    assert len(emitted) == 1
    assert emitted[0][1] == 50_000


def test_prediction_service_cancel_discards_inflight(qapp, samples_dir):
    portrait = samples_dir / "portrait.jpg"
    service = PredictionService(debounce_ms=50)

    emitted = []
    service.prediction_ready.connect(lambda p, t, r: emitted.append((p, t, r)))

    # Start request and wait for debounce timer to fire so worker starts
    service.request(portrait, 100_000)
    wait_events(70)

    # Now cancel while worker is in flight
    service.cancel()

    # Wait long enough for background thread to finish
    wait_events(300)
    service.wait_for_workers()

    # Because it was cancelled, prediction_ready must NOT be emitted
    assert len(emitted) == 0


def test_prediction_service_cache_hit_instant(qapp, samples_dir):
    portrait = samples_dir / "portrait.jpg"
    service = PredictionService(debounce_ms=150)

    emitted = []
    service.prediction_ready.connect(lambda p, t, r: emitted.append((p, t, r)))

    # 1. Warm cache
    service.request(portrait, 100_000)
    timeout_at = time.time() + 3.0
    while len(emitted) == 0 and time.time() < timeout_at:
        wait_events(30)

    service.wait_for_workers()

    assert len(emitted) == 1
    assert (portrait.resolve(), 100_000) in service.cache

    # 2. Second request: should hit cache immediately without waiting 150 ms debounce!
    emitted.clear()
    t0 = time.perf_counter()
    service.request(portrait, 100_000)
    t1 = time.perf_counter()

    assert len(emitted) == 1
    # Instant response from cache (< 50 ms, no debounce wait)
    assert (t1 - t0) < 0.05
    assert emitted[0][1] == 100_000
    assert emitted[0][2].ok is True


def test_prediction_worker_pdf(qapp, samples_dir):
    """PredictionWorker produces accurate dry-run predictions for PDF files."""
    pdf_file = samples_dir / "sample_scanned.pdf"
    target_bytes = 500_000

    worker = PredictionWorker(1, pdf_file, target_bytes)
    result_holder = []
    worker.finished_result.connect(
        lambda req_id, path, target, pred: result_holder.append(pred)
    )

    worker.start()
    timeout_at = time.time() + 10.0
    while len(result_holder) == 0 and time.time() < timeout_at:
        wait_events(50)

    assert len(result_holder) == 1
    pred = result_holder[0]
    assert pred.ok is True
    assert pred.final_bytes <= target_bytes
    assert pred.text.startswith("~")

