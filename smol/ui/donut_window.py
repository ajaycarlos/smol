"""PySide6 Donut Overlay Window.

A frameless, translucent, always-on-top radial menu centered at the cursor.
Renders 8 target size segments using DonutGeometry, dark glass aesthetics,
a center circular card with thumbnail, filename, and current file size.
Segments larger than the file are dimmed and unclickable.
Pressing Esc or clicking outside closes the overlay.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    QPointF,
    QRectF,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QWidget

from smol.core.size import format_size
from smol.ui.donut_geometry import DonutGeometry

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


class DonutWindow(QWidget):
    """Frameless translucent always-on-top donut menu centered on the cursor."""

    def __init__(
        self,
        files: Sequence[Path | str],
        size: int = 380,
        inner_radius: float = 75.0,
        outer_radius: float = 175.0,
        gap_angle: float = 2.5,
        on_select: Callable[[str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.file_paths = [Path(f) for f in files]
        self.overlay_size = size
        self.on_select = on_select
        self.selected_size: str | None = None

        self._hovered_idx: int | None = None

        # Build DonutGeometry
        self.geometry_calc = DonutGeometry(
            n_segments=len(DEFAULT_SEGMENT_CONFIG),
            inner_radius=inner_radius,
            outer_radius=outer_radius,
            gap_angle=gap_angle,
        )

        # File metadata and thumbnail
        self._init_file_data()

        # Build segment items with dimming logic
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

        if len(self.file_paths) == 1:
            first = self.file_paths[0]
            self.file_name = first.name
            self.file_size_text = format_size(self.total_bytes, spaced=True)
            self.thumbnail_pixmap = _load_thumbnail_pixmap(first, max_size=64)
        else:
            self.file_name = f"{len(self.file_paths)} files"
            self.file_size_text = format_size(self.total_bytes, spaced=True)
            first_valid = existing_files[0] if existing_files else self.file_paths[0]
            self.thumbnail_pixmap = _load_thumbnail_pixmap(first_valid, max_size=64)

    def _init_segments(self) -> None:
        """Initialize segment items and apply dimming logic."""
        self.segments: list[SegmentItem] = []
        for idx, (label, target_bytes) in enumerate(DEFAULT_SEGMENT_CONFIG):
            # Segments larger than the file are dimmed and unclickable
            # For multiple files, we check against the largest file
            if target_bytes is None:
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
        """Configure Qt window flags, attributes, and tracking."""
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

        # Mouse tracking for hover highlights
        self.setMouseTracking(True)

    def center_on_cursor(self) -> None:
        """Position overlay centered on the current cursor position."""
        cursor_pos = QCursor.pos()
        w = self.width()
        h = self.height()
        target_x = cursor_pos.x() - (w // 2)
        target_y = cursor_pos.y() - (h // 2)

        # Clamp to screen boundary
        screen = QApplication.screenAt(cursor_pos) or QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            target_x = max(geo.left(), min(target_x, geo.right() - w))
            target_y = max(geo.top(), min(target_y, geo.bottom() - h))

        self.move(target_x, target_y)

    def run_overlay(self) -> int:
        """Center on cursor, show window, and execute Qt event loop."""
        self.center_on_cursor()
        self.show()
        app = QApplication.instance()
        if app is not None:
            return app.exec()
        return 0

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Esc key dismisses the overlay."""
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
        else:
            super().keyPressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Update hover state on segments."""
        center = self.rect().center()
        dx = event.position().x() - center.x()
        dy = event.position().y() - center.y()

        idx = self.geometry_calc.segment_at(dx, dy)
        if idx != self._hovered_idx:
            self._hovered_idx = idx
            self.update()
        event.accept()

    def leaveEvent(self, event: object) -> None:
        """Clear hover state when mouse leaves window."""
        if self._hovered_idx is not None:
            self._hovered_idx = None
            self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle clicks on segments or outside."""
        if event.button() != Qt.MouseButton.LeftButton:
            return

        center = self.rect().center()
        dx = event.position().x() - center.x()
        dy = event.position().y() - center.y()

        idx = self.geometry_calc.segment_at(dx, dy)
        if idx is None:
            # Check if clicked outside outer radius
            r = math.hypot(dx, dy)
            if r > self.geometry_calc.outer_radius:
                self.close()
                event.accept()
                return
            # Center hole or gap: ignore
            return

        item = self.segments[idx]
        if not item.enabled:
            # Dimmed segment is unclickable
            return

        # Active segment selected
        self.selected_size = item.label
        if self.on_select:
            self.on_select(item.label)

        self.close()
        event.accept()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Render donut segments, dark glass styling, and center metadata card."""
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

        # 1. Subtle overall dark glass backdrop under the donut ring
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(15, 16, 20, 160))
        painter.drawEllipse(outer_rect.adjusted(-2.0, -2.0, 2.0, 2.0))

        # 2. Render each donut segment
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

            # Colors for segment states
            if not item.enabled:
                # Dimmed and unclickable
                fill_color = QColor(20, 21, 26, 95)
                pen = QPen(QColor(255, 255, 255, 14), 1.0)
                text_color = QColor(113, 113, 122, 110)
            elif is_hovered:
                # Active hovered
                fill_color = QColor(49, 53, 68, 245)
                pen = QPen(QColor(129, 140, 248, 230), 2.0)
                text_color = QColor(255, 255, 255, 255)
            else:
                # Active normal
                fill_color = QColor(28, 30, 38, 225)
                pen = QPen(QColor(255, 255, 255, 38), 1.2)
                text_color = QColor(244, 244, 245, 235)

            painter.setBrush(fill_color)
            painter.setPen(pen)
            painter.drawPath(path)

            # Segment label
            ax, ay = seg_geom.label_anchor
            anchor = center_pt + QPointF(ax, ay)

            font = QFont()
            font.setPointSize(10)
            font.setBold(item.enabled)
            painter.setFont(font)
            painter.setPen(text_color)

            # Center text on anchor
            text_rect = QRectF(anchor.x() - 45.0, anchor.y() - 12.0, 90.0, 24.0)
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignCenter,
                item.label,
            )

        # 3. Center card (inside inner radius)
        center_card_r = r_in - 3.0
        card_rect = QRectF(
            center_x - center_card_r,
            center_y - center_card_r,
            center_card_r * 2,
            center_card_r * 2,
        )

        painter.setBrush(QColor(18, 19, 24, 245))
        painter.setPen(QPen(QColor(255, 255, 255, 45), 1.5))
        painter.drawEllipse(card_rect)

        # Thumbnail or icon in center card
        thumb_top = center_y - 48.0
        if self.thumbnail_pixmap and not self.thumbnail_pixmap.isNull():
            tw = min(52, self.thumbnail_pixmap.width())
            th = min(52, self.thumbnail_pixmap.height())
            tx = center_x - (tw / 2.0)
            ty = thumb_top + (26.0 - th / 2.0)

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
            painter.setPen(QPen(QColor(255, 255, 255, 40), 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(tx, ty, tw, th), 8.0, 8.0)
        else:
            # File icon placeholder
            icon_rect = QRectF(center_x - 14.0, thumb_top + 4.0, 28.0, 36.0)
            painter.setPen(QPen(QColor(161, 161, 170, 200), 1.5))
            painter.setBrush(QColor(39, 39, 42, 180))
            painter.drawRoundedRect(icon_rect, 4.0, 4.0)

        # File name (elided)
        font_name = QFont()
        font_name.setPointSize(9)
        font_name.setBold(True)
        painter.setFont(font_name)
        painter.setPen(QColor(244, 244, 245, 240))

        fm = QFontMetrics(font_name)
        elided_name = fm.elidedText(
            self.file_name,
            Qt.TextElideMode.ElideMiddle,
            int(center_card_r * 2 - 16),
        )
        name_rect = QRectF(
            center_x - center_card_r + 8.0,
            center_y + 14.0,
            (center_card_r - 8.0) * 2,
            16.0,
        )
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignCenter, elided_name)

        # File size
        font_size = QFont()
        font_size.setPointSize(8)
        painter.setFont(font_size)
        painter.setPen(QColor(161, 161, 170, 220))
        size_rect = QRectF(
            center_x - center_card_r + 8.0,
            center_y + 32.0,
            (center_card_r - 8.0) * 2,
            16.0,
        )
        painter.drawText(size_rect, Qt.AlignmentFlag.AlignCenter, self.file_size_text)

        painter.end()
