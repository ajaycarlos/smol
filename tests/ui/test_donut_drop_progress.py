"""Tests for drop animation, ring progress, size countdown, and fast-path bypass."""

from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEasingCurve, QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

from smol.core.image import shrink_image
from smol.ui.donut_window import DonutWindow
from smol.ui.worker import ShrinkWorker


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_step_callback_in_shrink_image(samples_dir: Path, tmp_path: Path) -> None:
    """Core image shrink_image reports real progress and intermediate sizes."""
    portrait = samples_dir / "portrait.jpg"
    reported_steps: list[tuple[float, int]] = []

    def on_step(frac: float, cur_bytes: int) -> None:
        reported_steps.append((frac, cur_bytes))

    res = shrink_image(
        portrait,
        100_000,
        options={"out_dir": tmp_path, "step_callback": on_step},
    )

    assert res.ok is True
    assert len(reported_steps) >= 3
    # Fractions should be monotonically non-decreasing
    fractions = [s[0] for s in reported_steps]
    assert fractions == sorted(fractions)
    assert fractions[-1] == 1.0
    # Final reported size should equal output size
    assert reported_steps[-1][1] == res.final_bytes
    assert res.final_bytes <= 100_000


def test_shrink_worker_emits_step_progress(
    qapp, samples_dir: Path, tmp_path: Path
) -> None:
    """ShrinkWorker emits step_progress signals off the UI thread."""
    portrait = samples_dir / "portrait.jpg"
    worker = ShrinkWorker(
        [portrait],
        100_000,
        options={"out_dir": tmp_path, "pace_steps": False},
        pace_steps=False,
    )

    emitted_steps: list[tuple[float, int]] = []
    worker.step_progress.connect(lambda f, b: emitted_steps.append((f, b)))

    worker.start()
    assert worker.wait(5000)

    # Process pending events so queued signal is delivered
    qapp.processEvents()

    assert len(emitted_steps) >= 3
    assert emitted_steps[-1][0] == 1.0
    assert emitted_steps[-1][1] <= 100_000


def test_shrink_worker_pdf_video_stub(qapp, tmp_path: Path) -> None:
    """ShrinkWorker emits stub steps for PDF and video files."""
    dummy_pdf = tmp_path / "sample.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 dummy data " * 50_000)

    worker = ShrinkWorker(
        [dummy_pdf],
        50_000,
        options={"pace_steps": False},
        pace_steps=False,
    )

    emitted_steps: list[tuple[float, int]] = []
    worker.step_progress.connect(lambda f, b: emitted_steps.append((f, b)))

    worker.start()
    assert worker.wait(3000)
    qapp.processEvents()

    fractions = [s[0] for s in emitted_steps]
    assert fractions == [0.25, 0.50, 0.75, 1.0]
    # Candidate sizes should count down towards target
    assert emitted_steps[0][1] > emitted_steps[-1][1]


def test_donut_drop_animates_fade_and_pulse(
    qapp, samples_dir: Path, tmp_path: Path
) -> None:
    """On drop, unchosen segments fade out; chosen segment pulses into ring."""
    test_img = tmp_path / "portrait.jpg"
    test_img.write_bytes((samples_dir / "portrait.jpg").read_bytes())
    win = DonutWindow(files=[test_img], reduce_motion=False)
    try:
        # Find segment index 2 (100 KB)
        chosen_idx = 2
        seg_geom = win.geometry_calc.segments[chosen_idx]
        center = win.rect().center()
        rad = (win.inner_radius + win.outer_radius) / 2.0
        angle_rad = math.radians(seg_geom.mid_angle)
        drop_x = center.x() + rad * math.sin(angle_rad)
        drop_y = center.y() - rad * math.cos(angle_rad)

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(test_img))])

        drop_ev = QDropEvent(
            QPointF(drop_x, drop_y),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        win.dropEvent(drop_ev)

        assert win._chosen_segment_idx == chosen_idx
        assert win.state == "working"
        assert win._anim_fade_others is not None
        assert win._anim_fade_others.duration() == 160
        assert win._anim_fade_others.easingCurve().type() == QEasingCurve.Type.OutCubic

        assert win._anim_transition is not None
        assert win._anim_transition.duration() == 200

        assert win._anim_pulse is not None
        assert win._anim_pulse.duration() == 240

        # Step animations
        win._anim_fade_others.setCurrentTime(160)
        assert win.other_segments_opacity == 0.0

        win._anim_transition.setCurrentTime(200)
        assert win.drop_transition == 1.0

        if win._shrink_worker:
            win._shrink_worker.wait(5000)
            qapp.processEvents()
    finally:
        win.reset_state()
        win.close()


def test_fast_job_skips_straight_to_done(
    qapp, samples_dir: Path, tmp_path: Path
) -> None:
    """If a job finishes in under 300 ms, skip straight to done — no fake progress."""
    test_img = tmp_path / "already_small.jpg"
    test_img.write_bytes((samples_dir / "already_small.jpg").read_bytes())
    win = DonutWindow(files=[test_img], reduce_motion=False)
    try:
        win.start_shrink(50_000)
        if win._shrink_worker:
            win._shrink_worker.wait(3000)
            qapp.processEvents()

        assert win._is_fast_job is True
        assert win.state == "success"
        assert win._ring_progress == 1.0
        assert win.other_segments_opacity == 0.0
    finally:
        win.reset_state()
        win.close()


def test_reduce_motion_drop_behavior(qapp, samples_dir: Path) -> None:
    """reduce_motion setting replaces drop transitions with instant states."""
    portrait = samples_dir / "portrait.jpg"
    win = DonutWindow(files=[portrait], reduce_motion=True)
    try:
        win._start_drop_animation()
        assert win.other_segments_opacity == 0.0
        assert win.drop_transition == 1.0
        assert win.ring_pulse == 0.0
    finally:
        win.reset_state()
        win.close()


def test_ring_progress_and_countdown_updates(qapp, samples_dir: Path) -> None:
    """_on_step_progress updates live ring progress and size countdown."""
    portrait = samples_dir / "portrait.jpg"
    win = DonutWindow(files=[portrait], reduce_motion=False)
    try:
        win.state = "working"
        win._orig_size_bytes = 1_200_000
        win._countdown_bytes = 1_200_000
        win._ring_progress = 0.0

        # Step 1
        win._on_step_progress(0.25, 800_000)
        assert win._ring_progress == 0.25
        assert win._countdown_bytes == 800_000

        # Step 2
        win._on_step_progress(0.60, 400_000)
        assert win._ring_progress == 0.60
        assert win._countdown_bytes == 400_000

        # Step 3
        win._on_step_progress(1.0, 99_500)
        assert win._ring_progress == 1.0
        assert win._countdown_bytes == 99_500
    finally:
        win.reset_state()
        win.close()
