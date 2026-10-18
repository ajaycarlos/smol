import math
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure Qt can run in headless test environments
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import QApplication

from smol.ui.donut_window import DonutWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def sample_file_100kb(tmp_path: Path) -> Path:
    f = tmp_path / "test_100k.jpg"
    f.write_bytes(b"x" * 100_000)
    return f


@pytest.fixture
def sample_file_30kb(tmp_path: Path) -> Path:
    f = tmp_path / "test_30k.jpg"
    f.write_bytes(b"x" * 30_000)
    return f


def test_donut_window_flags_and_attributes(qapp, sample_file_100kb):
    window = DonutWindow([sample_file_100kb])

    flags = window.windowFlags()
    assert bool(flags & Qt.WindowType.FramelessWindowHint) is True
    assert bool(flags & Qt.WindowType.WindowStaysOnTopHint) is True
    assert bool(flags & Qt.WindowType.Tool) is True

    assert window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True
    assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating) is True
    assert math.isclose(window.windowOpacity(), 0.96, abs_tol=0.01)


def test_donut_window_cursor_centering(qapp, sample_file_100kb, monkeypatch):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QCursor

    monkeypatch.setattr(QCursor, "pos", staticmethod(lambda: QPoint(500, 400)))
    window = DonutWindow([sample_file_100kb])
    window.center_on_cursor()

    # Center of window should surround (500, 400)
    assert window.x() <= 500 <= window.x() + window.width()
    assert window.y() <= 400 <= window.y() + window.height()


def test_donut_window_multi_file(qapp, sample_file_100kb, sample_file_30kb):
    window = DonutWindow([sample_file_100kb, sample_file_30kb])
    assert "2 files" in window.file_name
    # max file is 100 KB, so 100 KB is enabled, but >100 KB is disabled
    seg_map = {seg.label: seg.enabled for seg in window.segments}
    assert seg_map["100 KB"] is True
    assert seg_map["200 KB"] is False
    assert seg_map["Custom…"] is True


def test_donut_segments_labels_and_bytes(qapp, sample_file_100kb):
    window = DonutWindow([sample_file_100kb])
    labels = [seg.label for seg in window.segments]
    expected_labels = [
        "20 KB",
        "50 KB",
        "100 KB",
        "200 KB",
        "500 KB",
        "1 MB",
        "2 MB",
        "Custom…",
    ]
    assert labels == expected_labels


def test_donut_window_segment_dimming_100kb(qapp, sample_file_100kb):
    # 100,000 bytes: 20 KB, 50 KB, 100 KB are <= file size; >100 KB are dimmed
    window = DonutWindow([sample_file_100kb])

    seg_map = {seg.label: seg.enabled for seg in window.segments}
    assert seg_map["20 KB"] is True
    assert seg_map["50 KB"] is True
    assert seg_map["100 KB"] is True
    assert seg_map["200 KB"] is False
    assert seg_map["500 KB"] is False
    assert seg_map["1 MB"] is False
    assert seg_map["2 MB"] is False
    assert seg_map["Custom…"] is True


def test_donut_window_segment_dimming_30kb(qapp, sample_file_30kb):
    # 30,000 bytes: only 20 KB is <= file size; >=50 KB are dimmed
    window = DonutWindow([sample_file_30kb])

    seg_map = {seg.label: seg.enabled for seg in window.segments}
    assert seg_map["20 KB"] is True
    assert seg_map["50 KB"] is False
    assert seg_map["100 KB"] is False
    assert seg_map["200 KB"] is False
    assert seg_map["Custom…"] is True


def test_donut_window_center_content(qapp, samples_dir):
    portrait = samples_dir / "portrait.jpg"
    window = DonutWindow([portrait])

    assert window.file_name == "portrait.jpg"
    assert "MB" in window.file_size_text or "KB" in window.file_size_text
    assert window.thumbnail_pixmap is not None
    assert not window.thumbnail_pixmap.isNull()


