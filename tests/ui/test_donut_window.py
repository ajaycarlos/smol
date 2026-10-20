import math
import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure Qt can run in headless test environments
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent, QKeyEvent, QMouseEvent, QPixmap
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


def wait_events(ms: int) -> None:
    import time

    app = QApplication.instance()
    end_time = time.time() + (ms / 1000.0)
    while time.time() < end_time:
        time.sleep(0.01)
        if app:
            app.processEvents()


def test_donut_window_hover_prediction(qapp, samples_dir):
    portrait = samples_dir / "portrait.jpg"
    window = DonutWindow([portrait])
    window.show()

    # Segment 2 is "100 KB" (index 2)
    center = QPointF(window.width() / 2.0, window.height() / 2.0)
    ax, ay = window.geometry_calc.label_anchors[2]
    hover_pos = center + QPointF(ax, ay)

    # Hover segment 2
    event = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        hover_pos,
        hover_pos,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.mouseMoveEvent(event)
    assert window._hovered_idx == 2

    # Initially before debounce: no prediction yet
    assert getattr(window, "_current_prediction", None) is None

    # Wait for 150 ms debounce + worker execution
    wait_events(300)

    # Prediction should be populated
    pred = getattr(window, "_current_prediction", None)
    assert pred is not None
    assert pred.ok is True
    assert "~" in pred.text
    assert "×" in pred.text

    # Paint event should render prediction text without error
    pixmap = QPixmap(window.size())
    pixmap.fill(Qt.GlobalColor.transparent)
    window.render(pixmap)
    assert not pixmap.isNull()

    # Leave window: prediction should clear
    window.leaveEvent(None)
    assert getattr(window, "_current_prediction", None) is None

    window.close()


def test_donut_window_hover_dimmed_segment_no_prediction(qapp, sample_file_30kb):
    window = DonutWindow([sample_file_30kb])
    window.show()

    # Segment 2 is "100 KB" which is dimmed for 30 KB file
    center = QPointF(window.width() / 2.0, window.height() / 2.0)
    ax, ay = window.geometry_calc.label_anchors[2]
    hover_pos = center + QPointF(ax, ay)

    event = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        hover_pos,
        hover_pos,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.mouseMoveEvent(event)
    assert window._hovered_idx == 2

    # Wait for debounce duration
    wait_events(200)

    # Dimmed segment must NOT trigger a prediction
    assert getattr(window, "_current_prediction", None) is None
    window.close()


def wait_for_worker(window: DonutWindow, timeout_ms: int = 5000) -> bool:
    import time

    start = time.time()
    while (
        getattr(window, "_shrink_worker", None) is not None
        and window._shrink_worker.isRunning()
    ):
        QApplication.processEvents()
        time.sleep(0.01)
        if (time.time() - start) * 1000 > timeout_ms:
            return False
    for _ in range(5):
        QApplication.processEvents()
    return True


def test_donut_click_starts_worker_and_shows_working_state(qapp, samples_dir, tmp_path):
    portrait = tmp_path / "portrait.jpg"
    shutil.copy(samples_dir / "portrait.jpg", portrait)
    window = DonutWindow([portrait])
    window.show()

    # Segment 2 is "100 KB"
    center = QPointF(window.width() / 2.0, window.height() / 2.0)
    ax, ay = window.geometry_calc.label_anchors[2]
    click_pos = center + QPointF(ax, ay)

    # Click segment 2
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        click_pos,
        click_pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.mousePressEvent(event)

    assert window.state == "working"
    assert window._shrink_worker is not None
    assert (
        "Shrinking" in window.center_status_text
        or "Working" in window.center_status_text
    )

    wait_for_worker(window)
    window.close()


def test_donut_shows_plain_result_message_on_success(qapp, samples_dir, tmp_path):
    portrait = tmp_path / "portrait.jpg"
    shutil.copy(samples_dir / "portrait.jpg", portrait)
    window = DonutWindow([portrait])
    window.show()

    # Click segment 2 ("100 KB")
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

    wait_for_worker(window)

    assert window.state == "success"
    assert window.result_message is not None
    assert "KB" in window.result_message or "MB" in window.result_message
    assert window.last_results is not None
    assert len(window.last_results) == 1
    _src, res = window.last_results[0]
    assert res.ok is True
    assert res.output_path is not None
    assert res.output_path.exists()
    window.close()


