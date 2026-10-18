"""PySide6 Donut Overlay Window.

A frameless, translucent, always-on-top radial menu centered at the cursor.
Renders 8 target size segments using DonutGeometry, liquid glass aesthetics,
a center circular card with thumbnail, filename, and current file size.
Segments larger than the file are dimmed and unclickable.
Pressing Esc or clicking outside closes the overlay.
"""

from __future__ import annotations

import math
import os
import re
import urllib.parse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    QMimeData,
    QPoint,
    QPointF,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QFontMetrics,
    QImage,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QWidget

from smol.core.config import add_custom_size, get_custom_sizes
from smol.core.result import Result
from smol.core.size import format_size, parse_size
from smol.ui.custom_input import CustomInputDialog
from smol.ui.donut_geometry import DonutGeometry
from smol.ui.prediction import Prediction, PredictionService
from smol.ui.worker import ShrinkWorker

DEFAULT_SEGMENT_CONFIG: list[tuple[str, int | None]] = [
    ("20 KB", 20_000),
    ("50 KB", 50_000),
    ("100 KB", 100_000),
    ("200 KB", 200_000),
    ("500 KB", 500_000),
    ("1 MB", 1_000_000),
    ("2 MB", 2_000_000),
    ("Custom…", None),
]


def build_segment_config(
    config_path: Path | str | None = None,
) -> list[tuple[str, int | None]]:
    """Build list of segment tuples: default sizes, up to 3 custom sizes, and Custom…"""
    base: list[tuple[str, int | None]] = [
        ("20 KB", 20_000),
        ("50 KB", 50_000),
        ("100 KB", 100_000),
        ("200 KB", 200_000),
        ("500 KB", 500_000),
        ("1 MB", 1_000_000),
        ("2 MB", 2_000_000),
    ]
    base_bytes = {b for _, b in base if b is not None}
    custom_sizes = get_custom_sizes(config_path)
    for sz in custom_sizes:
        if sz not in base_bytes:
            base.append((format_size(sz, spaced=True), sz))
    base.append(("Custom…", None))
    return base


@dataclass
class SegmentItem:
    """A segment displayed in the donut."""

    index: int
    label: str
    target_bytes: int | None
    enabled: bool = True


