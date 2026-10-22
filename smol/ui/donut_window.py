"""PySide6 Donut Overlay Window.

A frameless, translucent, always-on-top radial menu centered at the cursor.
Renders 8 target size segments using DonutGeometry, liquid glass aesthetics,
a center circular card with thumbnail, filename, and current file size.
Segments larger than the file are dimmed and unclickable.
Pressing Esc or clicking outside closes the overlay.
"""

from __future__ import annotations

import contextlib
import logging
import math
import os
import re
import shutil
import subprocess
import time
import urllib.parse
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from PIL import Image
from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QMimeData,
    QObject,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QThread,
    QTimer,
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

from smol.core.classify import BatchClassification, classify_files
from smol.core.config import get_reduce_motion
from smol.core.result import Result
from smol.core.size import format_size, parse_size
from smol.ui.custom_input import CustomInputDialog
from smol.ui.donut_geometry import DonutGeometry
from smol.ui.prediction import Prediction, PredictionService
from smol.ui.toast import ToastWindow
from smol.ui.worker import ClassificationWorker, ShrinkWorker

logger = logging.getLogger(__name__)
Image.init()

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


class FloorWorker(QThread):
    """Background worker estimating minimum achievable size using estimate_floor."""

    finished_floor = Signal(int, str)  # (floor_bytes, source)

    def __init__(
        self,
        file_path: Path | str,
        min_dim: int = 200,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.file_path = Path(file_path).resolve()
        self.min_dim = min_dim
        self._is_cancelled = False

    def cancel(self) -> None:
        self._is_cancelled = True

    def run(self) -> None:
        try:
            from PIL import Image

            Image.init()
            if self._is_cancelled:
                return

            from smol.core.suggest import estimate_floor

            est = estimate_floor(self.file_path, options={"min_dim": self.min_dim})
            if not self._is_cancelled:
                self.finished_floor.emit(est.bytes, est.source)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Error estimating floor for {self.file_path}: {exc}")


def build_segment_config(
    config_path: Path | str | None = None,
    original_bytes: int = 0,
    floor_bytes: int = 0,
    file_type: str = "image",
) -> list[tuple[str, int | None]]:
    """Build list of segment tuples from config using suggest_sizes.

    Returns up to 8 segments: at most 7 suggestion rungs + 1 Custom… fixed at end.
    """
    from smol.config import load_config
    from smol.core.suggest import SuggestOptions, suggest_sizes

    cfg = load_config(config_path)
    suggest_cfg = cfg.suggest
    sizes_cfg = cfg.sizes

    opts = SuggestOptions(
        mode=suggest_cfg.mode,
        ladder=tuple(sizes_cfg.ladder),
        pool=tuple(suggest_cfg.pool),
        pinned=tuple(sizes_cfg.pinned),
        recents=tuple(sizes_cfg.recents),
        max_segments=min(7, suggest_cfg.max_segments),
        min_dim=cfg.min_side,
    )

    orig_b = original_bytes if original_bytes > 0 else 100_000_000_000
    suggestions = suggest_sizes(
        original_bytes=orig_b,
        floor_bytes=floor_bytes,
        file_type=file_type,
        options=opts,
    )

    limited = suggestions[:7]
    result: list[tuple[str, int | None]] = [(s.label, s.bytes) for s in limited]
    result.append(("Custom…", None))
    return result


class SegmentItem(QObject):
    """A segment displayed in the donut."""

    def __init__(
        self,
        index: int,
        label: str,
        target_bytes: int | None,
        enabled: bool = True,
        clickable: bool = True,
        reason: str | None = None,
        reduce_motion: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.index = index
        self.label = label
        self.target_bytes = target_bytes
        self.enabled = enabled
        self.clickable = clickable
        self.reason = reason
        self.reduce_motion = reduce_motion
        self._hover_progress: float = 0.0
        self._hover_anim: QPropertyAnimation | None = None

    @Property(float)
    def hover_progress(self) -> float:
        return self._hover_progress

    @hover_progress.setter
    def hover_progress(self, val: float) -> None:
        self._hover_progress = max(0.0, min(1.0, float(val)))
        p = self.parent()
        if p is not None and hasattr(p, "update"):
            p.update()

    @property
    def hover_scale(self) -> float:
        if self.reduce_motion:
            return 1.0
        return 1.0 + (0.06 * self._hover_progress)


def _load_thumbnail_pixmap(path: Path, max_size: int = 70) -> QPixmap | None:
    """Load a thumbnail QPixmap from *path*, using Pillow or gs for PDF."""
    if not path.is_file():
        return None

    if path.suffix.lower() == ".pdf":
        gs_bin = shutil.which("gs")
        if gs_bin:
            try:
                res = subprocess.run(
                    [
                        gs_bin,
                        "-dSAFER",
                        "-dNOPAUSE",
                        "-dBATCH",
                        "-dQUIET",
                        "-sDEVICE=png16m",
                        "-dFirstPage=1",
                        "-dLastPage=1",
                        "-r72",
                        "-sOutputFile=-",
                        "-f",
                        str(path.resolve()),
                    ],
                    check=False,
                    capture_output=True,
                    timeout=2.0,
                )
                if res.returncode == 0 and res.stdout:
                    qimg = QImage.fromData(res.stdout)
                    if not qimg.isNull():
                        pix = QPixmap.fromImage(qimg)
                        return pix.scaled(
                            max_size,
                            max_size,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
            except (OSError, subprocess.TimeoutExpired):
                pass
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
    except Image.DecompressionBombError:
        return None
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


def parse_drop_uris(mime_data: QMimeData | object) -> list[Path]:
    """Extract existing local Path objects from drag-and-drop MIME data.

    Handles:
    - QUrl list from mime_data.urls()
    - text/uri-list from mime_data.data("text/uri-list") or mime_data.text()
    - file://localhost/ paths
    - percent-encoded characters (spaces, unicode, UTF-8 sequences)
    - multiple files across different folders
    - deduplication while preserving order and verifying file existence.
    """
    paths: list[Path] = []
    seen: set[Path] = set()

    def add_path(p: Path) -> None:
        try:
            resolved = p.resolve()
            if resolved.exists() and resolved not in seen:
                seen.add(resolved)
                paths.append(p)
        except (OSError, ValueError):
            pass

    def parse_uri_string(s: str) -> None:
        s = s.strip()
        if not s or s.startswith("#"):
            return
        if s.startswith("file://"):
            rest = s[7:]
            if rest.startswith(("localhost/", "localhost")):
                rest = rest[9:]
            unquoted = urllib.parse.unquote(rest, encoding="utf-8")
            add_path(Path(unquoted))
        elif os.path.isabs(s):
            add_path(Path(s))

    if hasattr(mime_data, "urls") and mime_data.urls():
        for url in mime_data.urls():
            if url.isLocalFile():
                add_path(Path(url.toLocalFile()))
            else:
                raw = url.toString()
                parse_uri_string(raw)

    raw_text = ""
    if hasattr(mime_data, "data"):
        raw_bytes = mime_data.data("text/uri-list")
        if raw_bytes and hasattr(raw_bytes, "data"):
            with contextlib.suppress(AttributeError, ValueError, TypeError, OSError):
                raw_text = bytes(raw_bytes.data()).decode("utf-8", errors="replace")
    if not raw_text and hasattr(mime_data, "text") and mime_data.text():
        raw_text = mime_data.text()

    if raw_text:
        for line in raw_text.splitlines():
            parse_uri_string(line)

    return paths


_active_shrink_workers: set[ShrinkWorker] = set()


class DonutWindow(QWidget):
    """Frameless translucent always-on-top donut menu centered on the cursor."""

    shrink_started = Signal(object)
    shrink_progress = Signal(int, int, str)
    shrink_finished = Signal(list)
    shrink_failed = Signal(str, object)
    drop_received = Signal(list)
    dismissed = Signal(str)
    step_progress_received = Signal(float, int)

    def __init__(
        self,
        files: Sequence[Path | str] | None = None,
        size: int = 380,
        inner_radius: float = 75.0,
        outer_radius: float = 175.0,
        gap_angle: float = 0.0,
        on_select: Callable[[str], None] | None = None,
        config_path: Path | str | None = None,
        reduce_motion: bool | None = None,
        parent: QWidget | None = None,
        file_paths: Sequence[Path | str] | None = None,
    ) -> None:
        super().__init__(parent)
        input_files = files if files is not None else (file_paths or [])
        self.file_paths = [Path(f) for f in input_files]
        self.overlay_size = size
        self.inner_radius = inner_radius
        self.outer_radius = outer_radius
        self.gap_angle = gap_angle
        self.on_select = on_select
        self.config_path = config_path
        if reduce_motion is not None:
            self.reduce_motion = bool(reduce_motion)
        else:
            self.reduce_motion = get_reduce_motion(self.config_path)

        self._open_scale: float = 1.0
        self._open_anim: QPropertyAnimation | None = None
        self._close_anim: QPropertyAnimation | None = None
        self._is_center_cancel_hovered: bool = False
        self._prediction_opacity: float = 0.0
        self._prediction_anim: QPropertyAnimation | None = None

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
        self._job_queue: list[tuple[int, list[Path]]] = []
        self._accumulated_results: list[tuple[Path, Result]] = []

        self._hovered_idx: int | None = None
        self._current_prediction: Prediction | None = None
        self._fading_prediction: Prediction | None = None
        self._hover_reason: str | None = None
        self._blurred_desktop: QPixmap | None = None

        # Floor estimation worker and attributes
        self._floor_bytes: int | None = None
        self._floor_source: str | None = None
        self.floor_worker: FloorWorker | None = None

        # Prediction service for hover estimation
        self.prediction_service = PredictionService(debounce_ms=150, parent=self)
        self.prediction_service.prediction_ready.connect(self._on_prediction_ready)
        self.prediction_service.prediction_cleared.connect(self._on_prediction_cleared)

        # File metadata and thumbnail
        self._init_file_data()

        # Drop and progress animation states
        self._chosen_segment_idx: int | None = None
        self._other_segments_opacity: float = 1.0
        self._anim_fade_others: QPropertyAnimation | None = None
        self._drop_transition: float = 0.0
        self._anim_transition: QPropertyAnimation | None = None
        self._ring_pulse: float = 0.0
        self._anim_pulse: QPropertyAnimation | None = None
        self._ring_progress: float = 0.0
        self._countdown_bytes: int = 0
        self._orig_size_bytes: int = 0
        self._shrink_start_time: float = 0.0
        self._is_fast_job: bool = False
        self._checkmark_burst: float = 0.0
        self._anim_checkmark_burst: QPropertyAnimation | None = None
        self._toast: ToastWindow | None = None
        self.last_skipped_files: list[Path] = []

        # Pre-drop classification state
        self.drag_classify_state: str | None = None
        self.center_classify_message: str | None = None
        self.all_segments_dimmed: bool = False
        self._current_classification: BatchClassification | None = None
        self._classification_worker: ClassificationWorker | None = None
        self._classify_timer: QTimer | None = None
        self._classify_timed_out: bool = False

        # Build segment items with dimming logic and geometry
        self._init_segments()

        # Setup window properties
        self._configure_window()

    @Property(float)
    def open_scale(self) -> float:
        """Scale factor (0.0 to 1.0) for opening fan-out animation."""
        return self._open_scale

    @open_scale.setter
    def open_scale(self, val: float) -> None:
        self._open_scale = max(0.0, min(1.0, float(val)))
        self.update()

    @Property(float)
    def prediction_opacity(self) -> float:
        """Opacity factor (0.0 to 1.0) for prediction label fade-in."""
        return self._prediction_opacity

    @prediction_opacity.setter
    def prediction_opacity(self, val: float) -> None:
        self._prediction_opacity = max(0.0, min(1.0, float(val)))
        self.update()

    @Property(float)
    def other_segments_opacity(self) -> float:
        """Opacity (0.0 to 1.0) of unselected segments during drop/working states."""
        return self._other_segments_opacity

    @other_segments_opacity.setter
    def other_segments_opacity(self, val: float) -> None:
        self._other_segments_opacity = max(0.0, min(1.0, float(val)))
        self.update()

    @Property(float)
    def drop_transition(self) -> float:
        """Transition progress (0.0 to 1.0) from segment arc to thumbnail ring."""
        return self._drop_transition

    @drop_transition.setter
    def drop_transition(self, val: float) -> None:
        self._drop_transition = max(0.0, min(1.0, float(val)))
        self.update()

    @Property(float)
    def ring_pulse(self) -> float:
        """Pulse scale intensity (0.0 to 1.0) when segment contracts into ring."""
        return self._ring_pulse

    @ring_pulse.setter
    def ring_pulse(self, val: float) -> None:
        self._ring_pulse = max(0.0, min(1.0, float(val)))
        self.update()

    @Property(float)
    def checkmark_burst(self) -> float:
        """Burst progression factor (0.0 to 1.0) for soft checkmark burst animation."""
        return self._checkmark_burst

    @checkmark_burst.setter
    def checkmark_burst(self, val: float) -> None:
        self._checkmark_burst = max(0.0, min(1.0, float(val)))
        self.update()

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
            self.file_name = "Drop on size"
            self.file_size_text = "Center cancels"
            self.thumbnail_pixmap = None
        elif len(self.file_paths) == 1:
            first = self.file_paths[0]
            clean_name = re.sub(r"[\r\n\x00-\x1f]", " ", first.name).strip()
            self.file_name = clean_name if clean_name else first.name
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
        """Initialize segment items and apply dimming logic via suggest_sizes."""
        file_type = "image"
        first = self._first_image_path()
        if first is not None and first.suffix.lower() == ".pdf":
            file_type = "pdf"

        from smol.config import load_config
        from smol.core.suggest import SuggestOptions, suggest_sizes

        cfg = load_config(self.config_path)
        suggest_cfg = cfg.suggest
        sizes_cfg = cfg.sizes

        opts = SuggestOptions(
            mode=suggest_cfg.mode,
            ladder=tuple(sizes_cfg.ladder),
            pool=tuple(suggest_cfg.pool),
            pinned=tuple(sizes_cfg.pinned),
            recents=tuple(sizes_cfg.recents),
            max_segments=min(7, suggest_cfg.max_segments),
            min_dim=cfg.min_side,
        )

        orig_b = self.max_file_bytes if self.max_file_bytes > 0 else 100_000_000_000
        floor_b = self._floor_bytes or 0

        suggestions = suggest_sizes(
            original_bytes=orig_b,
            floor_bytes=floor_b,
            file_type=file_type,
            options=opts,
        )

        limited = suggestions[:7]
        self.segments_config = [(s.label, s.bytes) for s in limited] + [
            ("Custom…", None)
        ]
        self.geometry_calc = DonutGeometry(
            n_segments=len(self.segments_config),
            inner_radius=self.inner_radius,
            outer_radius=self.outer_radius,
            gap_angle=self.gap_angle,
        )
        self.segments: list[SegmentItem] = []
        for idx, s in enumerate(limited):
            if not self.file_paths or self.max_file_bytes == 0:
                enabled = True
                clickable = True
                reason = None
            else:
                enabled = s.eligible
                reason = s.reason
                if reason == "larger than the file":
                    clickable = False
                elif (reason and "too small for this file" in reason) or s.eligible:
                    clickable = True
                else:
                    clickable = False

            self.segments.append(
                SegmentItem(
                    index=idx,
                    label=s.label,
                    target_bytes=s.bytes,
                    enabled=enabled,
                    clickable=clickable,
                    reason=reason,
                    reduce_motion=self.reduce_motion,
                    parent=self,
                )
            )

        # Append "Custom…" as the fixed last segment
        self.segments.append(
            SegmentItem(
                index=len(self.segments),
                label="Custom…",
                target_bytes=None,
                enabled=True,
                clickable=True,
                reason=None,
                reduce_motion=self.reduce_motion,
                parent=self,
            )
        )

    def _start_floor_worker(self) -> None:
        """Estimate lowest achievable size in background without UI freeze."""
        if self.floor_worker is not None and self.floor_worker.isRunning():
            return

        first_file = self._first_image_path()
        if (
            first_file is not None
            and first_file.is_file()
            and first_file.stat().st_size > 0
        ):
            from smol.config import load_config

            cfg = load_config(self.config_path)
            self.floor_worker = FloorWorker(
                first_file, min_dim=cfg.min_side, parent=self
            )
            self.floor_worker.finished_floor.connect(self._on_floor_estimated)
            self.floor_worker.start()

    def _on_floor_estimated(self, floor_bytes: int, source: str) -> None:
        """Handle floor estimation results from worker thread."""
        self._floor_bytes = floor_bytes
        self._floor_source = source
        self._update_segment_dimming()

    def _update_segment_dimming(self) -> None:
        """Update segment dimming when floor estimation completes."""
        from smol.config import load_config

        cfg = load_config(self.config_path)
        if cfg.suggest.mode == "smart":
            self._init_segments()
        else:
            floor_b = self._floor_bytes or 0
            for seg in self.segments:
                if seg.target_bytes is None:
                    continue
                if self.max_file_bytes > 0 and seg.target_bytes > self.max_file_bytes:
                    seg.enabled = False
                    seg.clickable = False
                    seg.reason = "larger than the file"
                elif floor_b > 0 and seg.target_bytes < floor_b:
                    seg.enabled = False
                    seg.clickable = True
                    formatted = format_size(floor_b, spaced=True)
                    seg.reason = f"too small for this file (min about {formatted})"
                else:
                    seg.enabled = True
                    seg.clickable = True
                    seg.reason = None
        self.update()

    @property
    def is_already_small(self) -> bool:
        """True if all predefined target sizes are larger than the input file."""
        size_segs = [s for s in self.segments if s.target_bytes is not None]
        return bool(
            size_segs and all(s.reason == "larger than the file" for s in size_segs)
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

    def reload_config(self, config_path: Path | str | None = None) -> None:
        """Reload configuration from disk and re-initialize segment geometry."""
        if config_path is not None:
            self.config_path = config_path
        self.reduce_motion = get_reduce_motion(self.config_path)
        self._init_segments()
        self.update()

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

    def center_at(self, x: int, y: int) -> None:
        """Position overlay centered on the given coordinates with screen clamping."""
        screen = QApplication.screenAt(QPoint(x, y)) or QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            if geo.height() <= 720 and self.overlay_size == 380:
                self.adapt_compact_size(340, 68.0, 156.0)

            w = self.width()
            h = self.height()
            target_x = x - (w // 2)
            target_y = y - (h // 2)

            margin = 8
            target_x = max(geo.left() + margin, min(target_x, geo.right() - w - margin))
            target_y = max(geo.top() + margin, min(target_y, geo.bottom() - h - margin))
            self.move(target_x, target_y)
        else:
            w = self.width()
            h = self.height()
            self.move(x - (w // 2), y - (h // 2))

    def center_on_screen(self) -> None:
        """Position overlay centered on the screen (Path C)."""
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            if geo.height() <= 720 and self.overlay_size == 380:
                self.adapt_compact_size(340, 68.0, 156.0)
            w = self.width()
            h = self.height()
            self.move(geo.center().x() - (w // 2), geo.center().y() - (h // 2))

    @property
    def job_queue(self) -> list[tuple[int, list[Path]]]:
        """Return the current list of queued jobs."""
        return self._job_queue

    def showEvent(self, event: object) -> None:
        """Trigger open fan-out animation and start floor estimation."""
        super().showEvent(event)
        self.start_open_animation()
        self._start_floor_worker()

    def start_open_animation(self) -> None:
        """Start 120 ms OutCubic scale from centre (instant if reduce_motion)."""
        if self._close_anim is not None and self._close_anim.state():
            self._close_anim.stop()

        if self.reduce_motion:
            self._open_scale = 1.0
            if self._open_anim is not None and self._open_anim.state():
                self._open_anim.stop()
            self.update()
            return

        if self._open_anim is not None and self._open_anim.state():
            self._open_anim.stop()

        self._open_scale = 0.0
        anim = QPropertyAnimation(self, b"open_scale", self)
        anim.setDuration(120)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._open_anim = anim
        anim.start()

    def start_close_animation(
        self, on_finished: Callable[[], None] | None = None
    ) -> None:
        """Start 120 ms InCubic scale down to centre and fade out."""
        if self._open_anim is not None and self._open_anim.state():
            self._open_anim.stop()

        if self.reduce_motion or not self.isVisible():
            self._open_scale = 0.0
            if self._close_anim is not None and self._close_anim.state():
                self._close_anim.stop()
            self.hide()
            if on_finished is not None:
                on_finished()
            return

        if self._close_anim is not None and self._close_anim.state():
            return

        anim = QPropertyAnimation(self, b"open_scale", self)
        anim.setDuration(120)
        anim.setStartValue(self._open_scale)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)

        def _on_done() -> None:
            self.hide()
            self._open_scale = 1.0
            if on_finished is not None:
                on_finished()

        anim.finished.connect(_on_done)
        self._close_anim = anim
        anim.start()

    def dismiss_animated(
        self, reason: str, on_finished: Callable[[], None] | None = None
    ) -> None:
        """Emit dismissed signal and play smooth close animation."""
        self.dismissed.emit(reason)
        self.start_close_animation(on_finished)

    def _segment_at(self, dx: float, dy: float) -> int | None:
        """Find segment index at (dx, dy), accounting for 6% hover expansion."""
        idx = self.geometry_calc.segment_at(dx, dy)
        if idx is not None:
            return idx
        if self._hovered_idx is not None and 0 <= self._hovered_idx < len(
            self.segments
        ):
            seg = self.segments[self._hovered_idx]
            if seg.hover_scale > 1.0:
                expanded_r_out = self.geometry_calc.outer_radius * seg.hover_scale
                r = math.hypot(dx, dy)
                if self.geometry_calc.inner_radius <= r <= expanded_r_out + 1.0:
                    theta = math.degrees(math.atan2(dx, -dy)) % 360.0
                    slot_idx = int(theta // self.geometry_calc.slot_angle)
                    if slot_idx == self._hovered_idx:
                        return self._hovered_idx
        return None

    def _animate_segment_hover(self, seg: SegmentItem, target_val: float) -> None:
        """Animate segment hover_progress smoothly towards target_val."""
        if self.reduce_motion:
            seg.hover_progress = target_val
            return

        if seg._hover_anim is not None and seg._hover_anim.state():
            seg._hover_anim.stop()

        anim = QPropertyAnimation(seg, b"hover_progress", self)
        anim.setDuration(100)
        anim.setStartValue(seg.hover_progress)
        anim.setEndValue(target_val)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        seg._hover_anim = anim
        anim.start()

    def _set_hovered_segment(self, new_idx: int | None) -> None:
        """Transition hovered segment, animating hover scale and brightening."""
        if new_idx == self._hovered_idx:
            return

        self._hovered_idx = new_idx
        for idx, seg in enumerate(self.segments):
            is_active = seg.enabled or getattr(seg, "clickable", False)
            target_val = 1.0 if (idx == new_idx and is_active) else 0.0
            anim_active = seg._hover_anim is not None and seg._hover_anim.state()
            if seg.hover_progress != target_val or anim_active:
                if self.reduce_motion:
                    seg.hover_progress = target_val
                else:
                    self._animate_segment_hover(seg, target_val)

    def _animate_prediction_opacity(self, target_val: float) -> None:
        """Animate prediction_opacity smoothly towards target_val."""
        if target_val <= 0.0:
            self._fading_prediction = (
                self._current_prediction or self._fading_prediction
            )
            self._current_prediction = None

        if self.reduce_motion:
            self.prediction_opacity = target_val
            self._fading_prediction = None
            self.update()
            return

        if self._prediction_anim is not None and self._prediction_anim.state():
            self._prediction_anim.stop()

        anim = QPropertyAnimation(self, b"prediction_opacity", self)
        anim.setDuration(120)
        anim.setStartValue(self.prediction_opacity)
        anim.setEndValue(target_val)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        if target_val <= 0.0:

            def on_fade_out_finished() -> None:
                if self.prediction_opacity <= 0.0:
                    self._fading_prediction = None
                    self.update()

            anim.finished.connect(on_fade_out_finished)
        self._prediction_anim = anim
        anim.start()

    def _start_drop_animation(self) -> None:
        """Trigger other segments fade out and pulse chosen segment into ring."""
        if self.reduce_motion:
            self.other_segments_opacity = 0.0
            self.drop_transition = 1.0
            self.ring_pulse = 0.0
            self.update()
            return

        # 1. Fade out other segments (160 ms)
        if self._anim_fade_others is not None and self._anim_fade_others.state():
            self._anim_fade_others.stop()
        self._anim_fade_others = QPropertyAnimation(
            self, b"other_segments_opacity", self
        )
        self._anim_fade_others.setDuration(160)
        self._anim_fade_others.setStartValue(self.other_segments_opacity)
        self._anim_fade_others.setEndValue(0.0)
        self._anim_fade_others.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_fade_others.start()

        # 2. Chosen segment contracts into thumbnail ring (200 ms)
        if self._anim_transition is not None and self._anim_transition.state():
            self._anim_transition.stop()
        self._anim_transition = QPropertyAnimation(self, b"drop_transition", self)
        self._anim_transition.setDuration(200)
        self._anim_transition.setStartValue(self.drop_transition)
        self._anim_transition.setEndValue(1.0)
        self._anim_transition.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_transition.start()

        # 3. Pulse ring around thumbnail (240 ms)
        if self._anim_pulse is not None and self._anim_pulse.state():
            self._anim_pulse.stop()
        self._anim_pulse = QPropertyAnimation(self, b"ring_pulse", self)
        self._anim_pulse.setDuration(240)
        self._anim_pulse.setKeyValueAt(0.0, 0.0)
        self._anim_pulse.setKeyValueAt(0.5, 1.0)
        self._anim_pulse.setKeyValueAt(1.0, 0.0)
        self._anim_pulse.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._anim_pulse.start()

    def reset_state(self) -> None:
        """Reset overlay to fresh idle state ready for a new summon or drop."""
        if self._shrink_worker is not None and self._shrink_worker.isRunning():
            self._shrink_worker.cancel()
            self._shrink_worker.wait(200)
            self._shrink_worker = None
        if self._open_anim is not None and self._open_anim.state():
            self._open_anim.stop()
        if self._close_anim is not None and self._close_anim.state():
            self._close_anim.stop()
        self._open_scale = 1.0
        self._is_center_cancel_hovered = False
        if self._prediction_anim is not None and self._prediction_anim.state():
            self._prediction_anim.stop()
        if self._anim_fade_others is not None and self._anim_fade_others.state():
            self._anim_fade_others.stop()
        if self._anim_transition is not None and self._anim_transition.state():
            self._anim_transition.stop()
        if self._anim_pulse is not None and self._anim_pulse.state():
            self._anim_pulse.stop()
        if (
            self._anim_checkmark_burst is not None
            and self._anim_checkmark_burst.state()
        ):
            self._anim_checkmark_burst.stop()
        self._checkmark_burst = 0.0
        if self._toast is not None:
            self._toast.close()
            self._toast = None
        for seg in getattr(self, "segments", []):
            if seg._hover_anim is not None and seg._hover_anim.state():
                seg._hover_anim.stop()
        self._job_queue.clear()
        self._accumulated_results.clear()
        self._chosen_segment_idx = None
        self._other_segments_opacity = 1.0
        self._drop_transition = 0.0
        self._ring_pulse = 0.0
        self._ring_progress = 0.0
        self._countdown_bytes = 0
        self._orig_size_bytes = 0
        self._is_fast_job = False
        self.state = "idle"
        self.center_status_text = ""
        self.result_message = None
        self.last_results = None
        self.failure_error = None
        self.retry_target_bytes = None
        self._retry_rect = None
        self._hovered_idx = None
        self._fading_prediction = None
        self._prediction_opacity = 0.0
        if (
            self._classification_worker is not None
            and self._classification_worker.isRunning()
        ):
            self._classification_worker.cancel()
            self._classification_worker.wait(100)
            self._classification_worker = None
        if self._classify_timer is not None and self._classify_timer.isActive():
            self._classify_timer.stop()
        self.drag_classify_state = None
        self.center_classify_message = None
        self.all_segments_dimmed = False
        self.last_skipped_files = []
        self._current_classification = None
        self._classify_timed_out = False
        self.file_paths = []
        self._init_file_data()
        self._init_segments()
        if self.isVisible():
            self.start_open_animation()
        else:
            self.update()

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
        """Esc key dismisses the overlay and cancels any active compression worker."""
        if event.key() == Qt.Key.Key_Escape:
            if self._shrink_worker is not None and self._shrink_worker.isRunning():
                self._shrink_worker.cancel()
            if self._custom_dialog is not None and self._custom_dialog.isVisible():
                self._custom_dialog.close()
            self.dismissed.emit("esc")
            self.close()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _open_custom_dialog(self, pos: QPointF | QPoint | None = None) -> None:
        """Open tiny custom input dialog near the cursor or segment."""
        if self._custom_dialog is not None and self._custom_dialog.isVisible():
            self._custom_dialog.close()

        self._custom_dialog = CustomInputDialog(
            parent=self,
            floor_bytes=self._floor_bytes,
            config_path=self.config_path,
        )
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
        from smol.config import add_recent_size

        add_recent_size(target_bytes, self.config_path)

        files = list(self._pending_custom_files) if self._pending_custom_files else None
        self._pending_custom_files = []

        if files:
            self.file_paths = files
            self._init_file_data()

        self._init_segments()
        for i, s in enumerate(self.segments):
            if s.target_bytes == target_bytes:
                self._chosen_segment_idx = i
                break
        self.update()

        self.queue_or_start_shrink(target_bytes, files=files)

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
                self._animate_prediction_opacity(1.0)

    def _on_prediction_cleared(self) -> None:
        """Clear current prediction text with smooth fade-out."""
        self._animate_prediction_opacity(0.0)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Update hover state on segments and trigger debounced prediction."""
        if self.state == "working":
            event.accept()
            return

        center = self.rect().center()
        pos = event.position() if hasattr(event, "position") else event.pos()
        dx = pos.x() - center.x()
        dy = pos.y() - center.y()

        idx = self._segment_at(dx, dy)
        if idx != self._hovered_idx:
            self._set_hovered_segment(idx)
            if idx is None:
                self._hover_reason = None
                self.prediction_service.cancel()
                self._animate_prediction_opacity(0.0)
            else:
                item = self.segments[idx]
                if not item.enabled:
                    self.prediction_service.cancel()
                    if item.reason:
                        self._hover_reason = item.reason
                        self.setToolTip(item.reason)
                        self._animate_prediction_opacity(1.0)
                    else:
                        self._hover_reason = None
                        self.setToolTip("")
                        self._animate_prediction_opacity(0.0)
                elif item.target_bytes is None or self.state != "idle":
                    self._hover_reason = None
                    self.setToolTip("")
                    self.prediction_service.cancel()
                    self._animate_prediction_opacity(0.0)
                else:
                    self._hover_reason = None
                    self.setToolTip("")
                    first_file = self._first_image_path()
                    if first_file is not None:
                        self.prediction_service.request(first_file, item.target_bytes)
        event.accept()

    def leaveEvent(self, event: object) -> None:
        """Clear hover state and cancel pending predictions when mouse leaves window."""
        self.setToolTip("")
        if self._hovered_idx is not None:
            self._set_hovered_segment(None)
            self._hover_reason = None
            self.prediction_service.cancel()
            self._animate_prediction_opacity(0.0)

    def closeEvent(self, event: object) -> None:
        """Clean up background workers, animations, and child dialogs on close."""
        if self._open_anim is not None and self._open_anim.state():
            self._open_anim.stop()
        if self._prediction_anim is not None and self._prediction_anim.state():
            self._prediction_anim.stop()
        for seg in getattr(self, "segments", []):
            if seg._hover_anim is not None and seg._hover_anim.state():
                seg._hover_anim.stop()

        if self.floor_worker is not None and self.floor_worker.isRunning():
            self.floor_worker.cancel()
            self.floor_worker.quit()
            self.floor_worker.wait(1000)

        if self._custom_dialog is not None and self._custom_dialog.isVisible():
            self._custom_dialog.close()
        self.prediction_service.cancel()
        self.prediction_service.wait_for_workers(timeout_ms=300)
        if self._shrink_worker is not None and self._shrink_worker.isRunning():
            self._shrink_worker.cancel()
            self._shrink_worker.wait(300)
        if (
            self._classification_worker is not None
            and self._classification_worker.isRunning()
        ):
            self._classification_worker.cancel()
            self._classification_worker.wait(300)
        super().closeEvent(event)
        self.dismissed.emit("closed")

    def hideEvent(self, event: object) -> None:
        """Emit dismissed signal when overlay is hidden."""
        super().hideEvent(event)
        self.dismissed.emit("hidden")

    def __del__(self) -> None:
        try:
            worker = getattr(self, "floor_worker", None)
            if worker is not None and worker.isRunning():
                worker.cancel()
                worker.wait(500)
            class_worker = getattr(self, "_classification_worker", None)
            if class_worker is not None and class_worker.isRunning():
                class_worker.cancel()
                class_worker.wait(500)
        except (RuntimeError, AttributeError):
            pass

    def _parse_drop_uris(self, mime_data: QMimeData | object) -> list[Path]:
        """Extract existing local Path objects from drag-and-drop MIME data."""
        return parse_drop_uris(mime_data)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept drag and trigger pre-drop classification (300 ms timeout)."""
        mime = event.mimeData()
        if not (mime.hasUrls() or mime.hasFormat("text/uri-list")):
            event.ignore()
            return

        event.acceptProposedAction()

        # Extract dragged paths/URIs
        paths: list[str] = []
        if mime.hasUrls():
            for u in mime.urls():
                if u.isLocalFile():
                    paths.append(u.toLocalFile())
                else:
                    paths.append(u.toString())
        elif mime.hasFormat("text/uri-list") or mime.hasText():
            paths = [str(p) for p in self._parse_drop_uris(mime)]

        if not paths:
            # URLs not yet available (e.g. Archive Manager), show neutral Checking...
            self.drag_classify_state = "unknown"
            self.center_classify_message = "Checking..."
            self.all_segments_dimmed = False
            self.update()
            return

        # Cancel any previous classification worker or timer
        if self._classification_worker and self._classification_worker.isRunning():
            self._classification_worker.cancel()
            self._classification_worker.wait(100)
            self._classification_worker = None
        if self._classify_timer and self._classify_timer.isActive():
            self._classify_timer.stop()

        self._classify_timed_out = False
        self._current_classification = None
        self.drag_classify_state = "unknown"
        self.center_classify_message = "Checking..."
        self.all_segments_dimmed = False
        self.update()

        # 300 ms timeout timer
        self._classify_timer = QTimer(self)
        self._classify_timer.setSingleShot(True)
        self._classify_timer.setInterval(300)
        self._classify_timer.timeout.connect(self._on_classify_timeout)
        self._classify_timer.start()

        # Background worker thread
        self._classification_worker = ClassificationWorker(paths, parent=self)
        self._classification_worker.classified.connect(self._on_classified)
        self._classification_worker.start()

    def _on_classify_timeout(self) -> None:
        """Handle 300 ms classification timeout: enter neutral 'Checking...' state."""
        if self._current_classification is None:
            self._classify_timed_out = True
            self.drag_classify_state = "unknown"
            self.center_classify_message = "Checking..."
            self.all_segments_dimmed = False
            self.update()

    def _on_classified(self, batch: BatchClassification) -> None:
        """Receive classification batch results and update pre-drop states."""
        if self._classify_timer and self._classify_timer.isActive():
            self._classify_timer.stop()

        self._current_classification = batch
        if self._classify_timed_out:
            return

        if batch.none_supported:
            self.drag_classify_state = "none_supported"
            first = batch.items[0] if batch.items else None
            self.center_classify_message = (
                first.reason if first and first.reason else "Unsupported file type"
            )
            self.all_segments_dimmed = True
        elif batch.mixed:
            self.drag_classify_state = "mixed"
            sup_cnt = len(batch.supported_items)
            skip_cnt = len(batch.unsupported_items)
            tot_cnt = batch.total_count
            self.center_classify_message = (
                f"{sup_cnt} of {tot_cnt} supported, {skip_cnt} will be skipped"
            )
            self.all_segments_dimmed = False
        elif batch.has_unknown:
            self.drag_classify_state = "unknown"
            self.center_classify_message = "Checking..."
            self.all_segments_dimmed = False
        else:
            self.drag_classify_state = "all_supported"
            self.center_classify_message = None
            self.all_segments_dimmed = False

        self.update()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        """Track segment under cursor during drag, rejecting when none supported."""
        center = self.rect().center()
        pos = event.position() if hasattr(event, "position") else event.pos()
        dx = pos.x() - center.x()
        dy = pos.y() - center.y()
        r = math.hypot(dx, dy)
        idx = self._segment_at(dx, dy)

        is_center = r <= self.geometry_calc.inner_radius
        if is_center != self._is_center_cancel_hovered:
            self._is_center_cancel_hovered = is_center
            self.update()

        if self.drag_classify_state == "none_supported":
            if idx is not None:
                self.setCursor(Qt.CursorShape.ForbiddenCursor)
            else:
                self.unsetCursor()
            event.ignore()
            return

        self.unsetCursor()
        if is_center:
            if self._hovered_idx is not None:
                self._set_hovered_segment(None)
        elif idx != self._hovered_idx:
            self._set_hovered_segment(idx)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        """Clear drag hover state and restore default classification state."""
        self.unsetCursor()
        self._set_hovered_segment(None)
        if self._is_center_cancel_hovered:
            self._is_center_cancel_hovered = False
            self.update()
        if self.state != "working":
            self.drag_classify_state = None
            self.center_classify_message = None
            self.all_segments_dimmed = False
            self.update()
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        """Handle file drops onto a donut segment with pre-drop filtering."""
        center = self.rect().center()
        pos = event.position() if hasattr(event, "position") else event.pos()
        dx = pos.x() - center.x()
        dy = pos.y() - center.y()
        r = math.hypot(dx, dy)

        # Dropping into center hole cancels upload!
        if r <= self.geometry_calc.inner_radius:
            self._is_center_cancel_hovered = False
            self.update()
            event.acceptProposedAction()
            self.dismiss_animated("centre_cancel")
            return

        if self.drag_classify_state == "none_supported":
            event.ignore()
            return

        idx = self._segment_at(dx, dy)

        dropped_files = self._parse_drop_uris(event.mimeData())
        if not dropped_files:
            event.ignore()
            return

        # If classification wasn't available at dragEnter or timed out:
        if (
            self._current_classification is None
            or self.drag_classify_state == "unknown"
        ):
            batch = classify_files([str(p) for p in dropped_files])
            self._current_classification = batch

        if self._current_classification is not None:
            if self._current_classification.none_supported:
                self.drag_classify_state = "none_supported"
                first = (
                    self._current_classification.items[0]
                    if self._current_classification.items
                    else None
                )
                self.center_classify_message = (
                    first.reason if first and first.reason else "Unsupported file type"
                )
                self.all_segments_dimmed = True
                self.update()
                event.ignore()
                return

            if (
                self._current_classification.mixed
                or self.drag_classify_state == "mixed"
            ):
                supported_files = [
                    Path(c.path) for c in self._current_classification.supported_items
                ]
                self.last_skipped_files = [
                    Path(c.path) for c in self._current_classification.unsupported_items
                ]
                dropped_files = supported_files
            else:
                self.last_skipped_files = []

        if idx is not None:
            item = self.segments[idx]
            if not getattr(item, "clickable", item.enabled) or self.all_segments_dimmed:
                event.ignore()
                return

            self.drop_received.emit(dropped_files)
            self._chosen_segment_idx = idx
            if item.target_bytes is not None:
                event.acceptProposedAction()
                self.selected_size = item.label
                if self.on_select:
                    self.on_select(item.label)
                self.queue_or_start_shrink(item.target_bytes, files=dropped_files)
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

    def queue_or_start_shrink(
        self,
        target_bytes: int,
        files: Sequence[Path | str] | None = None,
    ) -> None:
        """Start shrinking or enqueue if a job is currently working."""
        path_list = (
            [Path(f) for f in files] if files is not None else list(self.file_paths)
        )
        if not path_list:
            return

        if self.state == "working":
            self._job_queue.append((target_bytes, path_list))
            queued_count = len(self._job_queue)
            base_status = self.center_status_text.split(" (+")[0]
            self.center_status_text = f"{base_status} (+{queued_count} queued)"
            self.update()
            return

        self._accumulated_results = []
        self.start_shrink(target_bytes, files=path_list)

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
        self._shrink_start_time = time.monotonic()
        self._is_fast_job = False
        self._ring_progress = 0.0

        if self.file_paths and self.file_paths[0].exists():
            self._orig_size_bytes = self.file_paths[0].stat().st_size
        else:
            self._orig_size_bytes = 0
        self._countdown_bytes = self._orig_size_bytes

        if self._chosen_segment_idx is None:
            for i, seg in enumerate(self.segments):
                if seg.target_bytes == target_bytes:
                    self._chosen_segment_idx = i
                    break

        if len(self.file_paths) > 1:
            self.center_status_text = f"Shrinking (1/{len(self.file_paths)})..."
        else:
            self.center_status_text = "Shrinking..."

        self.result_message = None
        self.failure_error = None
        self.retry_target_bytes = None
        self._retry_rect = None

        self._start_drop_animation()
        self.shrink_started.emit(target_bytes)

        from smol.config import load_config

        cfg = load_config(self.config_path)
        options: dict[str, Any] = {
            "strip_metadata": cfg.strip_metadata,
            "allow_convert": cfg.allow_convert,
            "min_dim": cfg.min_side,
        }
        if cfg.output_mode == "fixed folder" and cfg.output_folder:
            options["out_dir"] = cfg.output_folder

        worker = ShrinkWorker(
            files=self.file_paths,
            target_bytes=target_bytes,
            options=options,
            parent=None,
        )
        self._shrink_worker = worker
        _active_shrink_workers.add(worker)
        worker.finished.connect(lambda: _active_shrink_workers.discard(worker))
        worker.progress.connect(self._on_shrink_progress)
        worker.step_progress.connect(self._on_step_progress)
        worker.results_ready.connect(self._on_shrink_finished)
        worker.start()
        self.update()

    def _on_step_progress(self, progress: float, current_bytes: int) -> None:
        """Handle real intermediate engine steps from compression worker."""
        if self.state == "working":
            self._ring_progress = max(self._ring_progress, float(progress))
            if current_bytes > 0:
                self._countdown_bytes = current_bytes
            self.step_progress_received.emit(float(progress), int(current_bytes))
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
        """Find the first likely image or PDF file in self.file_paths for prediction."""
        for p in self.file_paths:
            if not p.is_file():
                continue
            if p.suffix.lower() in (
                ".jpg",
                ".jpeg",
                ".png",
                ".webp",
                ".heic",
                ".heif",
                ".avif",
                ".pdf",
            ):
                return p

        return self.file_paths[0] if self.file_paths else None

    def _on_shrink_finished(self, results: list[tuple[Path, Result]]) -> None:
        """Handle completion of background shrink job."""
        if self._job_queue:
            self._accumulated_results.extend(results)
            next_target, next_files = self._job_queue.pop(0)
            self.file_paths = next_files
            self._init_file_data()
            self._init_segments()
            self.state = "idle"
            self.start_shrink(next_target, files=next_files)
            if self._job_queue:
                queued_count = len(self._job_queue)
                base_status = self.center_status_text.split(" (+")[0]
                self.center_status_text = f"{base_status} (+{queued_count} queued)"
                self.update()
            return

        all_results = self._accumulated_results + results
        self._accumulated_results = []
        results = all_results
        self.last_results = results

        shrunk_items = [
            (p, r) for p, r in results if r.ok and r.output_path is not None
        ]
        small_items = [(p, r) for p, r in results if r.ok and r.output_path is None]
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

        elapsed_ms = (time.monotonic() - self._shrink_start_time) * 1000.0
        if elapsed_ms < 300.0:
            self._is_fast_job = True
            # Job took under 300 ms: skip straight to done — no fake progress
            if self._anim_fade_others is not None and self._anim_fade_others.state():
                self._anim_fade_others.stop()
            if self._anim_transition is not None and self._anim_transition.state():
                self._anim_transition.stop()
            if self._anim_pulse is not None and self._anim_pulse.state():
                self._anim_pulse.stop()
            self._other_segments_opacity = 0.0
            self._drop_transition = 1.0
            self._ring_pulse = 0.0
            self._ring_progress = 1.0
        else:
            self._ring_progress = 1.0

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
                    self.result_message = f"{orig_sz} → ✓ {final_sz}"
                    if res.final_bytes > 0:
                        self._countdown_bytes = res.final_bytes
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
            self._start_completion_sequence(results)

        self.update()

    def _start_completion_sequence(self, results: list[tuple[Path, Result]]) -> None:
        """Execute ring snap shut -> soft checkmark burst (~600 ms)
        -> toast slide in.
        """
        self._ring_progress = 1.0  # Ring snaps shut
        if self.reduce_motion:
            self._checkmark_burst = 1.0
            self.update()
            self._show_completion_toast(results)
            return

        self._checkmark_burst = 0.0
        if (
            self._anim_checkmark_burst is not None
            and self._anim_checkmark_burst.state()
        ):
            self._anim_checkmark_burst.stop()

        self._anim_checkmark_burst = QPropertyAnimation(self, b"checkmark_burst", self)
        self._anim_checkmark_burst.setDuration(600)
        self._anim_checkmark_burst.setStartValue(0.0)
        self._anim_checkmark_burst.setEndValue(1.0)
        self._anim_checkmark_burst.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_checkmark_burst.finished.connect(
            lambda: self._show_completion_toast(results)
        )
        self._anim_checkmark_burst.start()

    def _build_completion_toast(
        self, results: list[tuple[Path, Result]]
    ) -> ToastWindow:
        """Construct completion toast instance with results and skipped files."""
        cursor_pos = QCursor.pos()
        return ToastWindow(
            results=results,
            cursor_pos=cursor_pos,
            reduce_motion=self.reduce_motion,
            skipped_files=self.last_skipped_files,
        )

    def _show_completion_toast(self, results: list[tuple[Path, Result]]) -> None:
        """Summon completion toast near cursor/corner and hide donut window."""
        if self.state != "success":
            return

        toast = self._build_completion_toast(results)
        self._toast = toast
        toast.show()
        toast.raise_()
        toast.dismissed.connect(self.close)
        self.hide()

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
            if r > self.geometry_calc.outer_radius * 1.06:
                self.dismissed.emit("outside")
                self.close()
                event.accept()
                return
            idx = self._segment_at(dx, dy)
            if idx is not None:
                item = self.segments[idx]
                if getattr(item, "clickable", item.enabled):
                    self._chosen_segment_idx = idx
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
            if r > self.geometry_calc.outer_radius * 1.06:
                self.dismissed.emit("outside")
                self.close()
                event.accept()
                return
            idx = self._segment_at(dx, dy)
            if idx is not None:
                item = self.segments[idx]
                if getattr(item, "clickable", item.enabled):
                    self._chosen_segment_idx = idx
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
        if r <= self.geometry_calc.inner_radius:
            self.dismiss_animated("centre_cancel")
            event.accept()
            return

        idx = self._segment_at(dx, dy)
        if idx is None:
            if r > self.geometry_calc.outer_radius * 1.06:
                self.dismissed.emit("outside")
                self.close()
                event.accept()
                return
            return

        item = self.segments[idx]
        if not getattr(item, "clickable", item.enabled):
            return

        self.selected_size = item.label
        if self.on_select:
            self.on_select(item.label)

        self._chosen_segment_idx = idx
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

        # Open/close animation fan-out scale and fade from centre
        painter.save()
        if self._open_scale < 1.0:
            scale_val = max(0.001, self._open_scale)
            painter.translate(center_x, center_y)
            painter.scale(scale_val, scale_val)
            painter.translate(-center_x, -center_y)
            painter.setOpacity(scale_val)

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
        # Draw in order so hovered segments render on top of unhovered
        segment_draw_order = sorted(
            range(len(self.segments)),
            key=lambda i: self.segments[i].hover_progress,
        )

        for idx in segment_draw_order:
            if self._chosen_segment_idx is not None:
                if idx != self._chosen_segment_idx:
                    seg_alpha_factor = self._other_segments_opacity
                else:
                    seg_alpha_factor = max(0.0, 1.0 - self._drop_transition)
                if seg_alpha_factor <= 0.001:
                    continue
            else:
                seg_alpha_factor = 1.0

            seg_geom = self.geometry_calc.segments[idx]
            item = self.segments[idx]
            hp = item.hover_progress
            scale = item.hover_scale

            seg_r_out = r_out * scale
            seg_outer_rect = QRectF(
                center_x - seg_r_out,
                center_y - seg_r_out,
                seg_r_out * 2.0,
                seg_r_out * 2.0,
            )

            # Segment angular path
            path = QPainterPath()
            start_qt = 90.0 - seg_geom.start_angle
            sweep_qt = -self.geometry_calc.span_angle
            end_qt = 90.0 - seg_geom.end_angle

            path.arcMoveTo(seg_outer_rect, start_qt)
            path.arcTo(seg_outer_rect, start_qt, sweep_qt)
            path.arcTo(inner_rect, end_qt, -sweep_qt)
            path.closeSubpath()

            # Segment Fill:
            # Active segments: rich deep glass tint
            # Hovered segments: bright interactive feedback
            # Dimmed segments: darker recessed tint (never brighter than active)
            is_enabled = item.enabled and not self.all_segments_dimmed
            if not is_enabled:
                fill_color = QColor(10, 12, 18, int(160 * seg_alpha_factor))
            else:
                r = int(22 + (45 - 22) * hp)
                g = int(25 + (52 - 25) * hp)
                b = int(38 + (75 - 38) * hp)
                a = int((125 + (190 - 125) * hp) * seg_alpha_factor)
                fill_color = QColor(r, g, b, a)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill_color)
            painter.drawPath(path)

            # Anchor position: floats slightly outward with 6% segment growth
            ax, ay = seg_geom.label_anchor
            anchor_scale = 1.0 + ((scale - 1.0) * 0.5)
            anchor = center_pt + QPointF(ax * anchor_scale, ay * anchor_scale)

            if hp > 0.0 and is_enabled and seg_alpha_factor > 0.1:
                # Subtle hover tint wash
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 255, 255, int(25 * hp * seg_alpha_factor)))
                painter.drawPath(path)

                # Radial glow behind label
                glow = QRadialGradient(anchor, 42.0)
                alpha_glow = int(45 * hp * seg_alpha_factor)
                glow.setColorAt(0.0, QColor(255, 255, 255, alpha_glow))
                alpha_glow_mid = int(18 * hp * seg_alpha_factor)
                glow.setColorAt(0.6, QColor(255, 255, 255, alpha_glow_mid))
                glow.setColorAt(1.0, QColor(255, 255, 255, 0))
                painter.setBrush(QBrush(glow))
                painter.drawEllipse(anchor, 42.0, 42.0)

                # Outer edge accent arc for hovered segment
                path_outer_hover = QPainterPath()
                path_outer_hover.arcMoveTo(seg_outer_rect, start_qt)
                path_outer_hover.arcTo(seg_outer_rect, start_qt, sweep_qt)
                pen_col = QColor(165, 225, 255, int(180 * hp * seg_alpha_factor))
                painter.setPen(QPen(pen_col, 2.0))
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

            if is_enabled:
                label_color = QColor(255, 255, 255, int(255 * seg_alpha_factor))
                shadow_color = QColor(0, 0, 0, int(160 * seg_alpha_factor))
            else:
                label_color = QColor(160, 172, 195, int(175 * seg_alpha_factor))
                shadow_color = QColor(0, 0, 0, int(140 * seg_alpha_factor))

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
        if self._other_segments_opacity > 0.01:
            rim_grad = QLinearGradient(
                QPointF(center_x, center_y - r_out),
                QPointF(center_x, center_y + r_out),
            )
            op = self._other_segments_opacity
            rim_grad.setColorAt(0.0, QColor(255, 255, 255, int(95 * op)))
            rim_grad.setColorAt(0.4, QColor(255, 255, 255, int(40 * op)))
            rim_grad.setColorAt(1.0, QColor(255, 255, 255, int(15 * op)))
            painter.setPen(QPen(QBrush(rim_grad), 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(outer_rect)

        # Inner ring highlight: seamless continuous bright circle
        painter.setPen(QPen(QColor(255, 255, 255, 45), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(inner_rect)

        # 5. Segment separators: etched glass grooves (shadow line + specular highlight)
        if self._other_segments_opacity > 0.05:
            op = self._other_segments_opacity
            for seg_geom in self.geometry_calc.segments:
                rad = math.radians(seg_geom.start_angle)
                sin_rad = math.sin(rad)
                cos_rad = math.cos(rad)
                x1 = center_x + r_in * sin_rad
                y1 = center_y - r_in * cos_rad
                x2 = center_x + r_out * sin_rad
                y2 = center_y - r_out * cos_rad

                # Subtle shadow groove line
                painter.setPen(QPen(QColor(0, 0, 0, int(60 * op)), 1.0))
                painter.drawLine(
                    QPointF(x1 - cos_rad * 0.5, y1 - sin_rad * 0.5),
                    QPointF(x2 - cos_rad * 0.5, y2 - sin_rad * 0.5),
                )
                # Light specular line
                painter.setPen(QPen(QColor(255, 255, 255, int(35 * op)), 1.0))
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

        if self._is_center_cancel_hovered:
            # Active cancel drop target highlight: subtle crimson glass wash
            painter.setBrush(QColor(45, 18, 24, 235))
            painter.setPen(QPen(QColor(248, 113, 113, 180), 1.8))
            painter.drawEllipse(card_rect)

            # Circular cancel badge
            badge_r = 18.0
            badge_cy = center_y - 14.0
            badge_rect = QRectF(
                center_x - badge_r,
                badge_cy - badge_r,
                badge_r * 2.0,
                badge_r * 2.0,
            )
            painter.setBrush(QColor(239, 68, 68, 230))
            painter.setPen(QPen(QColor(254, 202, 202, 220), 1.2))
            painter.drawEllipse(badge_rect)

            # Crisp white 'X' icon
            pen_x = QPen(
                QColor(255, 255, 255, 255),
                2.5,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
            painter.setPen(pen_x)
            painter.drawLine(
                QPointF(center_x - 6.0, badge_cy - 6.0),
                QPointF(center_x + 6.0, badge_cy + 6.0),
            )
            painter.drawLine(
                QPointF(center_x + 6.0, badge_cy - 6.0),
                QPointF(center_x - 6.0, badge_cy + 6.0),
            )

            # "Drop to cancel" text
            font_cancel = QFont()
            font_cancel.setPointSize(10)
            font_cancel.setBold(True)
            painter.setFont(font_cancel)
            cancel_rect = QRectF(
                center_x - center_card_r + 6.0,
                center_y + 9.0,
                (center_card_r - 6.0) * 2,
                18.0,
            )
            painter.setPen(QColor(0, 0, 0, 180))
            painter.drawText(
                cancel_rect.adjusted(0, 1, 0, 1),
                Qt.AlignmentFlag.AlignCenter,
                "Drop to cancel",
            )
            painter.setPen(QColor(254, 226, 226, 255))
            painter.drawText(
                cancel_rect,
                Qt.AlignmentFlag.AlignCenter,
                "Drop to cancel",
            )

            # Subtext "No file created"
            font_sub = QFont()
            font_sub.setPointSize(8)
            font_sub.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font_sub)
            sub_rect = QRectF(
                center_x - center_card_r + 6.0,
                center_y + 29.0,
                (center_card_r - 6.0) * 2,
                16.0,
            )
            painter.setPen(QColor(252, 165, 165, 220))
            painter.drawText(
                sub_rect,
                Qt.AlignmentFlag.AlignCenter,
                "No file created",
            )
            painter.restore()
            painter.end()
            return

        # Centre dark tint overlay
        painter.setBrush(QColor(15, 15, 25, 205))
        painter.setPen(QPen(QColor(255, 255, 255, 45), 1.2))
        painter.drawEllipse(card_rect)

        if self.state == "working":
            # Working state: Ring around thumbnail with progress and size countdown
            thumb_cx = center_x
            thumb_cy = center_y - 20.0
            max_thumb = 44.0
            thumb_ring_r = 29.0 * (1.0 + 0.08 * self._ring_pulse)

            # Circular track around thumbnail
            painter.setPen(QPen(QColor(255, 255, 255, 30), 3.5, Qt.PenStyle.SolidLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(thumb_cx, thumb_cy), thumb_ring_r, thumb_ring_r)

            # Active real progress arc
            prog = max(0.0, min(1.0, self._ring_progress))
            if prog > 0.0:
                painter.setPen(
                    QPen(
                        QColor(56, 189, 248, 255),
                        3.5,
                        Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap,
                    )
                )
                arc_rect = QRectF(
                    thumb_cx - thumb_ring_r,
                    thumb_cy - thumb_ring_r,
                    thumb_ring_r * 2.0,
                    thumb_ring_r * 2.0,
                )
                # 90 degrees in Qt is 12 o'clock, negative angle sweeps clockwise
                painter.drawArc(arc_rect, 90 * 16, -int(prog * 360.0 * 16.0))

            # Thumbnail inside ring
            if self.thumbnail_pixmap and not self.thumbnail_pixmap.isNull():
                tw = min(max_thumb, float(self.thumbnail_pixmap.width()))
                th = min(max_thumb, float(self.thumbnail_pixmap.height()))
                tx = thumb_cx - (tw / 2.0)
                ty = thumb_cy - (th / 2.0)

                shadow_rect = QRectF(tx - 2.0, ty + 2.0, tw + 4.0, th + 4.0)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(0, 0, 0, 110))
                painter.drawRoundedRect(shadow_rect, 8.0, 8.0)

                painter.save()
                clip_path = QPainterPath()
                clip_path.addRoundedRect(QRectF(tx, ty, tw, th), 6.0, 6.0)
                painter.setClipPath(clip_path)
                painter.drawPixmap(
                    int(tx),
                    int(ty),
                    self.thumbnail_pixmap.scaled(
                        int(tw),
                        int(th),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    ),
                )
                painter.restore()

                painter.setPen(QPen(QColor(255, 255, 255, 45), 1.0))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(QRectF(tx, ty, tw, th), 6.0, 6.0)
            else:
                icon_w, icon_h = 24.0, 30.0
                icon_rect = QRectF(
                    thumb_cx - (icon_w / 2.0),
                    thumb_cy - (icon_h / 2.0),
                    icon_w,
                    icon_h,
                )
                painter.setPen(QPen(QColor(161, 161, 170, 220), 1.5))
                painter.setBrush(QColor(39, 39, 42, 200))
                painter.drawRoundedRect(icon_rect, 4.0, 4.0)

            # Filename below ring
            font_name = QFont()
            font_name.setPointSize(9)
            font_name.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font_name)
            fm = QFontMetrics(font_name)
            name_w = int((center_card_r - 8.0) * 2)
            elided_name = fm.elidedText(
                self.file_name, Qt.TextElideMode.ElideMiddle, name_w
            )
            name_rect = QRectF(
                center_x - center_card_r + 8.0,
                center_y + 14.0,
                name_w,
                16.0,
            )
            painter.setPen(QColor(0, 0, 0, 160))
            painter.drawText(
                name_rect.adjusted(0, 1, 0, 1),
                Qt.AlignmentFlag.AlignCenter,
                elided_name,
            )
            painter.setPen(QColor(240, 245, 255, 240))
            painter.drawText(name_rect, Qt.AlignmentFlag.AlignCenter, elided_name)

            # Live size countdown below filename
            font_count = QFont()
            font_count.setPointSize(11)
            font_count.setBold(True)
            painter.setFont(font_count)
            cur_sz_str = (
                format_size(self._countdown_bytes, spaced=True)
                if self._countdown_bytes > 0
                else "..."
            )
            count_rect = QRectF(
                center_x - center_card_r + 8.0,
                center_y + 33.0,
                (center_card_r - 8.0) * 2,
                22.0,
            )
            painter.setPen(QColor(0, 0, 0, 180))
            painter.drawText(
                count_rect.adjusted(0, 1, 0, 1),
                Qt.AlignmentFlag.AlignCenter,
                cur_sz_str,
            )
            painter.setPen(QColor(56, 189, 248, 255))
            painter.drawText(count_rect, Qt.AlignmentFlag.AlignCenter, cur_sz_str)

        elif self.state == "success":
            # Success state: ring snaps shut + soft checkmark burst (~600 ms)
            thumb_cx = center_x
            thumb_cy = center_y - 20.0
            thumb_ring_r = 29.0

            # Ring track
            painter.setPen(QPen(QColor(52, 211, 153, 40), 3.5, Qt.PenStyle.SolidLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(thumb_cx, thumb_cy), thumb_ring_r, thumb_ring_r)

            # Ring snapped shut (100% full circle) in emerald
            painter.setPen(
                QPen(
                    QColor(52, 211, 153, 255),
                    3.5,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawEllipse(QPointF(thumb_cx, thumb_cy), thumb_ring_r, thumb_ring_r)

            # Soft checkmark burst
            burst = self._checkmark_burst
            if burst > 0.0:
                # Expanding translucent halo
                halo_r = thumb_ring_r + 14.0 * burst
                halo_alpha = int(140 * (1.0 - burst))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(52, 211, 153, halo_alpha))
                painter.drawEllipse(QPointF(thumb_cx, thumb_cy), halo_r, halo_r)

                # Soft checkmark icon
                scale = 0.5 + 0.55 * min(1.0, burst * 1.3)
                pen_burst = QPen(
                    QColor(52, 211, 153, 255),
                    3.5,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
                painter.setPen(pen_burst)
                path = QPainterPath()
                path.moveTo(thumb_cx - 9.0 * scale, thumb_cy + 0.5 * scale)
                path.lineTo(thumb_cx - 2.5 * scale, thumb_cy + 7.5 * scale)
                path.lineTo(thumb_cx + 10.0 * scale, thumb_cy - 7.0 * scale)
                painter.drawPath(path)
            else:
                pen_chk = QPen(
                    QColor(52, 211, 153, 255),
                    3.5,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
                painter.setPen(pen_chk)
                path = QPainterPath()
                path.moveTo(thumb_cx - 9.0, thumb_cy + 0.5)
                path.lineTo(thumb_cx - 2.5, thumb_cy + 7.5)
                path.lineTo(thumb_cx + 10.0, thumb_cy - 7.0)
                painter.drawPath(path)

            # Filename below ring
            font_name = QFont()
            font_name.setPointSize(9)
            font_name.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font_name)
            fm = QFontMetrics(font_name)
            name_w = int((center_card_r - 8.0) * 2)
            elided_name = fm.elidedText(
                self.file_name, Qt.TextElideMode.ElideMiddle, name_w
            )
            name_rect = QRectF(
                center_x - center_card_r + 8.0,
                center_y + 14.0,
                name_w,
                16.0,
            )
            painter.setPen(QColor(0, 0, 0, 160))
            painter.drawText(
                name_rect.adjusted(0, 1, 0, 1),
                Qt.AlignmentFlag.AlignCenter,
                elided_name,
            )
            painter.setPen(QColor(240, 245, 255, 240))
            painter.drawText(name_rect, Qt.AlignmentFlag.AlignCenter, elided_name)

            # Result size message below filename
            font_res = QFont()
            font_res.setPointSize(10)
            font_res.setBold(True)
            painter.setFont(font_res)
            res_rect = QRectF(
                center_x - center_card_r + 8.0,
                center_y + 32.0,
                (center_card_r - 8.0) * 2,
                20.0,
            )
            painter.setPen(QColor(0, 0, 0, 160))
            painter.drawText(
                res_rect.adjusted(0, 1, 0, 1),
                Qt.AlignmentFlag.AlignCenter,
                self.result_message or "Complete",
            )
            painter.setPen(QColor(52, 211, 153, 255))
            painter.drawText(
                res_rect,
                Qt.AlignmentFlag.AlignCenter,
                self.result_message or "Complete",
            )

        elif self.state == "failure":
            # Failure state: amber ring + honest message
            # + "Use smallest possible" button
            is_compact = center_card_r < 70.0
            thumb_cx = center_x
            thumb_cy = center_y - (20.0 if is_compact else 24.0)
            thumb_ring_r = 18.0 if is_compact else 25.0

            # Amber ring track
            painter.setPen(QPen(QColor(245, 158, 11, 45), 3.5, Qt.PenStyle.SolidLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(thumb_cx, thumb_cy), thumb_ring_r, thumb_ring_r)

            # Amber progress ring
            painter.setPen(
                QPen(
                    QColor(245, 158, 11, 235),
                    3.5,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawEllipse(QPointF(thumb_cx, thumb_cy), thumb_ring_r, thumb_ring_r)

            # Thumbnail or warning icon inside amber ring
            max_thumb = thumb_ring_r * 1.4
            if self.thumbnail_pixmap and not self.thumbnail_pixmap.isNull():
                tw = min(max_thumb, float(self.thumbnail_pixmap.width()))
                th = min(max_thumb, float(self.thumbnail_pixmap.height()))
                tx = thumb_cx - (tw / 2.0)
                ty = thumb_cy - (th / 2.0)

                painter.save()
                clip_path = QPainterPath()
                clip_path.addRoundedRect(QRectF(tx, ty, tw, th), 4.0, 4.0)
                painter.setClipPath(clip_path)
                painter.drawPixmap(
                    int(tx),
                    int(ty),
                    self.thumbnail_pixmap.scaled(
                        int(tw),
                        int(th),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    ),
                )
                painter.restore()

                painter.setPen(QPen(QColor(245, 158, 11, 100), 1.0))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(QRectF(tx, ty, tw, th), 4.0, 4.0)
            else:
                font_warn = QFont()
                font_warn.setPointSize(12 if is_compact else 14)
                font_warn.setBold(True)
                painter.setFont(font_warn)
                painter.setPen(QColor(254, 243, 199, 230))
                painter.drawText(
                    QRectF(
                        thumb_cx - thumb_ring_r,
                        thumb_cy - thumb_ring_r,
                        thumb_ring_r * 2,
                        thumb_ring_r * 2,
                    ),
                    Qt.AlignmentFlag.AlignCenter,
                    "!",
                )

            # Honest engine error message
            title_text = "Target too small"
            if self.failure_error:
                err_lower = self.failure_error.lower()
                if "read-only" in err_lower or "permission" in err_lower:
                    title_text = "Folder read-only"
                elif "unsupported" in err_lower:
                    title_text = "Unsupported type"
                elif "not found" in err_lower:
                    title_text = "File not found"

            font_err_title = QFont()
            font_err_title.setPointSize(9 if is_compact else 10)
            font_err_title.setBold(True)
            painter.setFont(font_err_title)
            err_title_y = center_y + (2.0 if is_compact else 5.0)
            err_title_rect = QRectF(
                center_x - center_card_r + 6.0,
                err_title_y,
                (center_card_r - 6.0) * 2,
                16.0,
            )
            painter.setPen(QColor(0, 0, 0, 160))
            painter.drawText(
                err_title_rect.adjusted(0, 1, 0, 1),
                Qt.AlignmentFlag.AlignCenter,
                title_text,
            )
            painter.setPen(QColor(251, 191, 36, 255))  # Amber
            painter.drawText(err_title_rect, Qt.AlignmentFlag.AlignCenter, title_text)

            font_err_msg = QFont()
            font_err_msg.setPointSize(7.5 if is_compact else 8.5)
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
                int(center_card_r * 2 - 10),
            )
            err_msg_y = center_y + (16.0 if is_compact else 21.0)
            msg_rect = QRectF(
                center_x - center_card_r + 5.0,
                err_msg_y,
                (center_card_r - 5.0) * 2,
                16.0,
            )
            painter.setPen(QColor(0, 0, 0, 140))
            painter.drawText(
                msg_rect.adjusted(0, 1, 0, 1),
                Qt.AlignmentFlag.AlignCenter,
                elided_err,
            )
            painter.setPen(QColor(220, 225, 235, 220))
            painter.drawText(msg_rect, Qt.AlignmentFlag.AlignCenter, elided_err)

            # "Use smallest possible" button
            if self.retry_target_bytes is not None:
                retry_text = "Use smallest possible"
                btn_w = min(136.0, center_card_r * 2 - 8.0)
                btn_h = 22.0 if is_compact else 24.0
                btn_y = center_y + (31.0 if is_compact else 37.0)
                self._retry_rect = QRectF(
                    center_x - btn_w / 2.0,
                    btn_y,
                    btn_w,
                    btn_h,
                )

                painter.setBrush(QColor(245, 158, 11, 45))
                painter.setPen(QPen(QColor(245, 158, 11, 185), 1.2))
                painter.drawRoundedRect(self._retry_rect, 6.0, 6.0)

                font_btn = QFont()
                font_btn.setPointSize(7.5 if is_compact else 8.0)
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
            # Idle state: thumbnail, filename, and size / prediction / classification
            if (
                self.drag_classify_state == "none_supported"
                and self.center_classify_message
            ):
                # Center prohibited / unsupported icon
                icon_r = 16.0
                icon_cy = center_y - 16.0
                painter.setPen(QPen(QColor(248, 113, 113, 230), 2.5))
                painter.setBrush(QColor(239, 68, 68, 35))
                painter.drawEllipse(QPointF(center_x, icon_cy), icon_r, icon_r)
                painter.drawLine(
                    QPointF(center_x - 11.0, icon_cy - 11.0),
                    QPointF(center_x + 11.0, icon_cy + 11.0),
                )

                # Center text: e.g. "Unsupported file type (.docx)"
                font_msg = QFont()
                font_msg.setPointSize(
                    8.5 if len(self.center_classify_message) > 22 else 9.5
                )
                font_msg.setBold(True)
                painter.setFont(font_msg)
                fm = QFontMetrics(font_msg)
                w = int((center_card_r - 6.0) * 2)
                elided = fm.elidedText(
                    self.center_classify_message, Qt.TextElideMode.ElideMiddle, w
                )
                rect = QRectF(center_x - center_card_r + 6.0, center_y + 8.0, w, 18.0)
                painter.setPen(QColor(0, 0, 0, 180))
                painter.drawText(
                    rect.adjusted(0, 1, 0, 1), Qt.AlignmentFlag.AlignCenter, elided
                )
                painter.setPen(QColor(248, 113, 113, 255))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, elided)

                # Subtext: "Drop not allowed"
                font_sub = QFont()
                font_sub.setPointSize(8)
                font_sub.setWeight(QFont.Weight.DemiBold)
                painter.setFont(font_sub)
                sub_rect = QRectF(
                    center_x - center_card_r + 6.0, center_y + 28.0, w, 16.0
                )
                painter.setPen(QColor(160, 172, 195, 220))
                painter.drawText(
                    sub_rect, Qt.AlignmentFlag.AlignCenter, "Drop not allowed"
                )
                painter.restore()
                painter.end()
                return

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

            # File size, prediction, or classification note: 9pt demibold with shadow
            font_size = QFont()
            font_size.setPointSize(9)
            font_size.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font_size)

            size_rect = QRectF(
                center_x - center_card_r + 6.0,
                center_y + 29.0,
                (center_card_r - 6.0) * 2,
                18.0,
            )

            if (
                self.drag_classify_state in ("mixed", "unknown")
                and self.center_classify_message
            ):
                font_msg = QFont()
                font_msg.setPointSize(
                    8.0 if len(self.center_classify_message) > 24 else 8.5
                )
                font_msg.setWeight(QFont.Weight.DemiBold)
                painter.setFont(font_msg)
                fm_msg = QFontMetrics(font_msg)
                w_msg = int((center_card_r - 6.0) * 2)
                elided_msg = fm_msg.elidedText(
                    self.center_classify_message, Qt.TextElideMode.ElideMiddle, w_msg
                )

                painter.setPen(QColor(0, 0, 0, 160))
                painter.drawText(
                    size_rect.adjusted(0, 1, 0, 1),
                    Qt.AlignmentFlag.AlignCenter,
                    elided_msg,
                )
                col = (
                    QColor(251, 191, 36)
                    if self.drag_classify_state == "mixed"
                    else QColor(56, 189, 248)
                )
                painter.setPen(col)
                painter.drawText(size_rect, Qt.AlignmentFlag.AlignCenter, elided_msg)
                painter.restore()
                painter.end()
                return

            pred = self._current_prediction or self._fading_prediction
            active_text = None
            is_ok = True
            if (
                self._hover_reason
                and self._hovered_idx is not None
                and not self.segments[self._hovered_idx].enabled
            ):
                active_text = self._hover_reason
                is_ok = False
            elif pred is not None:
                active_text = pred.text
                is_ok = pred.ok

            op = self._prediction_opacity
            center_size_str = (
                "Already small"
                if (self.is_already_small and not self._hover_reason)
                else self.file_size_text
            )
            is_already_small_active = (
                self.is_already_small and not self._hover_reason and op <= 0.0
            )
            normal_size_color = (
                QColor(251, 191, 36, 240)
                if is_already_small_active
                else QColor(210, 215, 225, 240)
            )

            if op <= 0.0 or active_text is None:
                painter.setPen(QColor(0, 0, 0, 160))
                painter.drawText(
                    size_rect.adjusted(0, 1, 0, 1),
                    Qt.AlignmentFlag.AlignCenter,
                    center_size_str,
                )
                painter.setPen(normal_size_color)
                painter.drawText(
                    size_rect, Qt.AlignmentFlag.AlignCenter, center_size_str
                )
            elif op >= 1.0:
                size_color = (
                    QColor(165, 225, 255, 255) if is_ok else QColor(251, 191, 36, 255)
                )
                painter.setPen(QColor(0, 0, 0, 160))
                painter.drawText(
                    size_rect.adjusted(0, 1, 0, 1),
                    Qt.AlignmentFlag.AlignCenter,
                    active_text,
                )
                painter.setPen(size_color)
                painter.drawText(size_rect, Qt.AlignmentFlag.AlignCenter, active_text)
            else:
                # Smooth cross-fade between file size and prediction label
                file_alpha = int(240 * (1.0 - op))
                shadow_alpha_file = int(160 * (1.0 - op))
                painter.setPen(QColor(0, 0, 0, shadow_alpha_file))
                painter.drawText(
                    size_rect.adjusted(0, 1, 0, 1),
                    Qt.AlignmentFlag.AlignCenter,
                    center_size_str,
                )
                painter.setPen(
                    QColor(251, 191, 36, file_alpha)
                    if self.is_already_small
                    else QColor(210, 215, 225, file_alpha)
                )
                painter.drawText(
                    size_rect, Qt.AlignmentFlag.AlignCenter, center_size_str
                )

                pred_color = QColor(165, 225, 255) if is_ok else QColor(251, 191, 36)
                pred_color.setAlpha(int(255 * op))
                shadow_alpha_pred = int(160 * op)
                painter.setPen(QColor(0, 0, 0, shadow_alpha_pred))
                painter.drawText(
                    size_rect.adjusted(0, 1, 0, 1),
                    Qt.AlignmentFlag.AlignCenter,
                    active_text,
                )
                painter.setPen(pred_color)
                painter.drawText(size_rect, Qt.AlignmentFlag.AlignCenter, active_text)

        painter.restore()
        painter.end()
