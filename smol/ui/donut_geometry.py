"""Donut geometry calculations (pure math, no Qt imports).

Computes segment angular spans, hit-testing, and label anchor positions
for an N-segment circular donut menu with configurable inner/outer radii
and gap angles.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EPSILON = 1e-9


@dataclass(frozen=True)
class SegmentGeometry:
    """Computed geometry for a single donut segment.

    All angles are in degrees measured clockwise from top (12 o'clock = 0 deg,
    3 o'clock = 90 deg, 6 o'clock = 180 deg, 9 o'clock = 270 deg).
    """

    index: int
    start_angle: float
    end_angle: float
    mid_angle: float
    label_anchor: tuple[float, float]


class DonutGeometry:
    """Pure-math donut geometry calculations for N segments with gaps.

    Coordinates:
      - Origin (0, 0) is the centre of the donut.
      - +dx is right, -dx is left.
      - +dy is down, -dy is up (screen / Qt widget coordinate system).
      - Top (12 o'clock) is at (0, -r), angle 0 deg.
      - Right (3 o'clock) is at (r, 0), angle 90 deg.
      - Bottom (6 o'clock) is at (0, r), angle 180 deg.
      - Left (9 o'clock) is at (-r, 0), angle 270 deg.
    """

    def __init__(
        self,
        n_segments: int,
        inner_radius: float,
        outer_radius: float,
        gap_angle: float = 0.0,
    ) -> None:
        if n_segments < 1:
            raise ValueError(f"n_segments must be at least 1, got {n_segments}")
        if inner_radius <= 0.0:
            raise ValueError(f"inner_radius must be positive, got {inner_radius}")
        if outer_radius <= inner_radius:
            raise ValueError(
                f"outer_radius ({outer_radius}) must be greater than "
                f"inner_radius ({inner_radius})"
            )
        if gap_angle < 0.0:
            raise ValueError(f"gap_angle cannot be negative, got {gap_angle}")

        slot_angle = 360.0 / n_segments
        if gap_angle >= slot_angle:
            raise ValueError(
                f"gap_angle ({gap_angle}) must be strictly less than slot "
                f"angle ({slot_angle})"
            )

        self.n_segments = n_segments
        self.inner_radius = float(inner_radius)
        self.outer_radius = float(outer_radius)
        self.gap_angle = float(gap_angle)
        self.slot_angle = float(slot_angle)
        self.span_angle = float(slot_angle - gap_angle)

        self.segments: list[SegmentGeometry] = self._build_segments()

    def _build_segments(self) -> list[SegmentGeometry]:
        segments: list[SegmentGeometry] = []
        r_mid = (self.inner_radius + self.outer_radius) / 2.0

        for i in range(self.n_segments):
            start = i * self.slot_angle
            end = start + self.span_angle
            mid = start + (self.span_angle / 2.0)

            mid_rad = math.radians(mid)
            ax = r_mid * math.sin(mid_rad)
            ay = -r_mid * math.cos(mid_rad)

            # Clean tiny float precision artifacts near 0
            if abs(ax) < EPSILON:
                ax = 0.0
            if abs(ay) < EPSILON:
                ay = 0.0

            segments.append(
                SegmentGeometry(
                    index=i,
                    start_angle=start,
                    end_angle=end,
                    mid_angle=mid,
                    label_anchor=(ax, ay),
                )
            )
        return segments

    @property
    def label_anchors(self) -> list[tuple[float, float]]:
        """Return list of (x, y) anchor points for all segments."""
        return [seg.label_anchor for seg in self.segments]

    def segment_at(self, dx: float, dy: float) -> int | None:
        """Find the segment index containing the point (dx, dy).

        Returns None if (dx, dy) is in the centre hole, outside the donut,
        or falls within a gap between segments.
        """
        r = math.hypot(dx, dy)
        if r < self.inner_radius - EPSILON or r > self.outer_radius + EPSILON:
            return None

        # Compute clockwise angle from top in degrees [0, 360)
        # dx = r * sin(theta), -dy = r * cos(theta)
        # theta = atan2(dx, -dy)
        theta = math.degrees(math.atan2(dx, -dy)) % 360.0

        slot_idx = int(theta // self.slot_angle)
        if slot_idx >= self.n_segments:
            slot_idx = self.n_segments - 1

        delta = theta - (slot_idx * self.slot_angle)
        # If delta is within the segment's span (with epsilon for boundary)
        if delta <= self.span_angle + EPSILON:
            return slot_idx

        # In the gap
        return None


def compute_segment_angles(
    n_segments: int,
    gap_angle: float = 0.0,
) -> list[tuple[float, float]]:
    """Compute (start_angle, end_angle) pairs for n_segments clockwise from top."""
    # Use dummy radii to reuse validation and angle logic
    geom = DonutGeometry(
        n_segments=n_segments,
        inner_radius=1.0,
        outer_radius=2.0,
        gap_angle=gap_angle,
    )
    return [(seg.start_angle, seg.end_angle) for seg in geom.segments]


def compute_label_anchors(
    n_segments: int,
    inner_radius: float,
    outer_radius: float,
    gap_angle: float = 0.0,
) -> list[tuple[float, float]]:
    """Compute (x, y) label anchor coordinates for all segments."""
    geom = DonutGeometry(
        n_segments=n_segments,
        inner_radius=inner_radius,
        outer_radius=outer_radius,
        gap_angle=gap_angle,
    )
    return geom.label_anchors


def segment_at(
    dx: float,
    dy: float,
    n_segments: int,
    inner_radius: float,
    outer_radius: float,
    gap_angle: float = 0.0,
) -> int | None:
    """Find the segment index containing (dx, dy), or None if outside/center/gap."""
    geom = DonutGeometry(
        n_segments=n_segments,
        inner_radius=inner_radius,
        outer_radius=outer_radius,
        gap_angle=gap_angle,
    )
    return geom.segment_at(dx, dy)
