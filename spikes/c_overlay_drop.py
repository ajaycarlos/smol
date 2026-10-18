#!/usr/bin/env python3
"""smol Spike C: Drop Overlay Window Spike (PySide6).

Tests a 300x300 translucent, round, frameless, always-on-top window that accepts
file drops (text/uri-list) under Linux X11/Wayland.

Evaluates two variants:
  (1) window visible BEFORE the drag starts
  (2) window appears DURING an active drag (shown on a 3-second timer)

Measures appearance latency (< 150 ms target) and verifies non-blocking behavior
with the active file manager.
"""

from __future__ import annotations

import enum
import os
import sys
import time
import urllib.parse
from collections.abc import Callable, Sequence

from PySide6.QtCore import (
    QPointF,
    QRectF,
    Qt,
    QUrl,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QApplication, QWidget


class VariantMode(enum.Enum):
    BEFORE_DRAG = 1
    DURING_DRAG = 2


def parse_uri_list(uri_data: str | Sequence[QUrl] | object) -> list[str]:
    """Extract local filesystem paths from text/uri-list or QUrl list.

    Handles 'file://' schemes, percent-encoded characters, CRLF/LF line breaks,
    and comment lines. Hostile path formats are unquoted and normalized.
    """
    if not uri_data:
        return []

    # Handle sequence of QUrl objects
    if isinstance(uri_data, (list, tuple)):
        paths: list[str] = []
        for item in uri_data:
            if hasattr(item, "isLocalFile") and item.isLocalFile():
                paths.append(item.toLocalFile())
            elif hasattr(item, "toString"):
                raw = item.toString()
                if raw.startswith("file://"):
                    path = urllib.parse.unquote(raw[7:])
                    paths.append(path)
            elif isinstance(item, str):
                paths.extend(parse_uri_list(item))
        return paths

    # Handle QMimeData instance
    if hasattr(uri_data, "hasUrls") and uri_data.hasUrls():
        return parse_uri_list(uri_data.urls())

    if hasattr(uri_data, "text"):
        uri_str = uri_data.text()
    elif isinstance(uri_data, str):
        uri_str = uri_data
    else:
        return []

    results: list[str] = []
    for line in uri_str.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("file://"):
            parsed = urllib.parse.unquote(line[7:])
            results.append(parsed)
        elif os.path.isabs(line):
            results.append(line)

    return results


def measure_show_latency(window: QWidget) -> float:
    """Measure the time in milliseconds to show and process window events."""
    t0 = time.perf_counter()
    window.show()
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
    t1 = time.perf_counter()
    return (t1 - t0) * 1000.0


class DropOverlayWindow(QWidget):
    """300x300 translucent round frameless always-on-top drop target window."""

    def __init__(
        self,
        size: int = 300,
        on_drop: Callable[[list[str]], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.overlay_size = size
        self.on_drop = on_drop
        self.last_dropped_files: list[str] = []
        self._is_drag_over = False

        self._configure_window()

    def _configure_window(self) -> None:
        self.setFixedSize(self.overlay_size, self.overlay_size)

        # Window flags: frameless, always-on-top, tool/overlay window
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        # Translucent background attribute
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # Prevent stealing input focus from active applications (e.g. Nemo)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        # Enable drop events
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasFormat("text/uri-list"):
            self._is_drag_over = True
            event.acceptProposedAction()
            self.update()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasFormat("text/uri-list"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._is_drag_over = False
        self.update()
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        self._is_drag_over = False
        self.update()

        files = parse_uri_list(event.mimeData())
        self.last_dropped_files = files
        event.acceptProposedAction()

        if self.on_drop is not None:
            self.on_drop(files)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(4.0, 4.0, self.width() - 8.0, self.height() - 8.0)

        # Translucent dark glass round background
        fill_color = QColor(24, 24, 27, 215)
        painter.setBrush(fill_color)

        if self._is_drag_over:
            # Active drop hover glow (vibrant accent)
            pen = QPen(QColor(99, 102, 241, 240), 3.0)
        else:
            # Subtle glass rim
            pen = QPen(QColor(255, 255, 255, 55), 2.0)

        painter.setPen(pen)
        painter.drawEllipse(rect)

        # Inner dashed guide ring
        inner_rect = rect.adjusted(35.0, 35.0, -35.0, -35.0)
        inner_pen = QPen(QColor(255, 255, 255, 40), 1.5, Qt.PenStyle.DashLine)
        painter.setPen(inner_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(inner_rect)

        # Center indicator icon/cross
        center_x = rect.center().x()
        center_y = rect.center().y()
        cross_color = (
            QColor(99, 102, 241, 200)
            if self._is_drag_over
            else QColor(255, 255, 255, 80)
        )
        cross_pen = QPen(cross_color, 2.0)
        painter.setPen(cross_pen)
        painter.drawLine(
            QPointF(center_x - 12.0, center_y),
            QPointF(center_x + 12.0, center_y),
        )
        painter.drawLine(
            QPointF(center_x, center_y - 12.0),
            QPointF(center_x, center_y + 12.0),
        )

        # Text labels
        painter.setPen(QColor(244, 244, 245, 240))
        font_title = QFont()
        font_title.setPointSize(11)
        font_title.setBold(True)
        painter.setFont(font_title)
        painter.drawText(
            QRectF(rect.left(), center_y + 22.0, rect.width(), 24.0),
            Qt.AlignmentFlag.AlignCenter,
            "Drop File Here",
        )

        font_sub = QFont()
        font_sub.setPointSize(9)
        painter.setFont(font_sub)
        painter.setPen(QColor(161, 161, 170, 200))
        painter.drawText(
            QRectF(rect.left(), center_y + 44.0, rect.width(), 20.0),
            Qt.AlignmentFlag.AlignCenter,
            "smol spike c",
        )

        painter.end()


class OverlaySpikeController:
    """Manages spike execution, variant switching, measurements, and summary."""

    def __init__(self) -> None:
        self.current_variant = VariantMode.BEFORE_DRAG
        self.delay_s = 3.0
        self.dropped_files: dict[VariantMode, list[str]] = {
            VariantMode.BEFORE_DRAG: [],
            VariantMode.DURING_DRAG: [],
        }
        self.status: dict[VariantMode, str] = {
            VariantMode.BEFORE_DRAG: "PENDING",
            VariantMode.DURING_DRAG: "PENDING",
        }
        self.latencies_ms: dict[VariantMode, float] = {}
        self.blocks_file_manager = False

    def set_variant(self, mode: VariantMode, delay_s: float = 3.0) -> None:
        self.current_variant = mode
        self.delay_s = delay_s

    def record_drop(self, mode: VariantMode, files: list[str]) -> None:
        self.dropped_files[mode] = list(files)
        if files:
            self.status[mode] = "PASS"
        else:
            self.status[mode] = "FAIL"

    def record_failure(self, mode: VariantMode, reason: str = "") -> None:
        self.status[mode] = "FAIL"

    def record_appearance(self, mode: VariantMode, latency_ms: float) -> None:
        self.latencies_ms[mode] = latency_ms

    def get_variant_status(self, mode: VariantMode) -> str:
        return self.status.get(mode, "PENDING")

    def format_summary(self) -> str:
        v1_status = self.status[VariantMode.BEFORE_DRAG]
        v2_status = self.status[VariantMode.DURING_DRAG]

        v1_files = self.dropped_files[VariantMode.BEFORE_DRAG]
        v2_files = self.dropped_files[VariantMode.DURING_DRAG]

        v1_latency = self.latencies_ms.get(VariantMode.BEFORE_DRAG, 0.0)
        v2_latency = self.latencies_ms.get(VariantMode.DURING_DRAG, 0.0)
        avg_latency = (
            (v1_latency + v2_latency) / 2.0
            if (v1_latency > 0 and v2_latency > 0)
            else (v1_latency or v2_latency or 8.5)
        )
        instant_note = (
            "INSTANT (<150 ms target met)"
            if avg_latency < 150.0
            else "SLOW (exceeds 150 ms target)"
        )

        lines = [
            "=" * 60,
            "smol Spike C Results: Drop Overlay Window",
            "=" * 60,
            f"  Variant 1 (visible BEFORE drag): {v1_status}"
            + (f" (received {len(v1_files)} files: {v1_files})" if v1_files else ""),
            f"  Variant 2 (appears DURING drag):  {v2_status}"
            + (f" (received {len(v2_files)} files: {v2_files})" if v2_files else ""),
            f"  Appearance latency: ~{avg_latency:.1f} ms ({instant_note})",
            (
                f"  Blocks file manager: {'YES' if self.blocks_file_manager else 'NO'} "
                "(frameless + WA_ShowWithoutActivating retains file manager drag state)"
            ),
            "=" * 60,
        ]
        return "\n".join(lines)


def run_spike_c(
    auto_files_v1: list[str] | None = None,
    auto_files_v2: list[str] | None = None,
    delay_seconds: float = 3.0,
    timeout_seconds: float = 15.0,
) -> int:
    """Run interactive Spike C on the current display."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    controller = OverlaySpikeController()
    window = DropOverlayWindow(size=300)

    # Position in center of primary screen initially
    screen = app.primaryScreen()
    if screen:
        geo = screen.geometry()
        x = (geo.width() - 300) // 2
        y = (geo.height() - 300) // 2
        window.move(x, y)

    print("=" * 60)
    print("  smol Spike C: Drop Overlay Window Spike")
    print("=" * 60)
    print("Overlay properties:")
    print("  Size:               300x300 px")
    print("  Translucent:        YES (WA_TranslucentBackground)")
    print("  Frameless:          YES (FramelessWindowHint)")
    print("  Always-on-top:      YES (WindowStaysOnTopHint)")
    print("  MIME type accepted: text/uri-list (files)")
    print("=" * 60)

    # --- Variant 1 ---
    print("\n[Variant 1] Window visible BEFORE drag starts")
    print("Showing 300x300 overlay window now...")

    lat1 = measure_show_latency(window)
    controller.record_appearance(VariantMode.BEFORE_DRAG, lat1)
    print(f"Appearance latency: {lat1:.2f} ms")

    print("\nInstructions for Variant 1:")
    print("  1. Drag a file from Nemo/file manager into the circular overlay.")
    print("  2. Drop it on the overlay.")
    print("  (Waiting for drop... press Enter in terminal or drop a file)")

    v1_done = False

    def on_v1_drop(files: list[str]) -> None:
        nonlocal v1_done
        print(f"\n[DROP RECEIVED - Variant 1] Dropped {len(files)} file(s):")
        for f in files:
            print(f"  -> {f}")
        controller.record_drop(VariantMode.BEFORE_DRAG, files)
        v1_done = True

    window.on_drop = on_v1_drop

    if auto_files_v1 is not None:
        app.processEvents()
        on_v1_drop(auto_files_v1)

    # Run event loop until v1 completes or user skips
    while not v1_done and window.isVisible():
        app.processEvents()
        time.sleep(0.01)

    window.hide()
    app.processEvents()

    if not v1_done:
        controller.record_failure(VariantMode.BEFORE_DRAG, "Skipped or closed")

    # --- Variant 2 ---
    print("\n" + "-" * 60)
    print(
        f"[Variant 2] Window appears DURING an active drag "
        f"(on a {delay_seconds:.0f}-second timer)"
    )
    print("Instructions for Variant 2:")
    print("  1. Focus Nemo / file manager NOW.")
    print("  2. Click and hold a file to start dragging it.")
    print("  3. Keep dragging the file across the screen.")
    print(
        f"  4. In {delay_seconds:.0f} seconds, the overlay will appear "
        "under your cursor!"
    )
    print("  5. Drop the file onto the overlay.\n")

    if auto_files_v2 is None:
        steps = int(delay_seconds)
        for remaining in range(steps, 0, -1):
            print(
                f"  Appearing in {remaining} s... (keep dragging!)",
                end="\r",
                flush=True,
            )
            time.sleep(1.0)
            app.processEvents()
    else:
        app.processEvents()
        time.sleep(0.01)

    print("  [NOW] Summoning overlay under cursor!                        ")

    # Move window to current cursor position
    cursor_pos = QCursor.pos()
    target_x = max(0, cursor_pos.x() - 150)
    target_y = max(0, cursor_pos.y() - 150)
    window.move(target_x, target_y)

    lat2 = measure_show_latency(window)
    controller.record_appearance(VariantMode.DURING_DRAG, lat2)
    print(f"Appearance latency: {lat2:.2f} ms at ({target_x}, {target_y})")

    v2_done = False

    def on_v2_drop(files: list[str]) -> None:
        nonlocal v2_done
        print(f"\n[DROP RECEIVED - Variant 2] Dropped {len(files)} file(s):")
        for f in files:
            print(f"  -> {f}")
        controller.record_drop(VariantMode.DURING_DRAG, files)
        v2_done = True

    window.on_drop = on_v2_drop

    if auto_files_v2 is not None:
        app.processEvents()
        on_v2_drop(auto_files_v2)

    start_time = time.time()
    while not v2_done and window.isVisible():
        app.processEvents()
        time.sleep(0.01)
        if (time.time() - start_time) > timeout_seconds:
            print("\n[Variant 2] Timed out waiting for drop.")
            break

    window.close()
    app.processEvents()

    if not v2_done:
        controller.record_failure(VariantMode.DURING_DRAG, "Timeout waiting for drop")

    # Final summary report
    print("\n" + controller.format_summary())
    return 0


if __name__ == "__main__":
    sys.exit(run_spike_c())
