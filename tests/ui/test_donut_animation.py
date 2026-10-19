"""Tests for Donut UI open and hover animations and reduce_motion toggle."""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEasingCurve
from PySide6.QtWidgets import QApplication

from smol.ui.donut_window import DonutWindow, SegmentItem
from smol.ui.prediction import Prediction


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    from PIL import Image

    img_path = tmp_path / "test_anim.jpg"
    data = bytes((i * 7 % 256) for i in range(500 * 500 * 3))
    img = Image.frombytes("RGB", (500, 500), data)
    img.save(img_path, format="JPEG", quality=95)
    return img_path


def test_open_animation_properties_and_easing(qapp, sample_image: Path) -> None:
    """Open animation uses 120 ms OutCubic easing to scale from centre."""
    window = DonutWindow(files=[sample_image], reduce_motion=False)
    try:
        # Initial state
        assert hasattr(window, "open_scale")
        window.open_scale = 0.5
        assert window.open_scale == 0.5

        # Trigger open animation
        window.start_open_animation()
        assert window._open_anim is not None
        assert window._open_anim.duration() == 120
        assert window._open_anim.easingCurve().type() == QEasingCurve.Type.OutCubic
        assert window._open_anim.startValue() == 0.0
        assert window._open_anim.endValue() == 1.0

        # Fast forward
        window._open_anim.setCurrentTime(120)
        assert window.open_scale == 1.0
    finally:
        window.close()


def test_open_animation_reduce_motion_no_scaling(qapp, sample_image: Path) -> None:
    """With reduce_motion=True, open_scale stays 1.0 with no scaling animation."""
    window = DonutWindow(files=[sample_image], reduce_motion=True)
    try:
        window.start_open_animation()
        assert window.open_scale == 1.0
        # No active scale animation
        assert window._open_anim is None or not window._open_anim.state()
    finally:
        window.close()


def test_segment_item_hover_scale_growth(qapp, sample_image: Path) -> None:
    """SegmentItem grows 6% (hover_scale 1.06) when hover_progress is 1.0."""
    item = SegmentItem(index=0, label="100 KB", target_bytes=100_000, enabled=True)
    assert item.hover_progress == 0.0
    assert item.hover_scale == 1.0

    # Advance hover progress to 1.0
    item.hover_progress = 1.0
    assert round(item.hover_scale, 4) == 1.06

    # Mid-way hover progress
    item.hover_progress = 0.5
    assert round(item.hover_scale, 4) == 1.03

    # With reduce_motion on, hover_scale must remain 1.0
    item.reduce_motion = True
    item.hover_progress = 1.0
    assert item.hover_scale == 1.0


def test_hover_animation_triggers_on_mouse_move(qapp, sample_image: Path) -> None:
    """Hovering a segment initiates smooth hover progress animation."""
    window = DonutWindow(files=[sample_image], reduce_motion=False)
    try:
        window.show()

        # Move to segment 0
        window._set_hovered_segment(0)
        assert window._hovered_idx == 0
        seg0 = window.segments[0]
        assert seg0._hover_anim is not None

        # Advance hover animation
        seg0._hover_anim.setCurrentTime(seg0._hover_anim.duration())
        assert seg0.hover_progress == 1.0
        assert round(seg0.hover_scale, 4) == 1.06

        # Hover another segment: segment 0 animates down, segment 1 animates up
        window._set_hovered_segment(1)
        seg1 = window.segments[1]
        seg0._hover_anim.setCurrentTime(seg0._hover_anim.duration())
        seg1._hover_anim.setCurrentTime(seg1._hover_anim.duration())
        assert seg0.hover_progress == 0.0
        assert seg0.hover_scale == 1.0
        assert seg1.hover_progress == 1.0
        assert round(seg1.hover_scale, 4) == 1.06
    finally:
        window.close()


def test_hover_reduce_motion_no_scaling(qapp, sample_image: Path) -> None:
    """With reduce_motion=True, segments do not scale on hover."""
    window = DonutWindow(files=[sample_image], reduce_motion=True)
    try:
        window._set_hovered_segment(0)
        seg0 = window.segments[0]
        # No scaling
        assert seg0.hover_scale == 1.0
        # Progress is set directly for simple fade / instant state
        assert seg0.hover_progress == 1.0
    finally:
        window.close()


