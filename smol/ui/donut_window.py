"""PySide6 Donut Overlay Window.

A frameless, translucent, always-on-top radial menu centered at the cursor.
Renders 8 target size segments using DonutGeometry, liquid glass aesthetics,
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
    QBrush,
    QColor,
    QCursor,
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


class DonutWindow(QWidget):
    """Frameless translucent always-on-top donut menu centered on the cursor."""

    def __init__(
        self,
        files: Sequence[Path | str],
        size: int = 380,
        inner_radius: float = 75.0,
        outer_radius: float = 175.0,
        gap_angle: float = 0.0,
        on_select: Callable[[str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.file_paths = [Path(f) for f in files]
        self.overlay_size = size
        self.on_select = on_select
        self.selected_size: str | None = None

        self._hovered_idx: int | None = None
        self._blurred_desktop: QPixmap | None = None

        # Build DonutGeometry with equalized gaps
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
        """Configure Qt window flags, attributes, opacity, and tracking."""
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
        """Center on cursor, capture backdrop, show window, and execute event loop."""
        self.center_on_cursor()
        self.capture_desktop_background()
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

        # 1. Background blur: paint blurred snapshot of desktop behind the donut
        donut_clip = QPainterPath()
        donut_clip.addEllipse(outer_rect)

        painter.save()
        painter.setClipPath(donut_clip)
        if self._blurred_desktop and not self._blurred_desktop.isNull():
            painter.drawPixmap(0, 0, self._blurred_desktop)
        else:
            # Base dark translucent background if snapshot not available (e.g. headless)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(16, 17, 24, 220))
            painter.drawEllipse(outer_rect)
        painter.restore()

        # 2. Render each donut segment (tint, highlights, labels)
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

            # Segment Fill: semi-transparent dark tint over blurred background
            if not item.enabled:
                # Dimmed segment (larger than file): rgba(0, 0, 0, 120)
                fill_color = QColor(0, 0, 0, 120)
            elif is_hovered:
                # Brighten tint when hovered
                fill_color = QColor(35, 38, 52, 210)
            else:
                # Active segment fill: rgba(15, 15, 25, 180)
                fill_color = QColor(15, 15, 25, 180)

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

            # Edge light bend: thin arc highlight along the OUTER edge
            # of active segments
            if item.enabled:
                p_start = QPointF(
                    center_x + r_out * math.sin(math.radians(seg_geom.start_angle)),
                    center_y - r_out * math.cos(math.radians(seg_geom.start_angle)),
                )
                p_end = QPointF(
                    center_x + r_out * math.sin(math.radians(seg_geom.end_angle)),
                    center_y - r_out * math.cos(math.radians(seg_geom.end_angle)),
                )
                edge_grad = QLinearGradient(p_start, p_end)
                top_alpha = 100 if is_hovered else 60
                edge_grad.setColorAt(0.0, QColor(255, 255, 255, top_alpha))
                edge_grad.setColorAt(1.0, QColor(255, 255, 255, 0))

                path_outer = QPainterPath()
                path_outer.arcMoveTo(outer_rect, start_qt)
                path_outer.arcTo(outer_rect, start_qt, sweep_qt)

                painter.setPen(QPen(QBrush(edge_grad), 1.5))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path_outer)

            # Inner ring highlight: thin bright arc along the INNER circle edge
            path_inner = QPainterPath()
            path_inner.arcMoveTo(inner_rect, start_qt)
            path_inner.arcTo(inner_rect, start_qt, sweep_qt)
            painter.setPen(QPen(QColor(255, 255, 255, 40), 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path_inner)

            # Segment label:
            # Active labels: 100% full brightness white (equalized left/right)
            # Dimmed labels: 35% opacity
            font = QFont()
            font.setPointSize(10)
            font.setBold(True)
            painter.setFont(font)

            if item.enabled:
                label_color = QColor(255, 255, 255, 255)
            else:
                label_color = QColor(255, 255, 255, 89)  # 35% of 255

            painter.setPen(label_color)
            text_rect = QRectF(anchor.x() - 45.0, anchor.y() - 12.0, 90.0, 24.0)
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignCenter,
                item.label,
            )

        # 3. Segment separators: thin 1px line in rgba(255, 255, 255, 30)
        sep_pen = QPen(QColor(255, 255, 255, 30), 1.0)
        painter.setPen(sep_pen)
        for seg_geom in self.geometry_calc.segments:
            rad = math.radians(seg_geom.start_angle)
            x1 = center_x + r_in * math.sin(rad)
            y1 = center_y - r_in * math.cos(rad)
            x2 = center_x + r_out * math.sin(rad)
            y2 = center_y - r_out * math.cos(rad)
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # 4. Centre circle: frosted glass treatment
        center_card_r = r_in - 2.0
        card_rect = QRectF(
            center_x - center_card_r,
            center_y - center_card_r,
            center_card_r * 2,
            center_card_r * 2,
        )

        # Centre dark tint overlay
        painter.setBrush(QColor(15, 15, 25, 200))
        painter.setPen(QPen(QColor(255, 255, 255, 40), 1.2))
        painter.drawEllipse(card_rect)

        # Thumbnail with soft drop shadow
        thumb_top = center_y - 48.0
        if self.thumbnail_pixmap and not self.thumbnail_pixmap.isNull():
            tw = min(54, self.thumbnail_pixmap.width())
            th = min(54, self.thumbnail_pixmap.height())
            tx = center_x - (tw / 2.0)
            ty = thumb_top + (27.0 - th / 2.0)

            # Soft drop shadow behind thumbnail
            shadow_rect = QRectF(tx - 2.0, ty + 2.0, tw + 4.0, th + 4.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 110))
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
            icon_rect = QRectF(center_x - 14.0, thumb_top + 4.0, 28.0, 36.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 90))
            painter.drawRoundedRect(icon_rect.adjusted(-1, 2, 1, 2), 4.0, 4.0)

            painter.setPen(QPen(QColor(161, 161, 170, 220), 1.5))
            painter.setBrush(QColor(39, 39, 42, 200))
            painter.drawRoundedRect(icon_rect, 4.0, 4.0)

        # Filename: increased font size (10pt) and bold weight
        font_name = QFont()
        font_name.setPointSize(10)
        font_name.setBold(True)
        painter.setFont(font_name)
        painter.setPen(QColor(255, 255, 255, 250))

        fm = QFontMetrics(font_name)
        elided_name = fm.elidedText(
            self.file_name,
            Qt.TextElideMode.ElideMiddle,
            int(center_card_r * 2 - 16),
        )
        name_rect = QRectF(
            center_x - center_card_r + 8.0,
            center_y + 13.0,
            (center_card_r - 8.0) * 2,
            18.0,
        )
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignCenter, elided_name)

        # File size: increased font size (9pt) and demibold weight
        font_size = QFont()
        font_size.setPointSize(9)
        font_size.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font_size)
        painter.setPen(QColor(210, 215, 225, 240))
        size_rect = QRectF(
            center_x - center_card_r + 8.0,
            center_y + 32.0,
            (center_card_r - 8.0) * 2,
            18.0,
        )
        painter.drawText(size_rect, Qt.AlignmentFlag.AlignCenter, self.file_size_text)

        painter.end()
