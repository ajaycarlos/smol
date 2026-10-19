"""Tests for completion sequence and failure states in DonutWindow.

Asserts:
- Success: ring snaps shut -> soft checkmark burst (~600 ms) -> toast slides in
- Failure: amber ring + honest message + "Use smallest possible" button
- Clicking "Use smallest possible" retries compression at the smallest possible target.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEasingCurve, Qt
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import QApplication

from smol.ui.donut_window import DonutWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def wait_for_worker(window: DonutWindow, timeout_ms: int = 5000) -> None:
    """Helper to synchronously wait for DonutWindow worker to complete."""
    if window._shrink_worker is not None and window._shrink_worker.isRunning():
        assert window._shrink_worker.wait(timeout_ms)
        QApplication.instance().processEvents()


def test_completion_sequence_ring_snap_and_checkmark_burst(
    qapp, samples_dir: Path, tmp_path: Path
) -> None:
    """Ring snaps shut, soft checkmark bursts for 600 ms, then toast appears."""
    test_img = tmp_path / "portrait.jpg"
    shutil.copy(samples_dir / "portrait.jpg", test_img)

    win = DonutWindow(files=[test_img], reduce_motion=False)
    win.show()
    try:
        win.start_shrink(100_000)
        wait_for_worker(win)

        # 1. State is success
        assert win.state == "success"

        # 2. Ring has snapped shut (100%)
        assert win._ring_progress == 1.0

        # 3. Soft checkmark burst animation is initialized with 600 ms duration
        assert win._anim_checkmark_burst is not None
        assert win._anim_checkmark_burst.duration() == 600
        assert (
            win._anim_checkmark_burst.easingCurve().type()
            == QEasingCurve.Type.OutCubic
        )

        # 4. Step animation through burst
        win.checkmark_burst = 0.5
        assert win.checkmark_burst == 0.5

        # Render during burst to verify painting code
        pix = QPixmap(win.size())
        pix.fill(Qt.GlobalColor.transparent)
        win.render(pix)

        # 5. Trigger end of 600 ms burst -> summons toast
        win._anim_checkmark_burst.setCurrentTime(600)
        qapp.processEvents()

        # Toast window is created and displayed
        assert win._toast is not None
        assert win._toast.isVisible() is True
        assert "portrait.jpg" in win._toast.label_message.text()
    finally:
        win.reset_state()
        win.close()


def test_completion_reduce_motion_instant(
    qapp, samples_dir: Path, tmp_path: Path
) -> None:
    """With reduce_motion=True, checkmark burst resolves instantly and toast appears."""
    test_img = tmp_path / "portrait.jpg"
    shutil.copy(samples_dir / "portrait.jpg", test_img)

    win = DonutWindow(files=[test_img], reduce_motion=True)
    win.show()
    try:
        win.start_shrink(100_000)
        wait_for_worker(win)

        assert win.state == "success"
        assert win._ring_progress == 1.0
        assert win.checkmark_burst == 1.0
        assert win._toast is not None
        assert win._toast.isVisible() is True
    finally:
        win.reset_state()
        win.close()


def test_failure_amber_ring_and_use_smallest_possible_button(
    qapp, samples_dir: Path, tmp_path: Path
) -> None:
    """Failure displays amber ring, honest message, and 'Use smallest possible' button.
    """
    noise = tmp_path / "noise_cannot_shrink.jpg"
    shutil.copy(samples_dir / "noise_cannot_shrink.jpg", noise)

    win = DonutWindow([noise])
    win.show()
    try:
        # Request impossible target (5 KB)
        win.start_shrink(5_000)
        wait_for_worker(win)

        assert win.state == "failure"
        assert win.retry_target_bytes is not None
        assert win.retry_target_bytes > 5_000
        assert "Smallest" in win.failure_error

        # Render window in failure state to test amber ring & button layout
        pix = QPixmap(win.size())
        pix.fill(Qt.GlobalColor.transparent)
        win.render(pix)

        assert win._retry_rect is not None
        assert win._retry_rect.isValid()

        # Click the "Use smallest possible" button
        click_pt = win._retry_rect.center().toPoint()
        press_ev = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            click_pt,
            click_pt,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        win.mousePressEvent(press_ev)

        # Verifies it retried shrinking at smallest possible size!
        assert win.state == "working"
        wait_for_worker(win)
        assert win.state == "success"
    finally:
        win.reset_state()
        win.close()
