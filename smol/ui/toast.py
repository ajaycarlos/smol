"""Toast notification overlay window (PySide6).

Displays completion state after shrinking:
- "photo.jpg  1.02 MB → 97 KB"
- Buttons: "Open folder", "Undo", "Copy path"
- Auto-hides after 6 s, paused while hovered
- Undo strictly deletes only the output file created, NEVER touching the original.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDesktopServices,
    QGuiApplication,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from smol.core.result import Result
from smol.core.size import format_size

logger = logging.getLogger("smol.toast")


class ToastWindow(QWidget):
    """Frameless translucent completion toast near cursor or screen corner."""

    folder_opened = Signal(Path)
    path_copied = Signal(str)
    undone = Signal(list)  # list[Path] deleted
    dismissed = Signal()

    def __init__(
        self,
        results: list[tuple[Path, Result]],
        cursor_pos: QPoint | None = None,
        reduce_motion: bool = False,
        auto_hide_ms: int = 6000,
        skipped_files: list[Path | str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.results = results
        self.cursor_pos = cursor_pos
        self.reduce_motion = reduce_motion
        self.auto_hide_ms = auto_hide_ms
        self.skipped_files = [Path(f) for f in (skipped_files or [])]

        self._is_hovered: bool = False
        self._undone: bool = False
        self._deleted_outputs: list[Path] = []
        self._slide_anim: QPropertyAnimation | None = None
        self._opacity_anim: QPropertyAnimation | None = None

        self._init_window()
        self._build_ui()
        self._init_timer()
        self._position_toast()

    def _init_window(self) -> None:
        """Configure top-level window flags and transparency."""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setObjectName("ToastWindow")

    def _build_ui(self) -> None:
        """Construct the liquid glass toast card and controls."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(0)

        # Container card with dark glass styling
        self.card = QFrame(self)
        self.card.setObjectName("ToastCard")
        self.card.setStyleSheet(
            """
            #ToastCard {
                background-color: rgba(16, 18, 27, 240);
                border: 1px solid rgba(255, 255, 255, 42);
                border-radius: 12px;
            }
            """
        )

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24.0)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 6)
        self.card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(10)

        # --- Top row: Badge, message, close button ---
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(10)

        # Soft green check badge
        self.badge = QLabel("✓", self.card)
        self.badge.setFixedSize(22, 22)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setStyleSheet(
            """
            background-color: rgba(52, 211, 153, 35);
            border: 1px solid rgba(52, 211, 153, 140);
            border-radius: 11px;
            color: #34d399;
            font-size: 13px;
            font-weight: bold;
            """
        )
        top_row.addWidget(self.badge)

        # Main message: "photo.jpg  1.02 MB → 97 KB"
        self.label_message = QLabel(self.card)
        self.label_message.setTextFormat(Qt.TextFormat.RichText)
        self.label_message.setText(self._format_message())
        top_row.addWidget(self.label_message, 1)

        # Close button "✕"
        self.btn_close = QPushButton("✕", self.card)
        self.btn_close.setFixedSize(20, 20)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setToolTip("Dismiss")
        self.btn_close.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                border: none;
                color: rgba(255, 255, 255, 140);
                font-size: 11px;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 25);
                color: #ffffff;
            }
            """
        )
        self.btn_close.clicked.connect(self.fade_out_and_close)
        top_row.addWidget(self.btn_close)

        card_layout.addLayout(top_row)

        # Status note (e.g. for feedback after undo/copy)
        self.label_status = QLabel(self.card)
        self.label_status.setStyleSheet("color: #94a3b8; font-size: 11px;")
        self.label_status.setVisible(False)
        card_layout.addWidget(self.label_status)

        # --- Bottom row: Action buttons ---
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 2, 0, 0)
        btn_row.setSpacing(8)

        btn_style = """
            QPushButton {
                background-color: rgba(255, 255, 255, 16);
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 6px;
                color: #e2e8f0;
                padding: 5px 12px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 32);
                border-color: rgba(255, 255, 255, 65);
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 12);
            }
            QPushButton:disabled {
                color: rgba(255, 255, 255, 50);
                border-color: rgba(255, 255, 255, 14);
                background-color: transparent;
            }
        """

        self.btn_open = QPushButton("Open folder", self.card)
        self.btn_open.setStyleSheet(btn_style)
        self.btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open.clicked.connect(self.open_folder)
        btn_row.addWidget(self.btn_open)

        self.btn_undo = QPushButton("Undo", self.card)
        self.btn_undo.setStyleSheet(btn_style)
        self.btn_undo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_undo.clicked.connect(self.undo)
        btn_row.addWidget(self.btn_undo)

        self.btn_copy = QPushButton("Copy path", self.card)
        self.btn_copy.setStyleSheet(btn_style)
        self.btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy.clicked.connect(self.copy_path)
        btn_row.addWidget(self.btn_copy)

        btn_row.addStretch(1)
        card_layout.addLayout(btn_row)

        main_layout.addWidget(self.card)

        # Disable undo/copy if no output was created
        has_output = any(r.ok and r.output_path is not None for _, r in self.results)
        if not has_output:
            self.btn_undo.setEnabled(False)
            self.btn_copy.setEnabled(False)

    def _format_message(self) -> str:
        """Format the primary notification string with bold filename and sizes."""
        shrunk_items = [
            (p, r) for p, r in self.results if r.ok and r.output_path is not None
        ]
        small_items = [
            (p, r) for p, r in self.results if r.ok and r.output_path is None
        ]

        if len(shrunk_items) == 1:
            src, res = shrunk_items[0]
            orig_sz = format_size(res.original_bytes, spaced=True)
            final_sz = format_size(res.final_bytes, spaced=True)
            # "photo.jpg  1.02 MB → 97 KB"
            msg = (
                f"<span style='color: #ffffff; font-weight: 700; font-size: 13px;'>"
                f"{src.name}</span> &nbsp;&nbsp; "
                f"<span style='color: #94a3b8; font-size: 12px;'>{orig_sz}</span> "
                f"<span style='color: #64748b; font-size: 11px;'>→</span> "
                f"<span style='color: #38bdf8; font-weight: 700; font-size: 12px;'>"
                f"✓ {final_sz}</span>"
            )
        elif len(shrunk_items) > 1:
            tot_orig = sum(r.original_bytes for _, r in shrunk_items)
            tot_final = sum(r.final_bytes for _, r in shrunk_items)
            orig_sz = format_size(tot_orig, spaced=True)
            final_sz = format_size(tot_final, spaced=True)
            count = len(shrunk_items)
            msg = (
                f"<span style='color: #ffffff; font-weight: 700; font-size: 13px;'>"
                f"{count} files</span> &nbsp;&nbsp; "
                f"<span style='color: #94a3b8; font-size: 12px;'>{orig_sz}</span> "
                f"<span style='color: #64748b; font-size: 11px;'>→</span> "
                f"<span style='color: #38bdf8; font-weight: 700; font-size: 12px;'>"
                f"✓ {final_sz}</span>"
            )
        elif small_items:
            src, res = small_items[0]
            sz = format_size(res.original_bytes, spaced=True)
            msg = (
                f"<span style='color: #ffffff; font-weight: 700; font-size: 13px;'>"
                f"{src.name}</span> &nbsp;&nbsp; "
                f"<span style='color: #34d399; font-weight: 600; font-size: 12px;'>"
                f"Already ≤ target ({sz})</span>"
            )
        else:
            msg = (
                "<span style='color: #ffffff; font-weight: 700; font-size: 13px;'>"
                "Completed</span>"
            )

        if self.skipped_files:
            skipped_names = ", ".join(f.name for f in self.skipped_files)
            msg += (
                f"<br><span style='color: #f87171; font-size: 11px;'>"
                f"Skipped: {skipped_names}</span>"
            )

        return msg

    def _init_timer(self) -> None:
        """Initialize the 6-second auto-hide timer."""
        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.setInterval(self.auto_hide_ms)
        self._auto_hide_timer.timeout.connect(self.fade_out_and_close)

    def showEvent(self, event) -> None:
        """Trigger slide-in and start auto-hide timer on display."""
        super().showEvent(event)
        self._start_slide_in()
        if not self._is_hovered and not self._undone:
            self._auto_hide_timer.start(self.auto_hide_ms)

    def enterEvent(self, event) -> None:
        """Pause auto-hide while mouse hovers over the toast."""
        self._is_hovered = True
        if self._auto_hide_timer.isActive():
            self._auto_hide_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        """Resume auto-hide after mouse leaves the toast."""
        self._is_hovered = False
        if not self._undone and self.isVisible():
            self._auto_hide_timer.start(self.auto_hide_ms)
        super().leaveEvent(event)

    def _position_toast(self) -> None:
        """Calculate placement near cursor or fallback to bottom-right corner."""
        self.adjustSize()
        w = max(380, self.sizeHint().width())
        h = max(90, self.sizeHint().height())
        self.resize(w, h)

        target_pt = self._calc_target_pos(w, h)
        self.target_pos = target_pt
        self.move(target_pt)

    def _calc_target_pos(self, w: int, h: int) -> QPoint:
        """Calculate clamped screen coordinates near cursor or screen corner."""
        pos = self.cursor_pos or QCursor.pos()
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        if screen is None:
            return QPoint(100, 100)

        geom = screen.availableGeometry()

        if self.cursor_pos is not None:
            # Place near cursor (offset slightly down and right)
            tx = pos.x() + 24
            ty = pos.y() + 24

            # Flip if it would run off screen edges
            if tx + w > geom.right() - 16:
                tx = pos.x() - w - 24
            if ty + h > geom.bottom() - 16:
                ty = pos.y() - h - 24

            # Clamp securely inside available screen rectangle
            tx = max(geom.left() + 16, min(tx, geom.right() - w - 16))
            ty = max(geom.top() + 16, min(ty, geom.bottom() - h - 16))
            return QPoint(tx, ty)
        else:
            # Corner fallback: bottom-right
            tx = geom.right() - w - 24
            ty = geom.bottom() - h - 24
            return QPoint(tx, ty)

    def _start_slide_in(self) -> None:
        """Execute smooth slide-in animation from below target position."""
        if self.reduce_motion:
            self.setWindowOpacity(1.0)
            self.move(self.target_pos)
            return

        final_pos = self.target_pos
        start_pos = QPoint(final_pos.x(), final_pos.y() + 22)
        self.move(start_pos)
        self.setWindowOpacity(0.0)

        self._slide_anim = QPropertyAnimation(self, b"pos", self)
        self._slide_anim.setDuration(220)
        self._slide_anim.setStartValue(start_pos)
        self._slide_anim.setEndValue(final_pos)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._opacity_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._opacity_anim.setDuration(220)
        self._opacity_anim.setStartValue(0.0)
        self._opacity_anim.setEndValue(1.0)
        self._opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._slide_anim.start()
        self._opacity_anim.start()

    def open_folder(self) -> None:
        """Open the directory containing the shrunk file in the system file manager."""
        folder: Path | None = None
        for _, res in self.results:
            if res.ok and res.output_path is not None:
                folder = res.output_path.parent
                break

        if folder is None and self.results:
            src, _ = self.results[0]
            folder = src.parent

        if folder is not None and folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
            self.folder_opened.emit(folder)

    def copy_path(self) -> None:
        """Copy output file path(s) to system clipboard with visual feedback."""
        paths: list[str] = []
        for _, res in self.results:
            if res.ok and res.output_path is not None:
                paths.append(str(res.output_path))

        if not paths:
            return

        text = "\n".join(paths)
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)

        self.btn_copy.setText("✓ Copied!")
        self.path_copied.emit(text)
        QTimer.singleShot(1500, lambda: self.btn_copy.setText("Copy path"))

    def undo(self) -> list[Path]:
        """Safely delete ONLY the output file(s) we created.

        HARD PROMISE: The original file is NEVER deleted or modified.
        """
        deleted: list[Path] = []
        for src_path, res in self.results:
            if not res.ok or res.output_path is None:
                continue

            src = Path(src_path).resolve()
            out = Path(res.output_path).resolve()

            # INVARIANT 1: Output must NOT match original file
            if out == src:
                logger.critical(
                    "SAFETY VIOLATION: output_path matches source_path (%s)!"
                    " Refusing to delete.",
                    src,
                )
                continue

            # INVARIANT 2: Output file must exist and be a regular file
            if not out.is_file():
                continue

            # INVARIANT 3: Source file must exist before we touch output
            if not src.exists():
                logger.warning(
                    "Source file %s does not exist; skipping deletion of %s.",
                    src,
                    out,
                )
                continue

            # INVARIANT 4: Output must not be a symlink to source
            if out.is_symlink() and out.resolve() == src:
                logger.critical(
                    "SAFETY VIOLATION: output is symlink to source! Refusing to delete."
                )
                continue

            # Delete ONLY the output file
            try:
                out.unlink()
                deleted.append(out)
                logger.info("Undo: removed output file %s", out)
            except OSError as exc:
                logger.error("Failed to delete output file %s: %s", out, exc)
                continue

            # INVARIANT 5: Post-condition verify: original file MUST still exist!
            assert src.exists(), (
                f"CRITICAL ENGINE PROMISE BROKEN: Original file {src} was deleted!"
            )

        self._undone = True
        self._deleted_outputs = deleted

        # Update UI feedback
        self.btn_undo.setEnabled(False)
        self.btn_undo.setText("Undone")
        self.btn_copy.setEnabled(False)
        self.label_status.setText("Output deleted (original untouched)")
        self.label_status.setStyleSheet("color: #fbbf24; font-size: 11px;")
        self.label_status.setVisible(True)

        self.undone.emit(deleted)

        # Auto-dismiss smoothly after undo
        QTimer.singleShot(1500, self.fade_out_and_close)
        return deleted

    def fade_out_and_close(self) -> None:
        """Fade out toast window smoothly and close."""
        if self._auto_hide_timer.isActive():
            self._auto_hide_timer.stop()

        if self.reduce_motion or not self.isVisible():
            self.dismissed.emit()
            self.close()
            return

        self._anim_fade_out = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim_fade_out.setDuration(180)
        self._anim_fade_out.setStartValue(self.windowOpacity())
        self._anim_fade_out.setEndValue(0.0)
        self._anim_fade_out.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _finish() -> None:
            self.dismissed.emit()
            self.close()

        self._anim_fade_out.finished.connect(_finish)
        self._anim_fade_out.start()
