"""Verification script for Donut open and hover animations, and reduce_motion toggle."""

import os
import sys
from pathlib import Path

# Run on offscreen or active display
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from smol.ui.donut_window import DonutWindow
from smol.ui.prediction import Prediction


def main() -> int:
    _app = QApplication.instance() or QApplication(sys.argv)

    # Standard portrait sample file
    sample = Path("tests/samples/portrait.jpg")
    if not sample.exists():
        print(f"Error: {sample} not found")
        return 1

    print("=== Smol Animation Verification (PLAN.md Section 6) ===")

    # Test 1: Open Animation (Normal Motion)
    print("\n1. Testing Open Animation (120 ms OutCubic scale from centre)...")
    win = DonutWindow(files=[sample], reduce_motion=False)
    win.resize(380, 380)

    # Initial start of open animation
    win.start_open_animation()
    assert win._open_anim is not None, "Open animation not instantiated"
    assert win._open_anim.duration() == 120, "Duration must be 120 ms"
    easing_name = win._open_anim.easingCurve().type().name
    print(
        f"  ✓ Open animation configured: duration={win._open_anim.duration()}ms, "
        f"easing={easing_name}"
    )

    # Check scale at 0 ms, 30 ms, 60 ms, 90 ms, 120 ms
    scale_steps = []
    for t in (0, 30, 60, 90, 120):
        win._open_anim.setCurrentTime(t)
        scale_steps.append((t, round(win.open_scale, 4)))
        # Verify render succeeds
        img = QImage(380, 380, QImage.Format.Format_ARGB32_Premultiplied)
        win.render(img)

    for t, s in scale_steps:
        bar = "█" * int(s * 20)
        print(f"    t={t:3d}ms: scale={s:0.4f} |{bar:<20}|")

    assert scale_steps[0][1] == 0.0, "Scale at t=0 must be 0.0"
    assert scale_steps[-1][1] == 1.0, "Scale at t=120 must be 1.0"
    assert scale_steps[2][1] > 0.5, (
        "OutCubic curve must be decelerating (scale at t=60ms > 0.5)"
    )
    print("  ✓ Open animation scale fan-out verified!")
    win.close()

    # Test 2: Hover Animation (6% growth, brightening, prediction fade-in)
    print(
        "\n2. Testing Hover Animation (6% growth, brightening, "
        "prediction label fade)..."
    )
    win_hover = DonutWindow(files=[sample], reduce_motion=False)
    win_hover.resize(380, 380)
    win_hover.show()

    # Hover segment 2 (100 KB)
    seg_idx = 2
    seg = win_hover.segments[seg_idx]
    assert seg.enabled, "Segment 2 must be enabled for portrait.jpg"

    win_hover._set_hovered_segment(seg_idx)
    assert seg._hover_anim is not None, "Segment hover animation must be active"

    hover_steps = []
    for t in (0, 25, 50, 75, 100):
        seg._hover_anim.setCurrentTime(t)
        scale = round(seg.hover_scale, 4)
        progress = round(seg.hover_progress, 4)
        hover_steps.append((t, progress, scale))
        img = QImage(380, 380, QImage.Format.Format_ARGB32_Premultiplied)
        win_hover.render(img)

    for t, p, s in hover_steps:
        growth_pct = round((s - 1.0) * 100, 2)
        print(f"    t={t:3d}ms: progress={p:0.4f}, scale={s:0.4f} (+{growth_pct:.1f}%)")

    assert hover_steps[0][2] == 1.0, "Initial scale must be 1.0"
    assert hover_steps[-1][2] == 1.06, (
        "Hovered segment scale must reach exactly 1.06 (+6%)"
    )
    print("  ✓ Segment 6% hover growth and smooth brightening verified!")

    # Test Prediction fade-in
    print("\n3. Testing Prediction Label Fade-in...")
    pred = Prediction(ok=True, target_bytes=seg.target_bytes, text="~96 KB, 600×800")
    win_hover._on_prediction_ready(str(sample), seg.target_bytes, pred)
    assert win_hover._prediction_anim is not None, "Prediction anim must be created"

    pred_steps = []
    for t in (0, 30, 60, 90, 120):
        win_hover._prediction_anim.setCurrentTime(t)
        op = round(win_hover.prediction_opacity, 4)
        pred_steps.append((t, op))
        img = QImage(380, 380, QImage.Format.Format_ARGB32_Premultiplied)
        win_hover.render(img)

    for t, op in pred_steps:
        bar = "█" * int(op * 20)
        print(f"    t={t:3d}ms: opacity={op:0.4f} |{bar:<20}|")

    assert pred_steps[0][1] == 0.0, "Initial prediction opacity must be 0.0"
    assert pred_steps[-1][1] == 1.0, "Final prediction opacity must be 1.0"
    print("  ✓ Prediction label smooth fade-in verified!")
    win_hover.close()

    # Test 4: reduce_motion = True (No scaling, simple fades/instant only)
    print("\n4. Testing reduce_motion Mode (No scaling, simple fades only)...")
    win_rm = DonutWindow(files=[sample], reduce_motion=True)
    win_rm.resize(380, 380)

    # Open with reduce_motion
    win_rm.start_open_animation()
    assert win_rm.open_scale == 1.0, (
        "With reduce_motion, open_scale must immediately be 1.0"
    )
    assert win_rm._open_anim is None or not win_rm._open_anim.state(), (
        "No open scale animation allowed with reduce_motion"
    )
    print(
        f"  ✓ Open scale with reduce_motion: open_scale={win_rm.open_scale} "
        "(no scaling)"
    )

    # Hover with reduce_motion
    win_rm._set_hovered_segment(seg_idx)
    seg_rm = win_rm.segments[seg_idx]
    assert seg_rm.hover_scale == 1.0, (
        f"With reduce_motion, hover_scale must remain 1.0, got {seg_rm.hover_scale}"
    )
    assert seg_rm.hover_progress == 1.0, (
        "With reduce_motion, progress is set immediately for simple fade"
    )
    print(
        f"  ✓ Hover scale with reduce_motion: hover_scale={seg_rm.hover_scale} "
        "(+0.0%, no scaling)"
    )

    # Prediction with reduce_motion
    win_rm._on_prediction_ready(str(sample), seg_rm.target_bytes, pred)
    assert win_rm.prediction_opacity == 1.0, (
        "Prediction opacity set instantly without scaling"
    )
    print(
        f"  ✓ Prediction opacity with reduce_motion: "
        f"opacity={win_rm.prediction_opacity}"
    )
    win_rm.close()

    print("\n=== All Verification Checks Passed Successfully ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