def test_donut_accepts_file_drop_on_segment(qapp, samples_dir, tmp_path):
    portrait = tmp_path / "portrait.jpg"
    shutil.copy(samples_dir / "portrait.jpg", portrait)
    window = DonutWindow([])
    window.show()

    # Drop onto segment 2 ("100 KB")
    center = QPointF(window.width() / 2.0, window.height() / 2.0)
    ax, ay = window.geometry_calc.label_anchors[2]
    drop_pos = center + QPointF(ax, ay)

    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile(str(portrait))])

    drop_event = QDropEvent(
        QPoint(int(drop_pos.x()), int(drop_pos.y())),
        Qt.DropAction.CopyAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    window.dropEvent(drop_event)

    assert drop_event.isAccepted()
    assert window.file_paths == [portrait]
    assert window.state == "working"
    assert window._shrink_worker is not None

    wait_for_worker(window)
    assert window.state == "success"
    window.close()


def test_donut_honest_failure_and_retry_option(qapp, samples_dir, tmp_path):
    noise = tmp_path / "noise_cannot_shrink.jpg"
    shutil.copy(samples_dir / "noise_cannot_shrink.jpg", noise)
    window = DonutWindow([noise])
    window.show()

    # Trigger 5 KB target which is impossible
    window.start_shrink(5_000)

    wait_for_worker(window)

    assert window.state == "failure"
    assert window.failure_error is not None
    assert "Smallest I can make this is" in window.failure_error
    assert window.retry_target_bytes is not None
    assert window.retry_target_bytes > 5_000

    # Trigger retry at smallest possible target
    window.retry_smallest()
    assert window.state == "working"
    wait_for_worker(window)
    assert window.state == "success"
    window.close()


def test_donut_click_retry_button_triggers_shrink(qapp, samples_dir, tmp_path):
    noise = tmp_path / "noise_cannot_shrink.jpg"
    shutil.copy(samples_dir / "noise_cannot_shrink.jpg", noise)
    window = DonutWindow([noise])
    window.show()

    # Trigger impossible target
    window.start_shrink(5_000)
    wait_for_worker(window)

    assert window.state == "failure"
    assert window.retry_target_bytes is not None

    # Render to populate _retry_rect in paintEvent
    pixmap = QPixmap(window.size())
    pixmap.fill(Qt.GlobalColor.transparent)
    window.render(pixmap)
    assert window._retry_rect is not None

    # Click on the center of the retry button
    retry_click_pos = window._retry_rect.center()
    click_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        retry_click_pos,
        retry_click_pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.mousePressEvent(click_event)

    assert window.state == "working"
    wait_for_worker(window)
    assert window.state == "success"
    window.close()


def test_donut_adapt_compact_size(qapp, sample_file_100kb):
    window = DonutWindow([sample_file_100kb])
    assert window.overlay_size == 380
    assert window.width() == 380

    window.adapt_compact_size(340, 68.0, 156.0)
    assert window.overlay_size == 340
    assert window.width() == 340
    assert window.height() == 340
    assert window.inner_radius == 68.0
    assert window.outer_radius == 156.0
    assert window.geometry_calc.inner_radius == 68.0
    assert window.geometry_calc.outer_radius == 156.0
    window.close()


def test_donut_auto_compact_on_tiny_screen(qapp, sample_file_100kb, monkeypatch):
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtGui import QCursor

    # Mock screen with 800x600 geometry
    mock_screen = MagicMock()
    mock_screen.availableGeometry.return_value = QRect(0, 0, 800, 600)

    monkeypatch.setattr(QApplication, "screenAt", lambda _pos: mock_screen)
    monkeypatch.setattr(QCursor, "pos", staticmethod(lambda: QPoint(400, 300)))

    window = DonutWindow([sample_file_100kb])
    window.center_on_cursor()

    assert window.overlay_size == 340
    assert window.width() == 340
    assert window.height() == 340
    # Window should be clamped safely within 8px margin of 800x600 screen
    assert window.x() >= 8
    assert window.y() >= 8
    assert window.x() + window.width() <= 800 - 8
    assert window.y() + window.height() <= 600 - 8
    window.close()


def test_donut_render_all_visual_states(qapp, samples_dir, tmp_path):
    long_file = tmp_path / "very_long_file_name_for_visual_testing_landscape_2026.jpg"
    shutil.copy(samples_dir / "landscape.jpg", long_file)

    # 1. Idle state with long filename
    win_long = DonutWindow([long_file])
    pix = QPixmap(win_long.size())
    pix.fill(Qt.GlobalColor.transparent)
    win_long.render(pix)
    assert not pix.isNull()
    win_long.close()

    # 2. Hover state with prediction
    from smol.ui.prediction import Prediction

    win_hover = DonutWindow([samples_dir / "portrait.jpg"])
    win_hover._hovered_idx = 2
    win_hover._current_prediction = Prediction(
        target_bytes=100_000,
        ok=True,
        text="~99.5 KB, 470×627",
        final_bytes=99512,
        width=470,
        height=627,
    )
    pix_hover = QPixmap(win_hover.size())
    win_hover.render(pix_hover)
    assert not pix_hover.isNull()
    win_hover.close()

    # 3. Many dimmed state
    win_dim = DonutWindow([samples_dir / "already_small.jpg"])
    pix_dim = QPixmap(win_dim.size())
    win_dim.render(pix_dim)
    assert not pix_dim.isNull()
    win_dim.close()


def test_donut_esc_cancels_active_worker(qapp, samples_dir: Path, tmp_path: Path):
    """Pressing Esc while donut is shrinking cancels the worker and closes window."""
    import shutil

    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    img_path = tmp_path / "donut_esc_test.jpg"
    shutil.copy(samples_dir / "portrait.jpg", img_path)

    win = DonutWindow([img_path])
    win.show()

    # Start shrink with pacing enabled so worker is active
    win.start_shrink(target_bytes=50_000)
    assert win._shrink_worker is not None
    assert win._shrink_worker.isRunning()

    # Send Esc key event
    esc_event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Escape,
        Qt.KeyboardModifier.NoModifier,
    )
    win.keyPressEvent(esc_event)

    # Worker must have been cancelled
    assert win._shrink_worker._is_cancelled is True
    win._shrink_worker.wait(3000)
    assert not win._shrink_worker.isRunning()

    # No partial output file
    outputs = list(tmp_path.glob("donut_esc_test_50KB*.jpg"))
    assert len(outputs) == 0
    win.close()