def test_donut_window_click_active_segment(qapp, sample_file_100kb):
    callback = MagicMock()
    window = DonutWindow([sample_file_100kb], on_select=callback)

    # Segment 0 is "20 KB" at top (0 deg). Label anchor is near (0, -r_mid)
    center = QPointF(window.width() / 2.0, window.height() / 2.0)
    ax, ay = window.geometry_calc.label_anchors[0]
    click_pos = center + QPointF(ax, ay)

    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        click_pos,
        click_pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.mousePressEvent(event)

    callback.assert_called_once_with("20 KB")
    assert window.selected_size == "20 KB"
    assert not window.isVisible()


def test_donut_window_click_dimmed_segment_ignored(qapp, sample_file_30kb):
    callback = MagicMock()
    window = DonutWindow([sample_file_30kb], on_select=callback)
    window.show()

    # Segment 2 is "100 KB" which is dimmed for 30 KB file
    center = QPointF(window.width() / 2.0, window.height() / 2.0)
    ax, ay = window.geometry_calc.label_anchors[2]
    click_pos = center + QPointF(ax, ay)

    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        click_pos,
        click_pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.mousePressEvent(event)

    callback.assert_not_called()
    assert window.selected_size is None
    window.close()


def test_donut_window_click_outside_closes(qapp, sample_file_100kb):
    callback = MagicMock()
    window = DonutWindow([sample_file_100kb], on_select=callback)
    window.show()

    # Click in the extreme corner of the widget (5, 5), far outside outer radius
    click_pos = QPointF(5.0, 5.0)
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        click_pos,
        click_pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.mousePressEvent(event)

    callback.assert_not_called()
    assert not window.isVisible()


def test_donut_window_esc_key_closes(qapp, sample_file_100kb):
    window = DonutWindow([sample_file_100kb])
    window.show()

    event = QKeyEvent(
        QKeyEvent.Type.KeyPress,
        Qt.Key.Key_Escape,
        Qt.KeyboardModifier.NoModifier,
    )
    window.keyPressEvent(event)

    assert not window.isVisible()


def test_donut_window_paint_event_headless(qapp, samples_dir):
    portrait = samples_dir / "portrait.jpg"
    window = DonutWindow([portrait])

    # Render widget into a pixmap using QWidget.render
    pixmap = QPixmap(window.size())
    pixmap.fill(Qt.GlobalColor.transparent)
    window.render(pixmap)

    assert not pixmap.isNull()
    assert pixmap.width() == window.width()
    assert pixmap.height() == window.height()


def test_donut_window_liquid_glass_properties(qapp, samples_dir):
    portrait = samples_dir / "portrait.jpg"
    window = DonutWindow([portrait])

    # Check window opacity
    assert math.isclose(window.windowOpacity(), 0.96, abs_tol=0.01)

    # Check desktop capture method execution
    window.capture_desktop_background()

    # Create dummy blurred background pixmap and test rendering with it
    dummy_pix = QPixmap(window.size())
    dummy_pix.fill(Qt.GlobalColor.darkBlue)
    window._blurred_desktop = dummy_pix

    pixmap = QPixmap(window.size())
    pixmap.fill(Qt.GlobalColor.transparent)
    window.render(pixmap)
    assert not pixmap.isNull()


def test_donut_window_hover_state(qapp, sample_file_100kb):
    window = DonutWindow([sample_file_100kb])

    center = QPointF(window.width() / 2.0, window.height() / 2.0)
    ax, ay = window.geometry_calc.label_anchors[0]
    hover_pos = center + QPointF(ax, ay)

    # Move mouse over segment 0
    move_event = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        hover_pos,
        hover_pos,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.mouseMoveEvent(move_event)
    assert window._hovered_idx == 0

    # Leave window
    window.leaveEvent(None)
    assert window._hovered_idx is None
