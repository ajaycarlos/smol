import os
import tempfile

import pytest

# Ensure Qt can run in headless test environments
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QKeyEvent
from PySide6.QtWidgets import QApplication

from spikes.d_dragenter_data import (
    CASE_DESCRIPTIONS,
    DragDataInspectorWindow,
    DragEventRecord,
    SessionSummary,
    format_log_line,
    format_summary_table,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_window_properties(qapp):
    window = DragDataInspectorWindow()
    assert window.width() == 320
    assert window.height() == 320
    assert window.acceptDrops() is True
    flags = window.windowFlags()
    assert bool(flags & Qt.WindowType.WindowStaysOnTopHint) is True


def test_key_press_case_tagging(qapp):
    window = DragDataInspectorWindow()
    assert window.current_case_tag is None

    # Press key '1'
    event1 = QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_1, Qt.KeyboardModifier.NoModifier, "1"
    )
    window.keyPressEvent(event1)
    assert window.current_case_tag == 1

    # Press key '6'
    event6 = QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_6, Qt.KeyboardModifier.NoModifier, "6"
    )
    window.keyPressEvent(event6)
    assert window.current_case_tag == 6


def test_format_log_line():
    record = DragEventRecord(
        timestamp=12345.678901,
        event_type="ENTER",
        source_is_none=True,
        proposed_action="CopyAction",
        formats=["text/uri-list"],
        has_urls=True,
        urls=[
            {"toString": "file:///path/to/test.jpg", "toLocalFile": "/path/to/test.jpg"}
        ],
        read_time_ms=0.045,
        case_tag=1,
    )
    line = format_log_line(record)
    assert "ENTER" in line
    assert "source_is_none=True" in line
    assert "read_time_ms=0.045" in line
    assert "file:///path/to/test.jpg" in line
    assert "\n" not in line.strip()  # Must be a single line


def test_summary_table_all_not_tested():
    sessions: dict[int, SessionSummary] = {}
    table = format_summary_table(sessions)
    for case_num in range(1, 7):
        assert f"Case {case_num}:" in table
        assert "NOT TESTED" in table
    assert "Case 1: One file from Nemo" in table
    assert "Case 6: An image dragged from a web browser" in table


def test_summary_table_with_tested_and_untested_cases():
    sessions: dict[int, SessionSummary] = {
        1: SessionSummary(
            case_num=1,
            enter_has_urls=True,
            enter_read_ms=0.082,
            move_has_urls=True,
            move_read_ms=0.021,
            drop_has_urls=True,
            drop_read_ms=0.035,
            formats=["text/uri-list", "x-special/nemo-clipboard"],
            urls=["/home/user/photo.jpg"],
        )
    }
    table = format_summary_table(sessions)

    # Case 1 should have real data
    assert "Case 1: One file from Nemo" in table
    assert "URLs at ENTER?     YES (0.082 ms)" in table
    assert "URLs at MOVE?      YES (0.021 ms)" in table
    assert "URLs only at DROP? NO" in table

    # Cases 2 to 6 must be NOT TESTED
    for c in range(2, 7):
        assert f"Case {c}: {CASE_DESCRIPTIONS[c]} -> NOT TESTED" in table


def test_interactive_window_logging(qapp):
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "d_log.txt")
        window = DragDataInspectorWindow(log_path=log_path)
        window.current_case_tag = 1

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile("/home/user/sample.png")])

        enter_event = QDragEnterEvent(
            QPointF(50.0, 50.0),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        window.dragEnterEvent(enter_event)

        drop_event = QDropEvent(
            QPointF(50.0, 50.0),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        window.dropEvent(drop_event)

        assert os.path.isfile(log_path)
        with open(log_path, encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip()]

        assert len(lines) == 2
        assert "ENTER" in lines[0]
        assert "DROP" in lines[1]
        assert "/home/user/sample.png" in lines[0]
        assert 1 in window.sessions
        assert window.sessions[1].enter_has_urls is True
