"""Tests for smol.ui.donut_geometry (pure math, no Qt)."""

import math

import pytest

from smol.ui.donut_geometry import (
    DonutGeometry,
    SegmentGeometry,
    compute_label_anchors,
    compute_segment_angles,
    segment_at,
)


def test_no_qt_imports():
    """Verify smol.ui.donut_geometry has zero Qt / PySide imports."""
    import smol.ui.donut_geometry as dg

    with open(dg.__file__, encoding="utf-8") as f:
        content = f.read().lower()

    assert "pyside" not in content
    assert "pyqt" not in content
    assert "qpainter" not in content
    assert "qwidget" not in content


def test_invalid_parameters():
    """Verify validation of geometry parameters."""
    # N < 1
    with pytest.raises(ValueError, match="n_segments"):
        DonutGeometry(n_segments=0, inner_radius=50, outer_radius=100)

    # inner_radius <= 0
    with pytest.raises(ValueError, match="inner_radius"):
        DonutGeometry(n_segments=4, inner_radius=0, outer_radius=100)
    with pytest.raises(ValueError, match="inner_radius"):
        DonutGeometry(n_segments=4, inner_radius=-10, outer_radius=100)

    # inner_radius >= outer_radius
    with pytest.raises(ValueError, match="outer_radius"):
        DonutGeometry(n_segments=4, inner_radius=100, outer_radius=100)
    with pytest.raises(ValueError, match="outer_radius"):
        DonutGeometry(n_segments=4, inner_radius=120, outer_radius=100)

    # negative gap
    with pytest.raises(ValueError, match="gap_angle"):
        DonutGeometry(n_segments=4, inner_radius=50, outer_radius=100, gap_angle=-1.0)

    # gap >= 360 / N
    with pytest.raises(ValueError, match="gap_angle"):
        DonutGeometry(n_segments=4, inner_radius=50, outer_radius=100, gap_angle=90.0)
    with pytest.raises(ValueError, match="gap_angle"):
        DonutGeometry(n_segments=4, inner_radius=50, outer_radius=100, gap_angle=95.0)


@pytest.mark.parametrize("n", range(1, 13))
def test_segment_angles_all_n(n: int):
    """Verify segment start and end angles for N from 1 to 12."""
    gap = 2.0 if n > 1 else 0.0
    geom = DonutGeometry(
        n_segments=n, inner_radius=50.0, outer_radius=100.0, gap_angle=gap
    )

    assert len(geom.segments) == n
    slot_angle = 360.0 / n
    expected_span = slot_angle - gap

    for i, seg in enumerate(geom.segments):
        assert isinstance(seg, SegmentGeometry)
        assert seg.index == i
        expected_start = i * slot_angle
        expected_end = expected_start + expected_span
        expected_mid = expected_start + (expected_span / 2.0)

        assert math.isclose(seg.start_angle, expected_start, abs_tol=1e-7)
        assert math.isclose(seg.end_angle, expected_end, abs_tol=1e-7)
        assert math.isclose(seg.mid_angle, expected_mid, abs_tol=1e-7)

    # First segment always starts at top (0.0 degrees)
    assert math.isclose(geom.segments[0].start_angle, 0.0, abs_tol=1e-7)


def test_segment_angles_functional_helper():
    """Verify compute_segment_angles helper function."""
    angles = compute_segment_angles(n_segments=4, gap_angle=4.0)
    assert len(angles) == 4
    # Slot is 90 deg, span is 86 deg
    assert angles[0] == (0.0, 86.0)
    assert angles[1] == (90.0, 176.0)
    assert angles[2] == (180.0, 266.0)
    assert angles[3] == (270.0, 356.0)


def test_segment_at_centre():
    """Verify coordinates in the centre hole return None."""
    geom = DonutGeometry(
        n_segments=6, inner_radius=40.0, outer_radius=100.0, gap_angle=3.0
    )

    # Origin (0, 0)
    assert geom.segment_at(0.0, 0.0) is None

    # Points with r < inner_radius in all directions
    for angle_deg in [0, 45, 90, 135, 180, 225, 270, 315]:
        rad = math.radians(angle_deg)
        r = 20.0  # < 40
        dx = r * math.sin(rad)
        dy = -r * math.cos(rad)
        assert geom.segment_at(dx, dy) is None


