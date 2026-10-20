import os
import tempfile

import pytest

# Ensure Qt can run in headless test environments if needed
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from spikes.d_dragenter_data import (
    DragEnterDataWindow,
    DragInspectionRecord,
    DragSessionTracker,
    build_mime_data_for_case,
    format_case_report,
    run_all_cases,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_window_initialization(qapp):
    window = DragEnterDataWindow()
    assert window.acceptDrops() is True
    flags = window.windowFlags()
    assert bool(flags & Qt.WindowType.WindowStaysOnTopHint) is True
    assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating) is True


def test_drag_enter_event_logging(qapp):
    window = DragEnterDataWindow()
    mime = QMimeData()
    test_url = QUrl.fromLocalFile("/path/to/test.jpg")
    mime.setUrls([test_url])

    event = QDragEnterEvent(
        QPointF(50.0, 50.0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dragEnterEvent(event)

    assert event.isAccepted() is True
    records = window.session_tracker.current_records
    assert len(records) >= 1
    rec = records[0]
    assert rec.event_type == "ENTER"
    assert rec.has_urls is True
    assert "/path/to/test.jpg" in rec.urls[0]
    assert rec.read_time_ms >= 0.0
    assert "text/uri-list" in rec.formats


def test_drag_move_event_logging(qapp):
    window = DragEnterDataWindow()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("/path/to/doc.pdf")])

    event = QDragMoveEvent(
        QPointF(60.0, 60.0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dragMoveEvent(event)

    assert event.isAccepted() is True
    records = window.session_tracker.current_records
    assert len(records) >= 1
    rec = records[-1]
    assert rec.event_type == "MOVE"
    assert rec.has_urls is True
    assert "/path/to/doc.pdf" in rec.urls[0]


def test_drop_event_logging(qapp):
    window = DragEnterDataWindow()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("/path/to/pic.png")])

    event = QDropEvent(
        QPointF(50.0, 50.0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(event)

    assert event.isAccepted() is True
    records = window.session_tracker.current_records
    assert len(records) >= 1
    rec = records[-1]
    assert rec.event_type == "DROP"
    assert rec.has_urls is True
    assert "/path/to/pic.png" in rec.urls[0]


def test_case_report_formatting():
    tracker = DragSessionTracker()
    tracker.add_record(
        DragInspectionRecord(
            event_type="ENTER",
            has_urls=True,
            formats=["text/uri-list"],
            urls=["file:///tmp/sample.jpg"],
            read_time_ms=0.120,
        )
    )
    tracker.add_record(
        DragInspectionRecord(
            event_type="MOVE",
            has_urls=True,
            formats=["text/uri-list"],
            urls=["file:///tmp/sample.jpg"],
            read_time_ms=0.080,
        )
    )
    tracker.add_record(
        DragInspectionRecord(
            event_type="DROP",
            has_urls=True,
            formats=["text/uri-list"],
            urls=["file:///tmp/sample.jpg"],
            read_time_ms=0.150,
        )
    )

    report = format_case_report("Case 1: One file from Nemo", tracker)
    assert "Case 1: One file from Nemo" in report
    assert "URLs available at ENTER? YES (0.120 ms)" in report
    assert "URLs available at MOVE? YES (0.080 ms)" in report
    assert "URLs available only at DROP? NO" in report


def test_build_mime_data_for_cases():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Case 1
        mime1, _desc1 = build_mime_data_for_case(1, tmpdir)
        assert mime1.hasUrls() is True
        assert len(mime1.urls()) == 1

        # Case 2
        mime2, _desc2 = build_mime_data_for_case(2, tmpdir)
        assert mime2.hasUrls() is True
        assert len(mime2.urls()) > 1

        # Case 3
        mime3, _desc3 = build_mime_data_for_case(3, tmpdir)
        assert mime3.hasUrls() is True
        assert os.path.isdir(mime3.urls()[0].toLocalFile())

        # Case 4 (archive file)
        _mime4, desc4 = build_mime_data_for_case(4, tmpdir)
        assert "archive" in desc4.lower()

        # Case 5 (network/phone or gvfs mock)
        _mime5, desc5 = build_mime_data_for_case(5, tmpdir)
        assert "network" in desc5.lower() or "mounted" in desc5.lower()

        # Case 6 (browser image)
        _mime6, desc6 = build_mime_data_for_case(6, tmpdir)
        assert "browser" in desc6.lower()


def test_run_all_cases_simulation(qapp):
    results = run_all_cases(interactive=False)
    assert len(results) == 6
    for case_title, tracker in results.values():
        report = format_case_report(case_title, tracker)
        assert "URLs available at ENTER?" in report
        assert "URLs available at MOVE?" in report
        assert "URLs available only at DROP?" in report
        assert "ms" in report