def _load_thumbnail_pixmap(path: Path, max_size: int = 70) -> QPixmap | None:
    """Load a thumbnail QPixmap from *path*, using Pillow if available."""
    if not path.is_file():
        return None

    try:
        import pillow_heif
        from PIL import Image, ImageOps

        pillow_heif.register_heif_opener()

        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img)
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            raw_data = img.tobytes("raw", "RGBA")
            qimage = QImage(
                raw_data,
                img.width,
                img.height,
                QImage.Format.Format_RGBA8888,
            )
            return QPixmap.fromImage(qimage)
    except (OSError, ValueError, RuntimeError):
        pass

    # Fallback to direct Qt pixmap loading
    try:
        pix = QPixmap(str(path))
        if not pix.isNull():
            return pix.scaled(
                max_size,
                max_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
    except (OSError, RuntimeError):
        pass

    return None


def _apply_blur(pixmap: QPixmap, radius: int = 14) -> QPixmap:
    """Apply Gaussian blur to *pixmap* using Pillow or smooth downscale/upscale."""
    try:
        from PIL import Image, ImageFilter

        qimg = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        w, h = qimg.width(), qimg.height()
        raw_bytes = qimg.bits().tobytes()
        img = Image.frombuffer("RGBA", (w, h), raw_bytes, "raw", "RGBA", 0, 1)
        blurred = img.filter(ImageFilter.GaussianBlur(radius=radius))
        out_bytes = blurred.tobytes("raw", "RGBA")
        result_qimg = QImage(out_bytes, w, h, QImage.Format.Format_RGBA8888)
        return QPixmap.fromImage(result_qimg)
    except (OSError, ValueError, RuntimeError):
        # High quality multi-step downscale/upscale fallback
        small = pixmap.scaled(
            max(1, pixmap.width() // 8),
            max(1, pixmap.height() // 8),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        return small.scaled(
            pixmap.width(),
            pixmap.height(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )


_active_shrink_workers: set[ShrinkWorker] = set()


class DonutWindow(QWidget):
    """Frameless translucent always-on-top donut menu centered on the cursor."""

    shrink_started = Signal(object)
    shrink_progress = Signal(int, int, str)
    shrink_finished = Signal(list)
    shrink_failed = Signal(str, object)

    def __init__(
        self,
        files: Sequence[Path | str],
        size: int = 380,
        inner_radius: float = 75.0,
        outer_radius: float = 175.0,
        gap_angle: float = 0.0,
        on_select: Callable[[str], None] | None = None,
        config_path: Path | str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.file_paths = [Path(f) for f in files]
        self.overlay_size = size
        self.inner_radius = inner_radius
        self.outer_radius = outer_radius
        self.gap_angle = gap_angle
        self.on_select = on_select
        self.config_path = config_path
        self.selected_size: str | None = None
        self._custom_dialog: CustomInputDialog | None = None
        self._pending_custom_files: list[Path] = []

        self.state: str = "idle"  # "idle" | "working" | "success" | "failure"
        self.center_status_text: str = ""
        self.result_message: str | None = None
        self.last_results: list[tuple[Path, Result]] | None = None
        self.failure_error: str | None = None
        self.retry_target_bytes: int | None = None
        self._retry_rect: QRectF | None = None
        self._shrink_worker: ShrinkWorker | None = None

        self._hovered_idx: int | None = None
        self._current_prediction: Prediction | None = None
        self._blurred_desktop: QPixmap | None = None

        # Prediction service for hover estimation
        self.prediction_service = PredictionService(debounce_ms=150, parent=self)
        self.prediction_service.prediction_ready.connect(self._on_prediction_ready)
        self.prediction_service.prediction_cleared.connect(self._on_prediction_cleared)

        # File metadata and thumbnail
        self._init_file_data()

        # Build segment items with dimming logic and geometry
        self._init_segments()

        # Setup window properties
        self._configure_window()

    def _init_file_data(self) -> None:
        """Inspect input files to compute names, sizes, and thumbnail."""
        self.total_bytes = 0
        self.max_file_bytes = 0

        existing_files = [p for p in self.file_paths if p.is_file()]
        for p in existing_files:
            try:
                sz = p.stat().st_size
                self.total_bytes += sz
                self.max_file_bytes = max(self.max_file_bytes, sz)
            except OSError:
                continue

        if not self.file_paths:
            self.file_name = "Drop files here"
            self.file_size_text = ""
            self.thumbnail_pixmap = None
        elif len(self.file_paths) == 1:
            first = self.file_paths[0]
            self.file_name = first.name
            self.file_size_text = format_size(self.total_bytes, spaced=True)
            self.thumbnail_pixmap = _load_thumbnail_pixmap(first, max_size=64)
        else:
            self.file_name = f"{len(self.file_paths)} files"
            self.file_size_text = format_size(self.total_bytes, spaced=True)
            self.thumbnail_pixmap = None
            for p in existing_files:
                pix = _load_thumbnail_pixmap(p, max_size=64)
                if pix is not None and not pix.isNull():
                    self.thumbnail_pixmap = pix
                    break

    def _init_segments(self) -> None:
        """Initialize segment items and apply dimming logic."""
        self.segments_config = build_segment_config(self.config_path)
        self.geometry_calc = DonutGeometry(
            n_segments=len(self.segments_config),
            inner_radius=self.inner_radius,
            outer_radius=self.outer_radius,
            gap_angle=self.gap_angle,
        )
        self.segments: list[SegmentItem] = []
        for idx, (label, target_bytes) in enumerate(self.segments_config):
            # Segments larger than the file are dimmed and unclickable
            # If no files or zero size, keep all segments enabled
            if not self.file_paths or self.max_file_bytes == 0 or target_bytes is None:
                enabled = True
            else:
                enabled = target_bytes <= self.max_file_bytes

            self.segments.append(
                SegmentItem(
                    index=idx,
                    label=label,
                    target_bytes=target_bytes,
                    enabled=enabled,
                )
            )

    def _configure_window(self) -> None:
        """Configure Qt window flags, attributes, opacity, tracking, and drops."""
        self.setFixedSize(self.overlay_size, self.overlay_size)

        # Frameless, stays on top, tool window
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        # Translucent background
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # Don't steal window activation
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        # Window opacity (0.96 slight see-through quality at edges)
        self.setWindowOpacity(0.96)

        # Mouse tracking for hover highlights
        self.setMouseTracking(True)

        # Accept file drag-and-drop
        self.setAcceptDrops(True)

    def capture_desktop_background(self) -> None:
        """Capture and blur the desktop area behind the window for frosted glass."""
        try:
            cursor_pos = QCursor.pos()
            screen = QApplication.screenAt(cursor_pos) or QApplication.primaryScreen()
            if screen:
                raw_grab = screen.grabWindow(
                    0, self.x(), self.y(), self.width(), self.height()
                )
                if not raw_grab.isNull():
                    self._blurred_desktop = _apply_blur(raw_grab, radius=14)
        except (OSError, RuntimeError, AttributeError):
            self._blurred_desktop = None

    def adapt_compact_size(
        self,
        size: int = 340,
        inner_radius: float = 68.0,
        outer_radius: float = 156.0,
    ) -> None:
        """Adaptively scale donut geometry for compact screens."""
        self.overlay_size = size
        self.inner_radius = inner_radius
        self.outer_radius = outer_radius
        self.setFixedSize(size, size)
        self._init_segments()

    def center_on_cursor(self) -> None:
        """Position overlay centered on the current cursor position."""
        cursor_pos = QCursor.pos()
        screen = QApplication.screenAt(cursor_pos) or QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            # If screen is compact (<= 720 height), adapt overlay size if default
            if geo.height() <= 720 and self.overlay_size == 380:
                self.adapt_compact_size(340, 68.0, 156.0)

            w = self.width()
            h = self.height()
            target_x = cursor_pos.x() - (w // 2)
            target_y = cursor_pos.y() - (h // 2)

            # Clamp to screen boundary with safety margin
            margin = 8
            target_x = max(geo.left() + margin, min(target_x, geo.right() - w - margin))
            target_y = max(geo.top() + margin, min(target_y, geo.bottom() - h - margin))
            self.move(target_x, target_y)
        else:
            w = self.width()
            h = self.height()
            self.move(cursor_pos.x() - (w // 2), cursor_pos.y() - (h // 2))

    def run_overlay(self) -> int:
        """Center on cursor, capture backdrop, show window, and execute event loop."""
        self.center_on_cursor()
        self.capture_desktop_background()
        self.show()
        app = QApplication.instance()
        if app is not None:
            return app.exec()
        return 0

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Esc key dismisses the overlay and any open custom dialog."""
        if event.key() == Qt.Key.Key_Escape:
            if self._custom_dialog is not None and self._custom_dialog.isVisible():
                self._custom_dialog.close()
            self.close()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _open_custom_dialog(self, pos: QPointF | QPoint | None = None) -> None:
        """Open tiny custom input dialog near the cursor or segment."""
        if self._custom_dialog is not None and self._custom_dialog.isVisible():
            self._custom_dialog.close()

        self._custom_dialog = CustomInputDialog()
        self._custom_dialog.confirmed.connect(self._on_custom_confirmed)
        self._custom_dialog.cancelled.connect(self._on_custom_cancelled)

        if pos is not None:
            pt = pos.toPoint() if hasattr(pos, "toPoint") else pos
            global_pos = self.mapToGlobal(pt)
        else:
            global_pos = QCursor.pos()

        self._custom_dialog.position_near(global_pos)
        self._custom_dialog.show()
        self._custom_dialog.raise_()
        self._custom_dialog.activateWindow()

    def _on_custom_confirmed(self, target_bytes: int) -> None:
        """Handle confirmed custom target size."""
        add_custom_size(target_bytes, self.config_path)

        files = list(self._pending_custom_files) if self._pending_custom_files else None
        self._pending_custom_files = []

        if files:
            self.file_paths = files
            self._init_file_data()

        self._init_segments()
        self.update()

        self.start_shrink(target_bytes, files=files)

    def _on_custom_cancelled(self) -> None:
        """Handle cancelled custom input."""
        self._pending_custom_files = []

    def _on_prediction_ready(
        self, path_str: str, target_bytes: int, prediction: Prediction
    ) -> None:
        """Update center display when prediction arrives for current hover."""
        if self._hovered_idx is not None:
            item = self.segments[self._hovered_idx]
            if item.target_bytes == target_bytes:
                self._current_prediction = prediction
                self.update()

    def _on_prediction_cleared(self) -> None:
        """Clear current prediction text."""
        if self._current_prediction is not None:
            self._current_prediction = None
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Update hover state on segments and trigger debounced prediction."""
        if self.state == "working":
            event.accept()
            return

        center = self.rect().center()
        pos = event.position() if hasattr(event, "position") else event.pos()
        dx = pos.x() - center.x()
        dy = pos.y() - center.y()

        idx = self.geometry_calc.segment_at(dx, dy)
        if idx != self._hovered_idx:
            self._hovered_idx = idx
            if idx is None:
                self.prediction_service.cancel()
                self._current_prediction = None
            else:
                item = self.segments[idx]
                if (
                    not item.enabled
                    or item.target_bytes is None
                    or self.state != "idle"
                ):
                    self.prediction_service.cancel()
                    self._current_prediction = None
                else:
                    first_file = self._first_image_path()
                    if first_file is not None:
                        self.prediction_service.request(first_file, item.target_bytes)
            self.update()
        event.accept()

    def leaveEvent(self, event: object) -> None:
        """Clear hover state and cancel pending predictions when mouse leaves window."""
        if self._hovered_idx is not None:
            self._hovered_idx = None
            self.prediction_service.cancel()
            self._current_prediction = None
            self.update()

    def closeEvent(self, event: object) -> None:
        """Clean up background workers and child dialogs on close."""
        if self._custom_dialog is not None and self._custom_dialog.isVisible():
            self._custom_dialog.close()
        self.prediction_service.cancel()
        self.prediction_service.wait_for_workers(timeout_ms=300)
        if self._shrink_worker is not None and self._shrink_worker.isRunning():
            self._shrink_worker.cancel()
            self._shrink_worker.wait(300)
        super().closeEvent(event)

    def _parse_drop_uris(self, mime_data: QMimeData | object) -> list[Path]:
        """Extract existing local Path objects from drag-and-drop MIME data."""
        paths: list[Path] = []
        if hasattr(mime_data, "urls") and mime_data.urls():
            for url in mime_data.urls():
                if url.isLocalFile():
                    p = Path(url.toLocalFile())
                    if p.exists():
                        paths.append(p)
                else:
                    raw = url.toString()
                    if raw.startswith("file://"):
                        p = Path(urllib.parse.unquote(raw[7:]))
                        if p.exists():
                            paths.append(p)
        elif hasattr(mime_data, "text") and mime_data.text():
            for line in mime_data.text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("file://"):
                    p = Path(urllib.parse.unquote(line[7:]))
                    if p.exists():
                        paths.append(p)
                elif os.path.isabs(line):
                    p = Path(line)
                    if p.exists():
                        paths.append(p)
        return paths

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept drag if it contains URLs or text/uri-list."""
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasFormat("text/uri-list"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        """Track segment under cursor during drag."""
        center = self.rect().center()
        pos = event.position() if hasattr(event, "position") else event.pos()
        dx = pos.x() - center.x()
        dy = pos.y() - center.y()
        idx = self.geometry_calc.segment_at(dx, dy)
        if idx != self._hovered_idx:
            self._hovered_idx = idx
            self.update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        """Clear drag hover state."""
        self._hovered_idx = None
        self.update()
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        """Handle file drops onto a donut segment."""
        center = self.rect().center()
        pos = event.position() if hasattr(event, "position") else event.pos()
        dx = pos.x() - center.x()
        dy = pos.y() - center.y()
        idx = self.geometry_calc.segment_at(dx, dy)

        dropped_files = self._parse_drop_uris(event.mimeData())
        if not dropped_files:
            event.ignore()
            return

        if idx is not None:
            item = self.segments[idx]
            if item.target_bytes is not None:
                event.acceptProposedAction()
                self.file_paths = dropped_files
                self._init_file_data()
                self._init_segments()
                self.selected_size = item.label
                if self.on_select:
                    self.on_select(item.label)
                self.start_shrink(item.target_bytes)
                return
            else:
                event.acceptProposedAction()
                self._pending_custom_files = dropped_files
                self.selected_size = item.label
                if self.on_select:
                    self.on_select(item.label)
                self._open_custom_dialog(pos=pos)
                return

        event.ignore()

    def start_shrink(
        self,
        target_bytes: int,
        files: Sequence[Path | str] | None = None,
    ) -> None:
        """Start the shrink worker thread for chosen target_bytes."""
        if self.state == "working":
            return

        if files is not None:
            self.file_paths = [Path(f) for f in files]
            self._init_file_data()
            self._init_segments()

        if not self.file_paths:
            return

        self.prediction_service.cancel()
        self._current_prediction = None

        self.state = "working"
        if len(self.file_paths) > 1:
            self.center_status_text = f"Shrinking (1/{len(self.file_paths)})..."
        else:
            self.center_status_text = "Shrinking..."

        self.result_message = None
        self.failure_error = None
        self.retry_target_bytes = None
        self._retry_rect = None

        self.shrink_started.emit(target_bytes)

        worker = ShrinkWorker(
            files=self.file_paths,
            target_bytes=target_bytes,
            parent=None,
        )
        self._shrink_worker = worker
        _active_shrink_workers.add(worker)
        worker.finished.connect(lambda: _active_shrink_workers.discard(worker))
        worker.progress.connect(self._on_shrink_progress)
        worker.results_ready.connect(self._on_shrink_finished)
        worker.start()
        self.update()

    def _on_shrink_progress(self, cur: int, total: int, name: str) -> None:
        """Handle worker progress updates."""
        if total > 1:
            self.center_status_text = f"Shrinking ({cur}/{total})..."
        else:
            self.center_status_text = "Shrinking..."
        self.shrink_progress.emit(cur, total, name)
        self.update()

    def _first_image_path(self) -> Path | None:
        """Find the first likely image file in self.file_paths for prediction."""
        for p in self.file_paths:
            if not p.is_file():
                continue
            if p.suffix.lower() in (
                ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".avif"
            ):
                return p
        return self.file_paths[0] if self.file_paths else None

    def _on_shrink_finished(self, results: list[tuple[Path, Result]]) -> None:
        """Handle completion of background shrink job."""
        self.last_results = results

        shrunk_items = [
            (p, r) for p, r in results if r.ok and r.output_path is not None
        ]
        small_items = [
            (p, r) for p, r in results if r.ok and r.output_path is None
        ]
        skipped_items = [
            (p, r)
            for p, r in results
            if not r.ok
            and r.error
            and ("unsupported" in r.error.lower() or "skipped" in r.error.lower())
        ]
        failed_items = [
            (p, r)
            for p, r in results
            if not r.ok
            and (
                not r.error
                or (
                    "unsupported" not in r.error.lower()
                    and "skipped" not in r.error.lower()
                )
            )
        ]

        if failed_items:
            self.state = "failure"
            _failed_path, failed_res = failed_items[0]
            self.failure_error = failed_res.error or "Compression failed"
            m = re.search(r"Smallest[^~]*~([0-9.]+\s*[A-Za-z]+)", self.failure_error)
            if m:
                try:
                    self.retry_target_bytes = parse_size(m.group(1).strip())
                except (ValueError, TypeError):
                    self.retry_target_bytes = None
            else:
                self.retry_target_bytes = None

            self.shrink_failed.emit(self.failure_error, self.retry_target_bytes)
        elif not shrunk_items and not small_items and skipped_items:
            self.state = "failure"
            _skipped_path, skipped_res = skipped_items[0]
            self.failure_error = skipped_res.error or "Unsupported file format"
            self.retry_target_bytes = None
            self.shrink_failed.emit(self.failure_error, None)
        else:
            self.state = "success"
            if len(results) == 1:
                _src, res = results[0]
                if res.output_path is not None:
                    orig_sz = format_size(res.original_bytes, spaced=True)
                    final_sz = format_size(res.final_bytes, spaced=True)
                    self.result_message = f"{orig_sz} → {final_sz}"
                else:
                    self.result_message = "Already ≤ target"
            else:
                parts: list[str] = []
                if shrunk_items:
                    parts.append(f"{len(shrunk_items)} shrunk")
                if small_items:
                    parts.append(f"{len(small_items)} already small")
                if skipped_items:
                    parts.append(f"{len(skipped_items)} skipped")
                self.result_message = ", ".join(parts) if parts else "Complete"

            self.shrink_finished.emit(results)

        self.update()

    def retry_smallest(self) -> None:
        """Retry shrinking at the smallest achievable target size."""
        if self.retry_target_bytes is not None:
            self.start_shrink(self.retry_target_bytes)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle clicks on segments, retry option, or outside."""
        if event.button() != Qt.MouseButton.LeftButton:
            return

        center = self.rect().center()
        pos = event.position() if hasattr(event, "position") else event.pos()
        dx = pos.x() - center.x()
        dy = pos.y() - center.y()
        r = math.hypot(dx, dy)

        if self.state == "working":
            event.accept()
            return

        if self.state == "failure":
            if (self._retry_rect and self._retry_rect.contains(pos)) or (
                r <= self.geometry_calc.inner_radius and self.retry_target_bytes
            ):
                self.retry_smallest()
                event.accept()
                return
            if r > self.geometry_calc.outer_radius:
                self.close()
                event.accept()
                return
            idx = self.geometry_calc.segment_at(dx, dy)
            if idx is not None:
                item = self.segments[idx]
                if item.enabled:
                    if item.target_bytes is not None:
                        self.start_shrink(item.target_bytes)
                        event.accept()
                        return
                    else:
                        self._open_custom_dialog(pos=pos)
                        event.accept()
                        return
            return

        if self.state == "success":
            if r > self.geometry_calc.outer_radius:
                self.close()
                event.accept()
                return
            idx = self.geometry_calc.segment_at(dx, dy)
            if idx is not None:
                item = self.segments[idx]
                if item.enabled:
                    if item.target_bytes is not None:
                        self.start_shrink(item.target_bytes)
                        event.accept()
                        return
                    else:
                        self._open_custom_dialog(pos=pos)
                        event.accept()
                        return
            return

        # Idle state
        idx = self.geometry_calc.segment_at(dx, dy)
        if idx is None:
            if r > self.geometry_calc.outer_radius:
                self.close()
                event.accept()
                return
            return

        item = self.segments[idx]
        if not item.enabled:
            return

        self.selected_size = item.label
        if self.on_select:
            self.on_select(item.label)

        if item.target_bytes is not None:
            self.start_shrink(item.target_bytes)
            event.accept()
        else:
            self._open_custom_dialog(pos=pos)
            event.accept()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Render liquid glass donut segments, highlights, and center card."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        center_x = self.width() / 2.0
        center_y = self.height() / 2.0
        center_pt = QPointF(center_x, center_y)

        r_in = self.geometry_calc.inner_radius
        r_out = self.geometry_calc.outer_radius

        outer_rect = QRectF(center_x - r_out, center_y - r_out, r_out * 2, r_out * 2)
        inner_rect = QRectF(center_x - r_in, center_y - r_in, r_in * 2, r_in * 2)

        # 1. Ambient outer drop shadow (elevation effect)
        shadow_rect = QRectF(
            center_x - r_out - 12.0,
            center_y - r_out - 12.0,
            (r_out + 12.0) * 2,
            (r_out + 12.0) * 2,
        )
        shadow_grad = QRadialGradient(center_pt, r_out + 12.0)
        shadow_grad.setColorAt(r_out / (r_out + 12.0), QColor(0, 0, 0, 95))
        shadow_grad.setColorAt((r_out + 4.0) / (r_out + 12.0), QColor(0, 0, 0, 45))
        shadow_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(shadow_grad))
        painter.drawEllipse(shadow_rect)

        # 2. Background blur & base dark glass disc
        # (ensures consistent contrast on all wallpapers)
        donut_clip = QPainterPath()
        donut_clip.addEllipse(outer_rect)

        painter.save()
        painter.setClipPath(donut_clip)
        if self._blurred_desktop and not self._blurred_desktop.isNull():
            painter.drawPixmap(0, 0, self._blurred_desktop)

        # Base deep glass foundation disc for consistent rich darkness on all wallpapers
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(16, 18, 27, 215))
        painter.drawEllipse(outer_rect)
        painter.restore()

        # 3. Render each donut segment (tint, highlights, labels)
        for idx, seg_geom in enumerate(self.geometry_calc.segments):
            item = self.segments[idx]
            is_hovered = idx == self._hovered_idx and item.enabled

            # Segment angular path
            path = QPainterPath()
            start_qt = 90.0 - seg_geom.start_angle
            sweep_qt = -self.geometry_calc.span_angle
            end_qt = 90.0 - seg_geom.end_angle

            path.arcMoveTo(outer_rect, start_qt)
            path.arcTo(outer_rect, start_qt, sweep_qt)
            path.arcTo(inner_rect, end_qt, -sweep_qt)
            path.closeSubpath()

            # Segment Fill:
            # Active segments: rich deep glass tint
            # Hovered segments: bright interactive feedback
            # Dimmed segments: darker recessed tint (never brighter than active)
            if not item.enabled:
                fill_color = QColor(10, 12, 18, 160)
            elif is_hovered:
                fill_color = QColor(45, 52, 75, 190)
            else:
                fill_color = QColor(22, 25, 38, 125)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill_color)
            painter.drawPath(path)

            # If hovered: subtle radial glow behind the label and tint brightening
            ax, ay = seg_geom.label_anchor
            anchor = center_pt + QPointF(ax, ay)

            if is_hovered:
                # Subtle hover tint wash
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 255, 255, 25))
                painter.drawPath(path)

                # Radial glow behind label
                glow = QRadialGradient(anchor, 42.0)
                glow.setColorAt(0.0, QColor(255, 255, 255, 45))
                glow.setColorAt(0.6, QColor(255, 255, 255, 18))
                glow.setColorAt(1.0, QColor(255, 255, 255, 0))
                painter.setBrush(QBrush(glow))
                painter.drawEllipse(anchor, 42.0, 42.0)

                # Outer edge accent arc for hovered segment
                path_outer_hover = QPainterPath()
                path_outer_hover.arcMoveTo(outer_rect, start_qt)
                path_outer_hover.arcTo(outer_rect, start_qt, sweep_qt)
                painter.setPen(QPen(QColor(165, 225, 255, 180), 2.0))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path_outer_hover)

            # Segment label:
            # Active labels: 100% white with subtle dark drop shadow
            # Dimmed labels: crisp muted slate (high WCAG contrast, clearly inactive)
            font = QFont()
            font.setPointSize(10)
            font.setBold(True)
            painter.setFont(font)

            text_rect = QRectF(anchor.x() - 45.0, anchor.y() - 12.0, 90.0, 24.0)

            if item.enabled:
                label_color = QColor(255, 255, 255, 255)
                shadow_color = QColor(0, 0, 0, 160)
            else:
                label_color = QColor(160, 172, 195, 175)
                shadow_color = QColor(0, 0, 0, 140)

            # Text shadow for maximum legibility on any wallpaper
            painter.setPen(shadow_color)
            painter.drawText(
                text_rect.adjusted(0, 1, 0, 1),
                Qt.AlignmentFlag.AlignCenter,
                item.label,
            )
            painter.setPen(label_color)
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignCenter,
                item.label,
            )

        # 4. Continuous outer specular rim & inner ring highlight
        rim_grad = QLinearGradient(
            QPointF(center_x, center_y - r_out),
            QPointF(center_x, center_y + r_out),
        )
        rim_grad.setColorAt(0.0, QColor(255, 255, 255, 95))
        rim_grad.setColorAt(0.4, QColor(255, 255, 255, 40))
        rim_grad.setColorAt(1.0, QColor(255, 255, 255, 15))
        painter.setPen(QPen(QBrush(rim_grad), 1.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(outer_rect)

        # Inner ring highlight: seamless continuous bright circle
        painter.setPen(QPen(QColor(255, 255, 255, 45), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(inner_rect)

        # 5. Segment separators: etched glass grooves (shadow line + specular highlight)
        for seg_geom in self.geometry_calc.segments:
            rad = math.radians(seg_geom.start_angle)
            sin_rad = math.sin(rad)
            cos_rad = math.cos(rad)
            x1 = center_x + r_in * sin_rad
            y1 = center_y - r_in * cos_rad
            x2 = center_x + r_out * sin_rad
            y2 = center_y - r_out * cos_rad

            # Subtle shadow groove line
            painter.setPen(QPen(QColor(0, 0, 0, 60), 1.0))
            painter.drawLine(
                QPointF(x1 - cos_rad * 0.5, y1 - sin_rad * 0.5),
                QPointF(x2 - cos_rad * 0.5, y2 - sin_rad * 0.5),
            )
            # Light specular line
            painter.setPen(QPen(QColor(255, 255, 255, 35), 1.0))
            painter.drawLine(
                QPointF(x1 + cos_rad * 0.5, y1 + sin_rad * 0.5),
                QPointF(x2 + cos_rad * 0.5, y2 + sin_rad * 0.5),
            )

        # 6. Centre circle: frosted glass treatment
        center_card_r = r_in - 2.0
        card_rect = QRectF(
            center_x - center_card_r,
            center_y - center_card_r,
            center_card_r * 2,
            center_card_r * 2,
        )

        # Centre dark tint overlay
        painter.setBrush(QColor(15, 15, 25, 205))
        painter.setPen(QPen(QColor(255, 255, 255, 45), 1.2))
        painter.drawEllipse(card_rect)

        if self.state == "working":
            # Working state in centre
            font_work = QFont()
            font_work.setPointSize(11)
            font_work.setBold(True)
            painter.setFont(font_work)
            work_rect = QRectF(
                center_x - center_card_r + 8.0,
                center_y - 18.0,
                (center_card_r - 8.0) * 2,
                22.0,
            )
            painter.setPen(QColor(0, 0, 0, 160))
            painter.drawText(
                work_rect.adjusted(0, 1, 0, 1),
                Qt.AlignmentFlag.AlignCenter,
                "Working…",
            )
            painter.setPen(QColor(165, 225, 255, 255))
            painter.drawText(work_rect, Qt.AlignmentFlag.AlignCenter, "Working…")

            font_sub = QFont()
            font_sub.setPointSize(9)
            painter.setFont(font_sub)
            sub_rect = QRectF(
                center_x - center_card_r + 8.0,
                center_y + 8.0,
                (center_card_r - 8.0) * 2,
                18.0,
            )
            painter.setPen(QColor(0, 0, 0, 140))
            painter.drawText(
                sub_rect.adjusted(0, 1, 0, 1),
                Qt.AlignmentFlag.AlignCenter,
                self.center_status_text or "Shrinking...",
            )
            painter.setPen(QColor(200, 210, 225, 230))
            painter.drawText(
                sub_rect,
                Qt.AlignmentFlag.AlignCenter,
                self.center_status_text or "Shrinking...",
            )

        elif self.state == "success":
            # Success state in centre
            font_done = QFont()
            font_done.setPointSize(12)
            font_done.setBold(True)
            painter.setFont(font_done)
            done_rect = QRectF(
                center_x - center_card_r + 8.0,
                center_y - 20.0,
                (center_card_r - 8.0) * 2,
                22.0,
            )
            painter.setPen(QColor(0, 0, 0, 160))
            painter.drawText(
                done_rect.adjusted(0, 1, 0, 1),
                Qt.AlignmentFlag.AlignCenter,
                "✓ Done",
            )
            painter.setPen(QColor(52, 211, 153, 255))  # Emerald green
            painter.drawText(done_rect, Qt.AlignmentFlag.AlignCenter, "✓ Done")

            font_res = QFont()
            font_res.setPointSize(9)
            font_res.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font_res)
            res_rect = QRectF(
                center_x - center_card_r + 8.0,
                center_y + 6.0,
                (center_card_r - 8.0) * 2,
                20.0,
            )
            painter.setPen(QColor(0, 0, 0, 140))
            painter.drawText(
                res_rect.adjusted(0, 1, 0, 1),
                Qt.AlignmentFlag.AlignCenter,
                self.result_message or "Complete",
            )
            painter.setPen(QColor(240, 245, 255, 240))
            painter.drawText(
                res_rect,
                Qt.AlignmentFlag.AlignCenter,
                self.result_message or "Complete",
            )

        elif self.state == "failure":
            # Honest engine message and retry option
            font_err_title = QFont()
            font_err_title.setPointSize(10)
            font_err_title.setBold(True)
            painter.setFont(font_err_title)
            err_title_rect = QRectF(
                center_x - center_card_r + 8.0,
                center_y - 36.0,
                (center_card_r - 8.0) * 2,
                18.0,
            )
            title_text = "Target too small"
            if self.failure_error:
                err_lower = self.failure_error.lower()
                if "read-only" in err_lower or "permission" in err_lower:
                    title_text = "Folder read-only"
                elif "unsupported" in err_lower:
                    title_text = "Unsupported type"
                elif "not found" in err_lower:
                    title_text = "File not found"

            painter.setPen(QColor(0, 0, 0, 160))
            painter.drawText(
                err_title_rect.adjusted(0, 1, 0, 1),
                Qt.AlignmentFlag.AlignCenter,
                title_text,
            )
            painter.setPen(QColor(251, 191, 36, 255))  # Amber
            painter.drawText(
                err_title_rect,
                Qt.AlignmentFlag.AlignCenter,
                title_text,
            )

            font_err_msg = QFont()
            font_err_msg.setPointSize(8)
            painter.setFont(font_err_msg)

            fm = QFontMetrics(font_err_msg)
            summary_err = self.failure_error or "Cannot shrink"
            if "Smallest" in summary_err:
                m = re.search(r"(Smallest [^;]+)", summary_err)
                if m:
                    summary_err = m.group(1)
            elif "Try an alternative folder" in summary_err:
                m = re.search(r"(Try an alternative folder[^.]*)", summary_err)
                if m:
                    summary_err = m.group(1)
            elif "read-only" in summary_err.lower():
                summary_err = "Output folder is read-only"
            elided_err = fm.elidedText(
                summary_err,
                Qt.TextElideMode.ElideMiddle,
                int(center_card_r * 2 - 12),
            )
            msg_rect = QRectF(
                center_x - center_card_r + 6.0,
                center_y - 14.0,
                (center_card_r - 6.0) * 2,
                18.0,
            )
            painter.setPen(QColor(0, 0, 0, 140))
            painter.drawText(
                msg_rect.adjusted(0, 1, 0, 1),
                Qt.AlignmentFlag.AlignCenter,
                elided_err,
            )
            painter.setPen(QColor(220, 225, 235, 220))
            painter.drawText(msg_rect, Qt.AlignmentFlag.AlignCenter, elided_err)

            if self.retry_target_bytes is not None:
                sz_str = format_size(self.retry_target_bytes, spaced=True)
                retry_text = f"Retry ({sz_str})"
                btn_w = min(110.0, center_card_r * 2 - 16.0)
                btn_h = 24.0
                self._retry_rect = QRectF(
                    center_x - btn_w / 2.0,
                    center_y + 12.0,
                    btn_w,
                    btn_h,
                )

                painter.setBrush(QColor(245, 158, 11, 45))
                painter.setPen(QPen(QColor(245, 158, 11, 180), 1.2))
                painter.drawRoundedRect(self._retry_rect, 6.0, 6.0)

                font_btn = QFont()
                font_btn.setPointSize(8)
                font_btn.setBold(True)
                painter.setFont(font_btn)
                painter.setPen(QColor(254, 243, 199, 255))
                painter.drawText(
                    self._retry_rect,
                    Qt.AlignmentFlag.AlignCenter,
                    retry_text,
                )
            else:
                self._retry_rect = None

        else:
            # Idle state: balanced thumbnail, filename, and size / prediction
            max_thumb = int(min(46, center_card_r * 0.63))
            thumb_top = center_y - float(max_thumb)
            if self.thumbnail_pixmap and not self.thumbnail_pixmap.isNull():
                tw = min(max_thumb, self.thumbnail_pixmap.width())
                th = min(max_thumb, self.thumbnail_pixmap.height())
                tx = center_x - (tw / 2.0)
                ty = thumb_top + ((max_thumb / 2.0) - (th / 2.0))

                # Soft drop shadow behind thumbnail
                shadow_rect = QRectF(tx - 2.0, ty + 2.0, tw + 4.0, th + 4.0)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(0, 0, 0, 120))
                painter.drawRoundedRect(shadow_rect, 10.0, 10.0)

                # Rounded clip for thumbnail
                painter.save()
                clip_path = QPainterPath()
                clip_path.addRoundedRect(QRectF(tx, ty, tw, th), 8.0, 8.0)
                painter.setClipPath(clip_path)
                painter.drawPixmap(
                    int(tx),
                    int(ty),
                    self.thumbnail_pixmap.scaled(
                        tw,
                        th,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    ),
                )
                painter.restore()

                # Delicate border around thumbnail
                painter.setPen(QPen(QColor(255, 255, 255, 45), 1.0))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(QRectF(tx, ty, tw, th), 8.0, 8.0)
            else:
                # File icon placeholder with soft shadow
                icon_w, icon_h = 26.0, 34.0
                icon_rect = QRectF(
                    center_x - (icon_w / 2.0),
                    thumb_top + ((max_thumb - icon_h) / 2.0),
                    icon_w,
                    icon_h,
                )
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(0, 0, 0, 90))
                painter.drawRoundedRect(icon_rect.adjusted(-1, 2, 1, 2), 4.0, 4.0)

                painter.setPen(QPen(QColor(161, 161, 170, 220), 1.5))
                painter.setBrush(QColor(39, 39, 42, 200))
                painter.drawRoundedRect(icon_rect, 4.0, 4.0)

            # Filename: adaptive font sizing & bold weight with soft text shadow
            font_name = QFont()
            if len(self.file_name) > 22:
                font_name.setPointSize(9)
                font_name.setWeight(QFont.Weight.DemiBold)
            else:
                font_name.setPointSize(10)
                font_name.setBold(True)
            painter.setFont(font_name)

            fm = QFontMetrics(font_name)
            name_available_w = int((center_card_r - 6.0) * 2)
            elided_name = fm.elidedText(
                self.file_name,
                Qt.TextElideMode.ElideMiddle,
                name_available_w,
            )
            name_rect = QRectF(
                center_x - center_card_r + 6.0,
                center_y + 7.0,
                (center_card_r - 6.0) * 2,
                18.0,
            )
            painter.setPen(QColor(0, 0, 0, 180))
            painter.drawText(
                name_rect.adjusted(0, 1, 0, 1),
                Qt.AlignmentFlag.AlignCenter,
                elided_name,
            )
            painter.setPen(QColor(255, 255, 255, 250))
            painter.drawText(name_rect, Qt.AlignmentFlag.AlignCenter, elided_name)

            # File size or prediction: 9pt demibold with soft text shadow
            font_size = QFont()
            font_size.setPointSize(9)
            font_size.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font_size)

            if self._current_prediction is not None:
                if self._current_prediction.ok:
                    size_color = QColor(165, 225, 255, 255)
                else:
                    size_color = QColor(251, 191, 36, 255)
                display_text = self._current_prediction.text
            else:
                size_color = QColor(210, 215, 225, 240)
                display_text = self.file_size_text

            size_rect = QRectF(
                center_x - center_card_r + 6.0,
                center_y + 29.0,
                (center_card_r - 6.0) * 2,
                18.0,
            )
            painter.setPen(QColor(0, 0, 0, 160))
            painter.drawText(
                size_rect.adjusted(0, 1, 0, 1),
                Qt.AlignmentFlag.AlignCenter,
                display_text,
            )
            painter.setPen(size_color)
            painter.drawText(size_rect, Qt.AlignmentFlag.AlignCenter, display_text)

        painter.end()
