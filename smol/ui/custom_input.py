"""Custom size input popup for smol.

Opens a compact, floating card near the cursor:
- Number input with validation (rejects zero, negatives, empty, or non-numeric)
- KB/MB unit toggle (1 KB = 1000 bytes, 1 MB = 1000000 bytes)
- Lists favourites (sizes.pinned) and recents (sizes.recents)
- Arrow keys (Up/Down) + Enter to pick from list or type a value
- Floor validation: "Smallest I can make this is about {floor}"
- Records picked/confirmed custom size into sizes.recents (LRU, 5% dedupe, max 5)
- Enter key confirms, Esc cancels
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from smol.config import add_recent_size, load_config
from smol.core.size import format_size


class _CustomLineEdit(QLineEdit):
    """Custom line edit that forwards Down arrow key to list widget."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.down_pressed = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Down:
            self.parent()._on_line_edit_down()
            event.accept()
            return
        super().keyPressEvent(event)


class CustomInputDialog(QDialog):
    """Compact frameless dialog for entering or selecting custom target sizes."""

    confirmed = Signal(object)
    cancelled = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        floor_bytes: int | None = None,
        config_path: Path | str | None = None,
    ) -> None:
        super().__init__(parent)

        self._floor_bytes = floor_bytes
        self._config_path = config_path
        self._unit = "KB"
        self._has_error = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._init_ui()

    @property
    def unit(self) -> str:
        """Current unit: 'KB' or 'MB'."""
        return self._unit

    def set_unit(self, unit: str) -> None:
        """Set unit explicitly to 'KB' or 'MB'."""
        if unit.upper() in ("KB", "MB"):
            self._unit = unit.upper()
            self.unit_toggle_btn.setText(self._unit)

    def has_error(self) -> bool:
        """Return True if an error is currently displayed."""
        return self._has_error

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        # Title / prompt label
        title_label = QLabel("Custom Target Size", self)
        title_font = QFont()
        title_font.setPointSize(9)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: rgba(255, 255, 255, 220);")
        layout.addWidget(title_label)

        # Input row: Number input + KB/MB toggle + OK button
        row_layout = QHBoxLayout()
        row_layout.setSpacing(6)

        self.line_edit = _CustomLineEdit(self)
        self.line_edit.setPlaceholderText("e.g. 75")
        self.line_edit.setFocus()
        self.line_edit.textChanged.connect(self._on_text_changed)
        self.line_edit.returnPressed.connect(self._handle_confirm)

        self.unit_toggle_btn = QPushButton("KB", self)
        self.unit_toggle_btn.setFixedWidth(46)
        self.unit_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.unit_toggle_btn.clicked.connect(self._toggle_unit)

        self.confirm_btn = QPushButton("↵", self)
        self.confirm_btn.setFixedWidth(32)
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.clicked.connect(self._handle_confirm)

        row_layout.addWidget(self.line_edit, stretch=1)
        row_layout.addWidget(self.unit_toggle_btn)
        row_layout.addWidget(self.confirm_btn)
        layout.addLayout(row_layout)

        # Error label
        self.error_label = QLabel("", self)
        error_font = QFont()
        error_font.setPointSize(8)
        self.error_label.setFont(error_font)
        self.error_label.setStyleSheet("color: #ff6b6b;")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        # Favourites and Recents list
        cfg = load_config(self._config_path)
        pinned = list(cfg.sizes.pinned)
        recents = list(cfg.sizes.recents)

        self.items_list = QListWidget(self)
        self.items_list.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.items_list.installEventFilter(self)
        self.items_list.itemClicked.connect(self._handle_item_clicked)

        has_items = False
        for sz in pinned:
            has_items = True
            lbl = f"★ {format_size(sz, spaced=True)}  (Favourite)"
            item = QListWidgetItem(lbl)
            item.setData(Qt.ItemDataRole.UserRole, sz)
            self.items_list.addItem(item)

        for sz in recents:
            if sz not in pinned:
                has_items = True
                lbl = f"◷ {format_size(sz, spaced=True)}"
                item = QListWidgetItem(lbl)
                item.setData(Qt.ItemDataRole.UserRole, sz)
                self.items_list.addItem(item)

        if has_items:
            list_font = QFont()
            list_font.setPointSize(8)
            self.items_list.setFont(list_font)
            self.items_list.setStyleSheet(
                """
                QListWidget {
                    background-color: rgba(20, 24, 35, 210);
                    border: 1px solid rgba(255, 255, 255, 40);
                    border-radius: 6px;
                    color: #e2e8f0;
                    padding: 2px;
                }
                QListWidget::item {
                    padding: 4px 6px;
                    border-radius: 4px;
                }
                QListWidget::item:hover {
                    background-color: rgba(56, 189, 248, 40);
                }
                QListWidget::item:selected {
                    background-color: rgba(56, 189, 248, 80);
                    color: #ffffff;
                }
                """
            )
            layout.addWidget(self.items_list)
            num_rows = min(5, self.items_list.count())
            self.items_list.setFixedHeight(num_rows * 24 + 10)
            self.setFixedSize(240, 110 + self.items_list.height())
        else:
            self.items_list.hide()
            self.setFixedSize(220, 100)

        self._update_styles()

    def _on_line_edit_down(self) -> None:
        """Handle Down key in line edit by focusing list widget."""
        if not self.items_list.isHidden() and self.items_list.count() > 0:
            self.items_list.setFocus()
            self.items_list.setCurrentRow(0)

    def eventFilter(self, watched, event: QEvent) -> bool:
        """Handle Up key and Enter key in items_list."""
        if watched == self.items_list and event.type() == QEvent.Type.KeyPress:
            key_event: QKeyEvent = event  # type: ignore
            if (
                key_event.key() == Qt.Key.Key_Up
                and self.items_list.currentRow() == 0
            ):
                self.items_list.clearSelection()
                self.line_edit.setFocus()
                return True
            elif key_event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._handle_list_confirm()
                return True
        return super().eventFilter(watched, event)

    def _handle_item_clicked(self, item: QListWidgetItem) -> None:
        """Handle clicking an item in the favourites/recents list."""
        sz = item.data(Qt.ItemDataRole.UserRole)
        if sz is not None:
            self._confirm_size(int(sz))

    def _handle_list_confirm(self) -> None:
        """Handle Enter key when items_list has selection."""
        item = self.items_list.currentItem()
        if item is not None:
            sz = item.data(Qt.ItemDataRole.UserRole)
            if sz is not None:
                self._confirm_size(int(sz))

    def _update_styles(self) -> None:
        border_color = "#ff6b6b" if self._has_error else "rgba(255, 255, 255, 60)"
        self.line_edit.setStyleSheet(
            f"""
            QLineEdit {{
                background-color: rgba(25, 27, 38, 220);
                color: #ffffff;
                border: 1px solid {border_color};
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: 600;
            }}
            QLineEdit:focus {{
                border: 1px solid rgba(100, 180, 255, 200);
            }}
            """
        )

        self.unit_toggle_btn.setStyleSheet(
            """
            QPushButton {{
                background-color: rgba(45, 50, 70, 220);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 50);
                border-radius: 6px;
                padding: 4px 6px;
                font-size: 10px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: rgba(60, 70, 100, 240);
                border: 1px solid rgba(255, 255, 255, 100);
            }}
            """
        )

        self.confirm_btn.setStyleSheet(
            """
            QPushButton {{
                background-color: rgba(30, 140, 90, 220);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 60);
                border-radius: 6px;
                padding: 4px 6px;
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: rgba(40, 180, 110, 240);
            }}
            """
        )

    def _toggle_unit(self) -> None:
        """Toggle between KB and MB."""
        self._unit = "MB" if self._unit == "KB" else "KB"
        self.unit_toggle_btn.setText(self._unit)

    def _on_text_changed(self) -> None:
        """Clear error state on user typing."""
        if self._has_error:
            self._has_error = False
            self.error_label.hide()
            self._update_styles()

    def _validate(self) -> int | None:
        """Validate input and return target bytes, or None if invalid."""
        raw_text = self.line_edit.text().strip()
        if not raw_text:
            self._show_error("Size cannot be empty")
            return None

        try:
            val = float(raw_text)
        except ValueError:
            self._show_error("Must be a valid number")
            return None

        if val <= 0:
            self._show_error("Must be greater than 0")
            return None

        multiplier = 1_000 if self._unit == "KB" else 1_000_000
        target_bytes = int(val * multiplier)
        if target_bytes <= 0:
            self._show_error("Must be greater than 0")
            return None

        # Validate against estimated floor
        if self._floor_bytes is not None and target_bytes < self._floor_bytes:
            formatted_floor = format_size(self._floor_bytes, spaced=True)
            self._show_error(f"Smallest I can make this is about {formatted_floor}")
            return None

        return target_bytes

    def _show_error(self, message: str) -> None:
        self._has_error = True
        self.error_label.setText(message)
        self.error_label.show()
        self._update_styles()

    def _confirm_size(self, target_bytes: int) -> None:
        """Record size into recents, emit confirmed signal, and close."""
        add_recent_size(target_bytes, self._config_path)
        self.confirmed.emit(target_bytes)
        self.close()

    def _handle_confirm(self) -> None:
        """Validate and confirm typed input."""
        target_bytes = self._validate()
        if target_bytes is not None:
            self._confirm_size(target_bytes)

    def _handle_cancel(self) -> None:
        """Cancel and close."""
        self.cancelled.emit()
        self.close()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle Esc key to cancel dialog."""
        if event.key() == Qt.Key.Key_Escape:
            self._handle_cancel()
            event.accept()
            return
        super().keyPressEvent(event)

    def position_near(self, point: QPoint) -> None:
        """Position the dialog near the given point, clamped inside screen geometry."""
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        screen_geo = screen.availableGeometry() if screen else None

        target_x = point.x() - self.width() // 2
        target_y = point.y() - self.height() // 2

        if screen_geo is not None:
            max_x = screen_geo.right() - self.width() - 10
            max_y = screen_geo.bottom() - self.height() - 10
            target_x = max(screen_geo.left() + 10, min(target_x, max_x))
            target_y = max(screen_geo.top() + 10, min(target_y, max_y))

        self.move(target_x, target_y)

    def paintEvent(self, event) -> None:
        """Paint dark liquid glass rounded container."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect()
        path = QPainterPath()
        path.addRoundedRect(rect.adjusted(1, 1, -1, -1), 10.0, 10.0)

        # Background fill
        painter.fillPath(path, QColor(18, 20, 28, 235))

        # Border
        painter.setPen(QColor(255, 255, 255, 45))
        painter.drawPath(path)
