"""Unit tests for DonutWindow pre-drop file classification.

Asserts:
- Classification in a worker thread on drag-enter with 300 ms overall timeout.
- Timeout behavior with a stub that sleeps: enters "unknown" / "Checking...".
- States:
  * "all supported": normal active segments.
  * "none supported": center shows "Unsupported file type (.docx)", segments dim.
  * "mixed": center shows "2 of 3 supported, 1 will be skipped".
- Drop processes ONLY supported files in mixed batches.
- Final toast lists skipped files by name.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from smol.core.classify import BatchClassification, Classification
from smol.ui.donut_window import DonutWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _wait_for_classify(donut: DonutWindow, timeout_ms: int = 1500) -> bool:
    """Pump Qt event loop until classification worker finishes and delivers signals."""
    import time

    start = time.time()
    worker = donut._classification_worker
    if worker is not None:
        while worker.isRunning():
            QCoreApplication.processEvents()
            time.sleep(0.01)
            if (time.time() - start) * 1000 > timeout_ms:
                return False
    for _ in range(10):
        QCoreApplication.processEvents()
        time.sleep(0.005)
    return True


def _make_drag_enter(urls: list[Path | str]) -> QDragEnterEvent:
    mime = QMimeData()
    qurls = [
        QUrl.fromLocalFile(str(u))
        if isinstance(u, Path) or not str(u).startswith("http")
        else QUrl(str(u))
        for u in urls
    ]
    mime.setUrls(qurls)
    ev = QDragEnterEvent(
        QPointF(150.0, 150.0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    ev._mime = mime
    return ev


def _make_drag_move(x: int = 150, y: int = 40) -> QDragMoveEvent:
    mime = QMimeData()
    ev = QDragMoveEvent(
        QPointF(float(x), float(y)),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    ev._mime = mime
    return ev


def _make_drop(urls: list[Path | str], x: int = 150, y: int = 40) -> QDropEvent:
    mime = QMimeData()
    qurls = [
        QUrl.fromLocalFile(str(u))
        if isinstance(u, Path) or not str(u).startswith("http")
        else QUrl(str(u))
        for u in urls
    ]
    mime.setUrls(qurls)
    ev = QDropEvent(
        QPointF(x, y),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    ev._mime = mime
    return ev


def test_donut_timeout_stub_sleeps(
    qapp, samples_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When classification exceeds 300 ms, Donut enters 'Checking...' state."""
    donut = DonutWindow(files=[samples_dir / "portrait.jpg"], reduce_motion=True)

    # Monkeypatch classify_files to sleep for 400 ms
    import smol.ui.worker

    def slow_classify(paths):
        time.sleep(0.4)
        return BatchClassification(
            items=[Classification(kind="jpeg", path=str(p)) for p in paths],
            total_count=len(paths),
            classified_count=len(paths),
        )

    monkeypatch.setattr(smol.ui.worker, "classify_files", slow_classify)

    enter_event = _make_drag_enter([samples_dir / "portrait.jpg"])
    donut.dragEnterEvent(enter_event)

    # Immediately on dragEnter, state should be unknown / Checking...
    assert donut.drag_classify_state == "unknown"
    assert donut.center_classify_message == "Checking..."

    # Wait 350 ms for timeout to trigger
    QTest.qWait(350)
    assert donut.drag_classify_state == "unknown"
    assert donut.center_classify_message == "Checking..."

    # Allow worker thread to finish cleanly before destroying widget
    QTest.qWait(150)
    donut.close()


def test_donut_drag_enter_all_supported(qapp, samples_dir: Path) -> None:
    """All supported files keeps all segments enabled and state all_supported."""
    donut = DonutWindow(files=[samples_dir / "portrait.jpg"], reduce_motion=True)

    files = [samples_dir / "portrait.jpg", samples_dir / "sample_scanned.pdf"]
    enter_event = _make_drag_enter(files)
    donut.dragEnterEvent(enter_event)

    # Allow worker thread to finish
    _wait_for_classify(donut)

    assert donut.drag_classify_state == "all_supported"
    assert donut.all_segments_dimmed is False
    donut.close()