def test_segment_at_outside():
    """Verify coordinates outside outer radius return None."""
    geom = DonutGeometry(
        n_segments=6, inner_radius=40.0, outer_radius=100.0, gap_angle=3.0
    )

    # Points with r > outer_radius in all directions
    for angle_deg in [0, 45, 90, 135, 180, 225, 270, 315]:
        rad = math.radians(angle_deg)
        r = 120.0  # > 100
        dx = r * math.sin(rad)
        dy = -r * math.cos(rad)
        assert geom.segment_at(dx, dy) is None


def test_segment_at_boundaries():
    """Verify hit testing exactly on radial and angular boundaries."""
    geom = DonutGeometry(
        n_segments=4, inner_radius=50.0, outer_radius=100.0, gap_angle=10.0
    )
    # Segments:
    # 0: [0, 80], gap: (80, 90)
    # 1: [90, 170], gap: (170, 180)
    # 2: [180, 260], gap: (260, 270)
    # 3: [270, 350], gap: (350, 360)

    # Radial boundaries (at mid-angle of segment 0 = 40 deg)
    mid_rad = math.radians(40.0)

    # Exactly on inner radius r = 50.0
    dx_in = 50.0 * math.sin(mid_rad)
    dy_in = -50.0 * math.cos(mid_rad)
    assert geom.segment_at(dx_in, dy_in) == 0

    # Exactly on outer radius r = 100.0
    dx_out = 100.0 * math.sin(mid_rad)
    dy_out = -100.0 * math.cos(mid_rad)
    assert geom.segment_at(dx_out, dy_out) == 0

    # Angular boundaries (at r = 75.0)
    r = 75.0

    # Exactly on start_angle of segment 0 (0 deg, top)
    assert geom.segment_at(0.0, -r) == 0

    # Exactly on end_angle of segment 0 (80 deg)
    rad_80 = math.radians(80.0)
    assert geom.segment_at(r * math.sin(rad_80), -r * math.cos(rad_80)) == 0

    # Exactly on start_angle of segment 1 (90 deg, right)
    assert geom.segment_at(r, 0.0) == 1

    # Exactly on end_angle of segment 1 (170 deg)
    rad_170 = math.radians(170.0)
    assert geom.segment_at(r * math.sin(rad_170), -r * math.cos(rad_170)) == 1


def test_segment_at_exactly_on_gap():
    """Verify points inside angular gaps return None."""
    geom = DonutGeometry(
        n_segments=4, inner_radius=50.0, outer_radius=100.0, gap_angle=10.0
    )
    r = 75.0

    # Midpoint of gap 0: 85 deg (between 80 and 90)
    rad_85 = math.radians(85.0)
    assert geom.segment_at(r * math.sin(rad_85), -r * math.cos(rad_85)) is None

    # Midpoint of gap 1: 175 deg (between 170 and 180)
    rad_175 = math.radians(175.0)
    assert geom.segment_at(r * math.sin(rad_175), -r * math.cos(rad_175)) is None

    # Midpoint of gap 2: 265 deg (between 260 and 270)
    rad_265 = math.radians(265.0)
    assert geom.segment_at(r * math.sin(rad_265), -r * math.cos(rad_265)) is None

    # Midpoint of gap 3: 355 deg (between 350 and 360)
    rad_355 = math.radians(355.0)
    assert geom.segment_at(r * math.sin(rad_355), -r * math.cos(rad_355)) is None


