"""Verification script for drop animation, ring progress, and size countdown.

VERIFY requirement:
"shrinking the large portrait sample shows a believable ring and size countdown."
"""

from __future__ import annotations

import math
import os
import shutil
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

from smol.ui.donut_window import DonutWindow


def main() -> None:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    repo_root = Path(__file__).resolve().parent.parent
    sample = repo_root / "tests" / "samples" / "portrait.jpg"
    assert sample.exists(), f"Sample file {sample} not found"

    orig_size = sample.stat().st_size
    print(
        f"Loaded sample: {sample.name} "
        f"({orig_size:,} bytes / {orig_size / 1_000_000:.2f} MB)"
    )

    # Use a temp directory for test output
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_sample = Path(tmp_dir) / "portrait.jpg"
        shutil.copyfile(sample, tmp_sample)

        win = DonutWindow(files=[tmp_sample], reduce_motion=False)
        win.show()
        app.processEvents()

        # Target 100 KB segment (index 2 in standard sizes)
        chosen_idx = 2
        seg_geom = win.geometry_calc.segments[chosen_idx]
        target_bytes = win.segments[chosen_idx].target_bytes
        center = win.rect().center()
        rad = (win.inner_radius + win.outer_radius) / 2.0
        angle_rad = math.radians(seg_geom.mid_angle)
        drop_x = center.x() + rad * math.sin(angle_rad)
        drop_y = center.y() - rad * math.cos(angle_rad)

        print(
            f"\nSimulating drag-and-drop onto segment {chosen_idx} "
            f"(target: {target_bytes / 1000:.0f} KB)..."
        )

        # Track progress frames
        progress_log: list[dict] = []
        t0 = time.perf_counter()

        def on_step(fraction: float, cur_bytes: int) -> None:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            progress_log.append({
                "time_ms": elapsed_ms,
                "progress_pct": fraction * 100.0,
                "countdown_bytes": cur_bytes,
                "other_opacity": win.other_segments_opacity,
                "pulse": win.ring_pulse,
            })
            print(
                f"  [{elapsed_ms:5.1f} ms] Ring: {fraction * 100.0:5.1f}% | "
                f"Countdown: {cur_bytes:>10,d} bytes ({cur_bytes / 1000:6.1f} KB) | "
                f"Other segments opacity: {win.other_segments_opacity:.2f}"
            )

        # Hook into worker when started
        def on_worker_started():
            if win._shrink_worker:
                win._shrink_worker.step_progress.connect(on_step)

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(tmp_sample))])
        drop_ev = QDropEvent(
            QPointF(drop_x, drop_y),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        win.dropEvent(drop_ev)
        on_worker_started()

        # Let the event loop run and process animation/worker signals
        while win.state == "working":
            app.processEvents()
            time.sleep(0.01)

        total_elapsed_ms = (time.perf_counter() - t0) * 1000
        print(
            f"\nShrink completed in {total_elapsed_ms:.1f} ms "
            f"with state: '{win.state}'"
        )
        print(
            f"Final output size: {win._countdown_bytes:,} bytes "
            f"({win._countdown_bytes / 1000:.1f} KB)"
        )
        print(f"Total progress steps logged: {len(progress_log)}")

        assert len(progress_log) >= 4, "Expected at least 4 progress step updates"
        assert (
            progress_log[0]["countdown_bytes"]
            > progress_log[-1]["countdown_bytes"]
        ), "Countdown size did not decrease"
        assert (
            progress_log[-1]["progress_pct"] == 100.0
        ), "Progress ring did not reach 100%"
        assert win.other_segments_opacity == 0.0, "Other segments did not fade out"
        assert win._is_fast_job is False, "Over 300 ms should not be fast job"

        win.close()
        app.processEvents()

    print("\n✓ VERIFY PASSED: Believable ring progress and size countdown confirmed!")


if __name__ == "__main__":
    main()