def test_prediction_opacity_fade_in_and_fade_out(qapp, sample_image: Path) -> None:
    """Prediction label fades in with animation and fades out on clear."""
    window = DonutWindow(files=[sample_image], reduce_motion=False)
    try:
        assert window.prediction_opacity == 0.0

        # Deliver prediction
        item = window.segments[0]
        pred = Prediction(
            ok=True, target_bytes=item.target_bytes, text="~95 KB, 600×800"
        )
        window._hovered_idx = 0
        window._on_prediction_ready(str(sample_image), item.target_bytes, pred)

        assert window._prediction_anim is not None
        window._prediction_anim.setCurrentTime(window._prediction_anim.duration())
        assert window.prediction_opacity == 1.0
        assert window._current_prediction == pred

        # Clear prediction
        window._on_prediction_cleared()
        assert window._prediction_anim is not None
        window._prediction_anim.setCurrentTime(window._prediction_anim.duration())
        assert window.prediction_opacity == 0.0
        assert window._current_prediction is None
    finally:
        window.close()


def test_prediction_opacity_reduce_motion(qapp, sample_image: Path) -> None:
    """With reduce_motion=True, prediction opacity updates instantly."""
    window = DonutWindow(files=[sample_image], reduce_motion=True)
    try:
        item = window.segments[0]
        pred = Prediction(
            ok=True, target_bytes=item.target_bytes, text="~95 KB, 600×800"
        )
        window._hovered_idx = 0
        window._on_prediction_ready(str(sample_image), item.target_bytes, pred)

        assert window.prediction_opacity == 1.0
        assert window._current_prediction == pred

        window._on_prediction_cleared()
        assert window.prediction_opacity == 0.0
        assert window._current_prediction is None
    finally:
        window.close()


def test_paint_event_during_animations(qapp, sample_image: Path) -> None:
    """paintEvent runs cleanly at all intermediate animation stages without errors."""
    from PySide6.QtGui import QImage

    window = DonutWindow(files=[sample_image], reduce_motion=False)
    try:
        window.resize(380, 380)

        # 1. Paint at open_scale = 0.0
        window.open_scale = 0.0
        img = QImage(380, 380, QImage.Format.Format_ARGB32_Premultiplied)
        window.render(img)

        # 2. Paint at midway open_scale = 0.5
        window.open_scale = 0.5
        window.render(img)

        # 3. Paint at full open_scale = 1.0 with hovered segment
        window.open_scale = 1.0
        window._set_hovered_segment(0)
        seg0 = window.segments[0]
        seg0.hover_progress = 1.0
        window.render(img)

        # 4. Paint with midway prediction cross-fade
        item = window.segments[0]
        pred = Prediction(
            ok=True, target_bytes=item.target_bytes, text="~95 KB, 600×800"
        )
        window._current_prediction = pred
        window.prediction_opacity = 0.5
        window.render(img)
    finally:
        window.close()


def test_segment_at_expanded_outer_rim(qapp, sample_image: Path) -> None:
    """_segment_at returns hovered segment on 6% expanded outer rim."""
    import math

    window = DonutWindow(files=[sample_image], reduce_motion=False)
    try:
        window._set_hovered_segment(0)
        seg0 = window.segments[0]
        seg0.hover_progress = 1.0
        assert seg0.hover_scale == 1.06

        # Normal outer radius is 175. Expanded outer radius is 175 * 1.06 = 185.5.
        # Pick a point at r = 180 on segment 0 (top-centered, mid_angle around 22.5 deg)
        seg_geom = window.geometry_calc.segments[0]
        mid_rad = math.radians(seg_geom.mid_angle)
        r = 180.0
        dx = r * math.sin(mid_rad)
        dy = -r * math.cos(mid_rad)

        # Normal segment_at would return None because r > 175
        assert window.geometry_calc.segment_at(dx, dy) is None
        # But _segment_at recognizes the expanded 6% rim for the hovered segment!
        assert window._segment_at(dx, dy) == 0
    finally:
        window.close()


def test_disabled_segment_does_not_grow(qapp, sample_image: Path) -> None:
    """Disabled segment does not animate hover_progress to 1.0 or scale up."""
    window = DonutWindow(files=[sample_image], reduce_motion=False)
    try:
        # Find a disabled segment (e.g. 2 MB)
        disabled_idx = None
        for idx, seg in enumerate(window.segments):
            if not seg.enabled:
                disabled_idx = idx
                break

        if disabled_idx is not None:
            window._set_hovered_segment(disabled_idx)
            seg = window.segments[disabled_idx]
            assert seg.hover_progress == 0.0
            assert seg.hover_scale == 1.0
    finally:
        window.close()