def test_segment_at_zero_gap():
    """When gap is 0, full ring between r_in and r_out maps to segments."""
    geom = DonutGeometry(
        n_segments=4, inner_radius=50.0, outer_radius=100.0, gap_angle=0.0
    )
    r = 75.0

    # Quadrant test
    # Segment 0: [0, 90]
    p0 = (r * math.sin(math.radians(45)), -r * math.cos(math.radians(45)))
    assert geom.segment_at(*p0) == 0
    # Segment 1: [90, 180]
    p1 = (r * math.sin(math.radians(135)), -r * math.cos(math.radians(135)))
    assert geom.segment_at(*p1) == 1
    # Segment 2: [180, 270]
    p2 = (r * math.sin(math.radians(225)), -r * math.cos(math.radians(225)))
    assert geom.segment_at(*p2) == 2
    # Segment 3: [270, 360]
    p3 = (r * math.sin(math.radians(315)), -r * math.cos(math.radians(315)))
    assert geom.segment_at(*p3) == 3


@pytest.mark.parametrize("n", range(1, 13))
def test_segment_at_all_n_midpoints_and_gaps(n: int):
    """Verify segment hit test for all N from 1 to 12 at midpoints and gaps."""
    gap = 4.0 if n > 1 else 0.0
    geom = DonutGeometry(
        n_segments=n, inner_radius=40.0, outer_radius=120.0, gap_angle=gap
    )
    r_mid = 80.0
    slot = 360.0 / n
    span = slot - gap

    for i in range(n):
        # Test segment midpoint: MUST hit segment i
        mid_angle = i * slot + span / 2.0
        rad_mid = math.radians(mid_angle)
        dx_mid = r_mid * math.sin(rad_mid)
        dy_mid = -r_mid * math.cos(rad_mid)
        hit = geom.segment_at(dx_mid, dy_mid)
        assert hit == i, f"Expected segment {i} for N={n} at angle {mid_angle}"

        # Test gap midpoint (if gap > 0): MUST return None
        if gap > 0:
            gap_angle_mid = i * slot + span + gap / 2.0
            rad_gap = math.radians(gap_angle_mid)
            dx_gap = r_mid * math.sin(rad_gap)
            dy_gap = -r_mid * math.cos(rad_gap)
            hit_gap = geom.segment_at(dx_gap, dy_gap)
            assert hit_gap is None, f"Expected None on gap for N={n}"


@pytest.mark.parametrize("n", range(1, 13))
def test_label_anchor_points(n: int):
    """Verify label anchor points for all N from 1 to 12."""
    r_in = 60.0
    r_out = 140.0
    gap = 3.0 if n > 1 else 0.0
    geom = DonutGeometry(
        n_segments=n, inner_radius=r_in, outer_radius=r_out, gap_angle=gap
    )

    anchors = geom.label_anchors
    assert len(anchors) == n

    expected_r = (r_in + r_out) / 2.0  # 100.0

    for i, (ax, ay) in enumerate(anchors):
        # Distance from origin must equal expected midpoint radius
        dist = math.hypot(ax, ay)
        assert math.isclose(dist, expected_r, abs_tol=1e-5)

        # Check against segment geometry anchor property
        seg_anchor = geom.segments[i].label_anchor
        assert math.isclose(seg_anchor[0], ax, abs_tol=1e-7)
        assert math.isclose(seg_anchor[1], ay, abs_tol=1e-7)

        # Angle of anchor point should match mid_angle
        seg = geom.segments[i]
        expected_ax = expected_r * math.sin(math.radians(seg.mid_angle))
        expected_ay = -expected_r * math.cos(math.radians(seg.mid_angle))
        assert math.isclose(ax, expected_ax, abs_tol=1e-5)
        assert math.isclose(ay, expected_ay, abs_tol=1e-5)


def test_standalone_functions():
    """Verify standalone pure functions work identically."""
    n = 8
    r_in, r_out, gap = 50.0, 100.0, 2.0

    angles = compute_segment_angles(n, gap)
    anchors = compute_label_anchors(n, r_in, r_out, gap)

    geom = DonutGeometry(n, r_in, r_out, gap)

    assert angles == [(s.start_angle, s.end_angle) for s in geom.segments]
    assert anchors == geom.label_anchors

    # Standalone segment_at
    ax, ay = anchors[0]
    assert segment_at(ax, ay, n, r_in, r_out, gap) == 0
    assert segment_at(0.0, 0.0, n, r_in, r_out, gap) is None