def test_donut_drag_enter_none_supported(qapp, tmp_path: Path) -> None:
    """Unsupported files dim all segments, show reason in center, and reject drops."""
    docx_file = tmp_path / "document.docx"
    docx_file.write_bytes(b"PK\x03\x04" + b"\x00" * 30)

    donut = DonutWindow(files=[docx_file], reduce_motion=True)

    enter_event = _make_drag_enter([docx_file])
    donut.dragEnterEvent(enter_event)

    # Wait for classification worker
    _wait_for_classify(donut)

    assert donut.drag_classify_state == "none_supported"
    assert donut.all_segments_dimmed is True
    assert "Unsupported file type (.docx)" in donut.center_classify_message

    # Over segments, move event sets forbidden cursor and ignores
    move_event = _make_drag_move(x=donut.width() // 2, y=40)
    donut.dragMoveEvent(move_event)
    assert donut.cursor().shape() == Qt.CursorShape.ForbiddenCursor
    assert move_event.isAccepted() is False

    # Drop event is rejected
    drop_event = _make_drop([docx_file], x=donut.width() // 2, y=40)
    donut.dropEvent(drop_event)
    assert drop_event.isAccepted() is False
    assert donut.state != "working"

    donut.close()


def test_donut_drag_enter_folder(qapp, tmp_path: Path) -> None:
    """Folder dragged onto donut shows 'folder, not supported' and dims segments."""
    folder = tmp_path / "my_photos"
    folder.mkdir()

    donut = DonutWindow(files=[folder], reduce_motion=True)
    enter_event = _make_drag_enter([folder])
    donut.dragEnterEvent(enter_event)

    _wait_for_classify(donut)

    assert donut.drag_classify_state == "none_supported"
    assert donut.all_segments_dimmed is True
    assert donut.center_classify_message == "folder, not supported"

    donut.close()


def test_donut_drag_enter_mismatched_extension(
    qapp, samples_dir: Path, tmp_path: Path
) -> None:
    """PDF renamed to .jpg is recognized as supported (PDF)."""
    fake_jpg = tmp_path / "disguised.jpg"
    fake_jpg.write_bytes((samples_dir / "sample_scanned.pdf").read_bytes()[:2048])

    donut = DonutWindow(files=[fake_jpg], reduce_motion=True)
    enter_event = _make_drag_enter([fake_jpg])
    donut.dragEnterEvent(enter_event)

    _wait_for_classify(donut)

    assert donut.drag_classify_state == "all_supported"
    assert donut.all_segments_dimmed is False
    donut.close()


def test_donut_drag_enter_mixed_batch(qapp, samples_dir: Path, tmp_path: Path) -> None:
    """Mixed batch shows summary, processes supported, toast lists skipped."""
    f1 = samples_dir / "portrait.jpg"
    f2 = samples_dir / "sample_scanned.pdf"
    f3 = tmp_path / "notes.docx"
    f3.write_bytes(b"PK\x03\x04" + b"\x00" * 30)

    donut = DonutWindow(files=[f1], reduce_motion=True)
    enter_event = _make_drag_enter([f1, f2, f3])
    donut.dragEnterEvent(enter_event)

    _wait_for_classify(donut)

    assert donut.drag_classify_state == "mixed"
    assert donut.all_segments_dimmed is False
    assert donut.center_classify_message == "2 of 3 supported, 1 will be skipped"

    # Drop mixed batch onto first segment (e.g. index 0)
    drop_event = _make_drop([f1, f2, f3], x=donut.width() // 2, y=40)
    donut.dropEvent(drop_event)

    assert drop_event.isAccepted() is True
    # Verify that only supported files are queued/processed
    assert donut.file_paths == [f1, f2]
    assert donut.last_skipped_files == [f3]

    from smol.core.result import Result

    dummy_res = Result(
        ok=True,
        output_path=f1,
        original_bytes=100_000,
        final_bytes=50_000,
    )
    toast = donut._build_completion_toast([(f1, dummy_res)])  # mock completion
    msg = toast.label_message.text()
    assert "notes.docx" in msg
    assert "Skipped" in msg

    donut.close()
