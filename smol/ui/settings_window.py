"""PySide6 settings window for smol.

Provides user interface for configuring:
- Trigger-key capture box (with conflict warnings for Ctrl, Shift, Alt)
- Size list editor (add, remove, reorder)
- Output rules (next to original file or fixed folder picker)
- Feature toggles (keep format, allow convert, strip metadata, reduce motion, autostart)
- Save button with validation
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from smol.config import SmolConfig, load_config, save_config
from smol.core.size import format_size, parse_size
from smol.integrations.autostart import AutostartIntegrator

DARK_STYLESHEET = """
QWidget#settingsRoot {
    background-color: #0d111a;
    color: #e2e8f0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

QScrollArea {
    border: none;
    background-color: transparent;
}

QWidget#scrollContainer {
    background-color: transparent;
}

QFrame.cardFrame {
    background-color: #161b26;
    border: 1px solid #232b3d;
    border-radius: 8px;
    padding: 10px 14px;
}

QLabel.sectionTitle {
    color: #f8fafc;
    font-size: 11pt;
    font-weight: 700;
}

QLabel.subText {
    color: #94a3b8;
    font-size: 9pt;
}

QLabel.optionDesc {
    color: #64748b;
    font-size: 8.5pt;
    margin-left: 22px;
}

QPushButton {
    background-color: #1e2638;
    color: #e2e8f0;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 9.5pt;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #27334d;
    border-color: #475569;
}

QPushButton:pressed {
    background-color: #192233;
}

QPushButton:disabled {
    background-color: #131722;
    color: #475569;
    border-color: #1e2638;
}

QPushButton.primaryButton {
    background-color: #0284c7;
    color: #ffffff;
    border: 1px solid #0ea5e9;
    font-weight: 600;
    padding: 7px 20px;
}

QPushButton.primaryButton:hover {
    background-color: #0369a1;
    border-color: #38bdf8;
}

QPushButton.primaryButton:pressed {
    background-color: #075985;
}

QPushButton.keyCaptureBtn {
    background-color: #1b2234;
    border: 1px solid #3b4968;
    color: #38bdf8;
    font-size: 11pt;
    font-weight: 700;
    padding: 9px 18px;
    border-radius: 6px;
    text-align: center;
}

QPushButton.keyCaptureBtn:hover {
    background-color: #242f49;
    border-color: #00d2ff;
}

QPushButton.keyCaptureBtn[recording="true"] {
    background-color: #172a45;
    border: 2px solid #00d2ff;
    color: #f0f9ff;
}

QListWidget {
    background-color: #111520;
    border: 1px solid #232b3d;
    border-radius: 6px;
    color: #f1f5f9;
    padding: 4px;
}

QListWidget::item {
    padding: 7px 10px;
    border-radius: 4px;
    margin: 1px 2px;
}

QListWidget::item:hover {
    background-color: #1c2333;
}

QListWidget::item:selected {
    background-color: #0369a1;
    color: #ffffff;
}

QLineEdit {
    background-color: #111520;
    border: 1px solid #2b354c;
    border-radius: 6px;
    color: #f8fafc;
    padding: 7px 10px;
    font-size: 9.5pt;
}

QLineEdit:focus {
    border: 1px solid #00d2ff;
}

QRadioButton, QCheckBox {
    color: #e2e8f0;
    font-size: 9.5pt;
    spacing: 8px;
}

QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border-radius: 8px;
}

QRadioButton::indicator:unchecked {
    border: 1px solid #475569;
    border-radius: 8px;
    background-color: #111520;
}

QRadioButton::indicator:checked {
    border: 1px solid #00d2ff;
    border-radius: 8px;
    background-color: #0284c7;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 3px;
}

QCheckBox::indicator:unchecked {
    border: 1px solid #475569;
    border-radius: 3px;
    background-color: #111520;
}

QCheckBox::indicator:checked {
    border: 1px solid #00d2ff;
    border-radius: 3px;
    background-color: #0284c7;
}

QScrollBar:vertical {
    border: none;
    background-color: #0d111a;
    width: 8px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background-color: #232b3d;
    min-height: 20px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background-color: #3b4968;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""


def check_trigger_key_conflict(key: str) -> tuple[bool, str]:
    """Check if the chosen key conflicts with common desktop/file-manager shortcuts.

    Returns (is_conflict, warning_message).
    """
    cleaned = key.strip()
    upper = cleaned.upper()

    # Plain Ctrl (without Alt) triggers "Copy" in Nemo, Nautilus, Dolphin, Thunar
    if upper in ("CTRL", "CONTROL", "CONTROL_L", "CONTROL_R", "LCTRL", "RCTRL"):
        return (
            True,
            (
                "⚠️ Holding Ctrl while dragging triggers 'Copy' in Linux "
                "file managers.\nSuper or Ctrl+Alt is recommended."
            ),
        )

    # Shift triggers "Move"
    if upper in ("SHIFT", "SHIFT_L", "SHIFT_R", "LSHIFT", "RSHIFT"):
        return (
            True,
            "⚠️ Holding Shift while dragging triggers 'Move' in Linux file managers.",
        )

    # Alt triggers window movement (Alt+drag) or Link
    if upper in ("ALT", "ALT_L", "LALT"):
        return (
            True,
            (
                "⚠️ Holding Alt while dragging triggers window movement in\n"
                "Linux desktop environments."
            ),
        )

    return (False, "")


class TriggerKeyCaptureWidget(QWidget):
    """Interactive capture box for setting the hold-trigger key."""

    key_changed = Signal(str)

    def __init__(
        self, initial_key: str = "Super", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._current_key = initial_key or "Super"
        self._recording = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Button displaying the captured key
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.key_button = QPushButton(self._current_key)
        self.key_button.setProperty("class", "keyCaptureBtn")
        self.key_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.key_button.clicked.connect(self._toggle_recording)
        self.key_button.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        btn_row.addWidget(self.key_button)

        self.record_button = QPushButton("Capture Key")
        self.record_button.clicked.connect(self._toggle_recording)
        btn_row.addWidget(self.record_button)

        layout.addLayout(btn_row)

        # Quick preset buttons
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        preset_label = QLabel("Presets:")
        preset_label.setStyleSheet("color: #64748b; font-size: 8.5pt;")
        preset_row.addWidget(preset_label)

        presets = [
            ("Super (Default)", "Super"),
            ("Ctrl+Alt", "Ctrl+Alt"),
            ("Right Alt", "Right Alt"),
            ("Right Ctrl", "Right Ctrl"),
        ]
        for label, val in presets:
            btn = QPushButton(label)
            btn.setStyleSheet("font-size: 8.5pt; padding: 3px 8px;")
            btn.clicked.connect(lambda _=False, k=val: self.set_key(k))
            preset_row.addWidget(btn)
        preset_row.addStretch()
        layout.addLayout(preset_row)

        # Warning / conflict label
        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.hide()
        layout.addWidget(self.warning_label)

        self._update_conflict_display()

    def get_key(self) -> str:
        return self._current_key

    def set_key(self, key: str) -> None:
        self._current_key = key.strip()
        self._recording = False
        self.key_button.setProperty("recording", "false")
        self.key_button.setText(self._current_key)
        self.record_button.setText("Capture Key")
        self._update_conflict_display()
        self.key_changed.emit(self._current_key)

    def is_recording(self) -> bool:
        return self._recording

    def _toggle_recording(self) -> None:
        if self._recording:
            self._cancel_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        self._recording = True
        self.key_button.setProperty("recording", "true")
        self.key_button.setText("Press any key or combination (Esc to cancel)...")
        self.record_button.setText("Cancel")

    def _cancel_recording(self) -> None:
        self._recording = False
        self.key_button.setProperty("recording", "false")
        self.key_button.setText(self._current_key)
        self.record_button.setText("Capture Key")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._recording:
            super().keyPressEvent(event)
            return

        key = event.key()

        if key == Qt.Key.Key_Escape:
            self._cancel_recording()
            event.accept()
            return

        # Map pressed key/combination
        captured = self._map_key_event(event)
        if captured:
            self.set_key(captured)
            event.accept()
            return

        super().keyPressEvent(event)

    def _map_key_event(self, event: QKeyEvent) -> str | None:
        key = event.key()
        modifiers = event.modifiers()

        # Check combination Ctrl+Alt
        has_ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier) or key in (
            Qt.Key.Key_Control,
        )
        has_alt = bool(modifiers & Qt.KeyboardModifier.AltModifier) or key in (
            Qt.Key.Key_Alt,
            Qt.Key.Key_AltGr,
        )
        if has_ctrl and has_alt:
            return "Ctrl+Alt"

        # Super / Meta (Windows key)
        if key in (Qt.Key.Key_Meta, Qt.Key.Key_Super_L, Qt.Key.Key_Super_R):
            return "Super"

        # Right Alt (AltGr)
        if key == Qt.Key.Key_AltGr:
            return "Right Alt"

        # Right Ctrl vs Ctrl
        if key == Qt.Key.Key_Control:
            return "Ctrl"

        if key == Qt.Key.Key_Alt:
            return "Alt"

        if key == Qt.Key.Key_Shift:
            return "Shift"

        # Function keys (F1 - F12)
        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
            return f"F{key - Qt.Key.Key_F1 + 1}"

        text = event.text().strip().upper()
        if text:
            return text

        seq = QKeySequence(key).toString()
        if seq:
            return seq

        return None

    def _update_conflict_display(self) -> None:
        is_conflict, message = check_trigger_key_conflict(self._current_key)
        if is_conflict:
            self.warning_label.setText(message)
            self.warning_label.setFixedHeight(48)
            self.warning_label.setStyleSheet(
                "background-color: #3b2308; border: 1px solid #b45309; "
                "color: #fef3c7; border-radius: 6px; padding: 5px 10px; "
                "font-size: 8.5pt;"
            )
            self.warning_label.show()
        else:
            self.warning_label.setText(
                "✓ Safe trigger key with no desktop shortcut conflicts."
            )
            self.warning_label.setFixedHeight(28)
            self.warning_label.setStyleSheet(
                "background-color: #064e3b; border: 1px solid #059669; "
                "color: #d1fae5; border-radius: 6px; padding: 5px 10px; "
                "font-size: 8.5pt;"
            )
            self.warning_label.show()


class AddSizeDialog(QDialog):
    """Dialog to input and validate a new target size."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Target Size")
        self.setMinimumWidth(340)
        self.setStyleSheet(DARK_STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        label = QLabel("Enter size (e.g. 75 KB, 1.5 MB, 300000):")
        label.setStyleSheet("color: #e2e8f0; font-size: 9.5pt;")
        layout.addWidget(label)

        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("e.g. 75 KB")
        self.input_edit.textChanged.connect(self._validate_input)
        layout.addWidget(self.input_edit)

        self.preview_label = QLabel("Enter a size above")
        self.preview_label.setStyleSheet("color: #64748b; font-size: 8.5pt;")
        layout.addWidget(self.preview_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.add_btn = QPushButton("Add")
        self.add_btn.setProperty("class", "primaryButton")
        self.add_btn.setEnabled(False)
        self.add_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.add_btn)

        layout.addLayout(btn_row)
        self._parsed_bytes: int | None = None

    def _validate_input(self, text: str) -> None:
        text = text.strip()
        if not text:
            self.preview_label.setText("Enter a size above")
            self.preview_label.setStyleSheet("color: #64748b; font-size: 8.5pt;")
            self.add_btn.setEnabled(False)
            self._parsed_bytes = None
            return

        try:
            b = parse_size(text)
            if b <= 0:
                raise ValueError("Size must be positive")
            self._parsed_bytes = b
            formatted = format_size(b, spaced=True)
            self.preview_label.setText(f"✓ Parsed: {b:,} bytes ({formatted})")
            self.preview_label.setStyleSheet("color: #10b981; font-size: 8.5pt;")
            self.add_btn.setEnabled(True)
        except (ValueError, TypeError) as exc:
            self._parsed_bytes = None
            self.preview_label.setText(f"✗ Invalid: {exc}")
            self.preview_label.setStyleSheet("color: #f87171; font-size: 8.5pt;")
            self.add_btn.setEnabled(False)

    def get_size_bytes(self) -> int | None:
        return self._parsed_bytes


class SizeListEditor(QWidget):
    """List editor for target sizes with Add, Remove, and Reorder buttons."""

    sizes_changed = Signal()

    def __init__(
        self, initial_sizes: list[int] | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # List widget
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(120)
        self.list_widget.currentRowChanged.connect(self._update_button_states)
        layout.addWidget(self.list_widget, stretch=1)

        # Action buttons
        btn_col = QVBoxLayout()
        btn_col.setSpacing(6)

        self.add_btn = QPushButton("+ Add…")
        self.add_btn.clicked.connect(self._on_add)
        btn_col.addWidget(self.add_btn)

        self.remove_btn = QPushButton("− Remove")
        self.remove_btn.clicked.connect(self._on_remove)
        btn_col.addWidget(self.remove_btn)

        self.up_btn = QPushButton("▲ Move Up")
        self.up_btn.clicked.connect(self._on_move_up)
        btn_col.addWidget(self.up_btn)

        self.down_btn = QPushButton("▼ Move Down")
        self.down_btn.clicked.connect(self._on_move_down)
        btn_col.addWidget(self.down_btn)

        self.reset_btn = QPushButton("Reset Defaults")
        self.reset_btn.setStyleSheet("font-size: 8.5pt;")
        self.reset_btn.clicked.connect(self._on_reset)
        btn_col.addWidget(self.reset_btn)

        btn_col.addStretch()
        layout.addLayout(btn_col)

        default_sizes = initial_sizes or [
            20_000,
            50_000,
            100_000,
            200_000,
            500_000,
            1_000_000,
            2_000_000,
        ]
        self.set_sizes(default_sizes)

    def get_sizes(self) -> list[int]:
        sizes: list[int] = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            b = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(b, int) and b > 0:
                sizes.append(b)
        return sizes

    def set_sizes(self, sizes: list[int]) -> None:
        self.list_widget.clear()
        for b in sizes:
            self._append_size_item(b)
        self._update_button_states()

    def _append_size_item(self, b: int) -> None:
        formatted = format_size(b, spaced=True)
        text = f"{formatted}  ({b:,} B)"
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, b)
        self.list_widget.addItem(item)

    def _update_button_states(self) -> None:
        row = self.list_widget.currentRow()
        count = self.list_widget.count()

        self.remove_btn.setEnabled(row >= 0 and count > 1)
        self.up_btn.setEnabled(row > 0)
        self.down_btn.setEnabled(0 <= row < count - 1)

    def _on_add(self) -> None:
        dialog = AddSizeDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            b = dialog.get_size_bytes()
            if b is not None:
                self._append_size_item(b)
                self.list_widget.setCurrentRow(self.list_widget.count() - 1)
                self.sizes_changed.emit()

    def _on_remove(self) -> None:
        row = self.list_widget.currentRow()
        if row >= 0 and self.list_widget.count() > 1:
            self.list_widget.takeItem(row)
            new_row = min(row, self.list_widget.count() - 1)
            self.list_widget.setCurrentRow(new_row)
            self.sizes_changed.emit()

    def _on_move_up(self) -> None:
        row = self.list_widget.currentRow()
        if row > 0:
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row - 1, item)
            self.list_widget.setCurrentRow(row - 1)
            self.sizes_changed.emit()

    def _on_move_down(self) -> None:
        row = self.list_widget.currentRow()
        if 0 <= row < self.list_widget.count() - 1:
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row + 1, item)
            self.list_widget.setCurrentRow(row + 1)
            self.sizes_changed.emit()

    def _on_reset(self) -> None:
        self.set_sizes(
            [20_000, 50_000, 100_000, 200_000, 500_000, 1_000_000, 2_000_000]
        )
        self.sizes_changed.emit()


class OutputRulesWidget(QWidget):
    """Output location radio selection with folder picker."""

    def __init__(
        self,
        initial_mode: str = "next to original",
        initial_folder: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.btn_group = QButtonGroup(self)

        self.radio_original = QRadioButton("Save next to original file")
        self.btn_group.addButton(self.radio_original, 1)
        layout.addWidget(self.radio_original)

        sub_orig = QLabel(
            "Outputs photo_100KB.jpg in the same directory as the source file."
        )
        sub_orig.setProperty("class", "optionDesc")
        layout.addWidget(sub_orig)

        self.radio_fixed = QRadioButton("Save to fixed destination folder")
        self.btn_group.addButton(self.radio_fixed, 2)
        layout.addWidget(self.radio_fixed)

        # Folder picker row
        picker_row = QHBoxLayout()
        picker_row.setContentsMargins(22, 0, 0, 0)
        picker_row.setSpacing(6)

        self.folder_edit = QLineEdit(initial_folder)
        self.folder_edit.setPlaceholderText("Select folder...")
        picker_row.addWidget(self.folder_edit)

        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.clicked.connect(self._on_browse)
        picker_row.addWidget(self.browse_btn)

        layout.addLayout(picker_row)

        self.radio_original.toggled.connect(self._on_mode_toggled)

        mode_clean = initial_mode.strip().lower()
        if mode_clean in ("fixed folder", "fixed_folder"):
            self.radio_fixed.setChecked(True)
        else:
            self.radio_original.setChecked(True)

        self._on_mode_toggled()

    def _on_mode_toggled(self) -> None:
        fixed = self.radio_fixed.isChecked()
        self.folder_edit.setEnabled(fixed)
        self.browse_btn.setEnabled(fixed)

    def _on_browse(self) -> None:
        current = self.folder_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Select Output Folder", current)
        if chosen:
            self.folder_edit.setText(chosen)

    def get_output_mode(self) -> str:
        return "fixed folder" if self.radio_fixed.isChecked() else "next to original"

    def get_output_folder(self) -> str:
        return self.folder_edit.text().strip()

    def set_output_rules(self, mode: str, folder: str) -> None:
        self.folder_edit.setText(folder)
        if mode.strip().lower() in ("fixed folder", "fixed_folder"):
            self.radio_fixed.setChecked(True)
        else:
            self.radio_original.setChecked(True)
        self._on_mode_toggled()


class TogglesWidget(QWidget):
    """Checkboxes for engine and system options."""

    def __init__(
        self,
        keep_format: bool = True,
        allow_convert: bool = False,
        strip_metadata: bool = True,
        reduce_motion: bool = False,
        autostart: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 1. keep_format
        self.cb_keep_format = QCheckBox("Keep original format")
        self.cb_keep_format.setChecked(keep_format)
        layout.addWidget(self.cb_keep_format)
        desc1 = QLabel(
            "Preserve original file extension (e.g. keep PNG as PNG, WebP as WebP)."
        )
        desc1.setProperty("class", "optionDesc")
        layout.addWidget(desc1)

        # 2. allow_convert
        self.cb_allow_convert = QCheckBox("Allow format conversion")
        self.cb_allow_convert.setChecked(allow_convert)
        layout.addWidget(self.cb_allow_convert)
        desc2 = QLabel(
            "Allow fallback from PNG to JPEG when target size cannot be reached."
        )
        desc2.setProperty("class", "optionDesc")
        layout.addWidget(desc2)

        # 3. strip_metadata
        self.cb_strip_metadata = QCheckBox("Strip metadata && GPS tags")
        self.cb_strip_metadata.setChecked(strip_metadata)
        layout.addWidget(self.cb_strip_metadata)
        desc3 = QLabel(
            "Remove camera details, location tags, and EXIF metadata for privacy."
        )
        desc3.setProperty("class", "optionDesc")
        layout.addWidget(desc3)

        # 4. reduce_motion
        self.cb_reduce_motion = QCheckBox("Reduce motion")
        self.cb_reduce_motion.setChecked(reduce_motion)
        layout.addWidget(self.cb_reduce_motion)
        desc4 = QLabel(
            "Disable donut fan-out and pulse animations, use instant transitions."
        )
        desc4.setProperty("class", "optionDesc")
        layout.addWidget(desc4)

        # 5. autostart
        self.cb_autostart = QCheckBox("Start at login (autostart daemon)")
        self.cb_autostart.setChecked(autostart)
        layout.addWidget(self.cb_autostart)
        desc5 = QLabel(
            "Automatically launch smol shortcut listener daemon on desktop login."
        )
        desc5.setProperty("class", "optionDesc")
        layout.addWidget(desc5)

    def get_toggles(self) -> dict[str, bool]:
        return {
            "keep_format": self.cb_keep_format.isChecked(),
            "allow_convert": self.cb_allow_convert.isChecked(),
            "strip_metadata": self.cb_strip_metadata.isChecked(),
            "reduce_motion": self.cb_reduce_motion.isChecked(),
            "autostart": self.cb_autostart.isChecked(),
        }

    def set_toggles(
        self,
        keep_format: bool,
        allow_convert: bool,
        strip_metadata: bool,
        reduce_motion: bool,
        autostart: bool,
    ) -> None:
        self.cb_keep_format.setChecked(keep_format)
        self.cb_allow_convert.setChecked(allow_convert)
        self.cb_strip_metadata.setChecked(strip_metadata)
        self.cb_reduce_motion.setChecked(reduce_motion)
        self.cb_autostart.setChecked(autostart)


class SettingsWindow(QWidget):
    """Main PySide6 settings window for smol."""

    saved = Signal(object)  # Emits SmolConfig on successful save

    def __init__(
        self,
        config_path: Path | str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config_path = config_path
        self.setObjectName("settingsRoot")
        self.setWindowTitle("smol settings")
        self.setMinimumSize(520, 560)
        self.resize(580, 850)
        self.setStyleSheet(DARK_STYLESHEET)

        # Load initial config
        self._config = load_config(self.config_path)

        # Check real autostart integration status if available
        autostart_installed = AutostartIntegrator().status().installed
        autostart_val = self._config.autostart or autostart_installed

        # Main window layout
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(10)

        # Header
        header_row = QVBoxLayout()
        header_row.setSpacing(3)
        title_label = QLabel("smol settings")
        title_label.setStyleSheet("color: #f8fafc; font-size: 16pt; font-weight: 800;")
        header_row.addWidget(title_label)

        sub_label = QLabel(
            "Configure shortcut trigger, target sizes, output rules, and behavior."
        )
        sub_label.setStyleSheet("color: #94a3b8; font-size: 9.5pt;")
        header_row.addWidget(sub_label)
        root_layout.addLayout(header_row)

        # Scroll area for clean responsive scaling
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_widget.setObjectName("scrollContainer")
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 4, 8, 4)
        scroll_layout.setSpacing(10)

        # 1. Trigger Key Section
        key_frame = QFrame()
        key_frame.setProperty("class", "cardFrame")
        key_layout = QVBoxLayout(key_frame)
        key_layout.setSpacing(8)

        sec_key_title = QLabel("Trigger Key")
        sec_key_title.setProperty("class", "sectionTitle")
        key_layout.addWidget(sec_key_title)

        sec_key_sub = QLabel("Held while dragging files to summon the donut overlay.")
        sec_key_sub.setProperty("class", "subText")
        key_layout.addWidget(sec_key_sub)

        self.key_capture = TriggerKeyCaptureWidget(self._config.trigger_key)
        key_layout.addWidget(self.key_capture)
        scroll_layout.addWidget(key_frame)

        # 2. Target Sizes Section
        sizes_frame = QFrame()
        sizes_frame.setProperty("class", "cardFrame")
        sizes_layout = QVBoxLayout(sizes_frame)
        sizes_layout.setSpacing(8)

        sec_sizes_title = QLabel("Target Sizes")
        sec_sizes_title.setProperty("class", "sectionTitle")
        sizes_layout.addWidget(sec_sizes_title)

        sec_sizes_sub = QLabel(
            "Available sizes displayed in the donut ring (drag files onto segments)."
        )
        sec_sizes_sub.setProperty("class", "subText")
        sizes_layout.addWidget(sec_sizes_sub)

        self.size_editor = SizeListEditor(self._config.sizes)
        sizes_layout.addWidget(self.size_editor)
        scroll_layout.addWidget(sizes_frame)

        # 3. Output Rules Section
        out_frame = QFrame()
        out_frame.setProperty("class", "cardFrame")
        out_layout = QVBoxLayout(out_frame)
        out_layout.setSpacing(8)

        sec_out_title = QLabel("Output Location")
        sec_out_title.setProperty("class", "sectionTitle")
        out_layout.addWidget(sec_out_title)

        sec_out_sub = QLabel(
            "Rules for destination directory where shrunk files are saved."
        )
        sec_out_sub.setProperty("class", "subText")
        out_layout.addWidget(sec_out_sub)

        self.output_rules = OutputRulesWidget(
            self._config.output_mode, self._config.output_folder
        )
        out_layout.addWidget(self.output_rules)
        scroll_layout.addWidget(out_frame)

        # 4. Toggles Section
        toggles_frame = QFrame()
        toggles_frame.setProperty("class", "cardFrame")
        toggles_layout = QVBoxLayout(toggles_frame)
        toggles_layout.setSpacing(8)

        sec_toggles_title = QLabel("Options & Behavior")
        sec_toggles_title.setProperty("class", "sectionTitle")
        toggles_layout.addWidget(sec_toggles_title)

        sec_toggles_sub = QLabel(
            "Compression format rules, privacy, animation, and startup behavior."
        )
        sec_toggles_sub.setProperty("class", "subText")
        toggles_layout.addWidget(sec_toggles_sub)

        self.toggles_widget = TogglesWidget(
            keep_format=self._config.keep_format,
            allow_convert=self._config.allow_convert,
            strip_metadata=self._config.strip_metadata,
            reduce_motion=self._config.reduce_motion,
            autostart=autostart_val,
        )
        toggles_layout.addWidget(self.toggles_widget)
        scroll_layout.addWidget(toggles_frame)

        scroll.setWidget(scroll_widget)
        root_layout.addWidget(scroll, stretch=1)

        # Status / validation message banner
        self.status_banner = QLabel("")
        self.status_banner.setWordWrap(True)
        self.status_banner.hide()
        root_layout.addWidget(self.status_banner)

        # Footer actions
        footer_row = QHBoxLayout()
        footer_row.setSpacing(10)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.close)
        footer_row.addWidget(self.cancel_btn)

        footer_row.addStretch()

        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setProperty("class", "primaryButton")
        self.save_btn.clicked.connect(self.save)
        footer_row.addWidget(self.save_btn)

        root_layout.addLayout(footer_row)

    def validate(self) -> tuple[bool, str]:
        """Validate all current settings before saving."""
        # 1. Trigger key
        key = self.key_capture.get_key()
        if not key or not key.strip():
            return False, "Trigger key cannot be empty. Please select or record a key."

        # 2. Sizes
        sizes = self.size_editor.get_sizes()
        if not sizes:
            return (
                False,
                "Target sizes list cannot be empty. At least one size is required.",
            )
        if any(s <= 0 for s in sizes):
            return False, "All target sizes must be positive byte values."

        # 3. Output rules
        mode = self.output_rules.get_output_mode()
        if mode == "fixed folder":
            folder = self.output_rules.get_output_folder()
            if not folder:
                return (
                    False,
                    (
                        "Please select an existing output directory or choose "
                        "'Save next to original file'."
                    ),
                )
            p = Path(folder).expanduser().resolve()
            if not p.exists():
                return False, f"Selected output folder does not exist: {folder}"
            if not p.is_dir():
                return False, f"Selected output path is not a directory: {folder}"
            if not os.access(p, os.W_OK):
                return False, f"Selected output directory is not writable: {folder}"

        return True, ""

    def save(self) -> bool:
        """Validate and persist settings to config.toml and sync autostart."""
        valid, err_msg = self.validate()
        if not valid:
            self.status_banner.setText(f"✗ {err_msg}")
            self.status_banner.setStyleSheet(
                "background-color: #3b1818; border: 1px solid #ef4444; "
                "color: #fecaca; border-radius: 6px; padding: 8px 12px; "
                "font-size: 9pt; font-weight: 500;"
            )
            self.status_banner.show()
            return False

        # Gather updated values
        key = self.key_capture.get_key()
        sizes = self.size_editor.get_sizes()
        mode = self.output_rules.get_output_mode()
        folder = self.output_rules.get_output_folder()
        toggles = self.toggles_widget.get_toggles()

        updated_config = SmolConfig(
            trigger_key=key,
            sizes=sizes,
            output_mode=mode,
            output_folder=folder,
            naming_pattern=self._config.naming_pattern,
            keep_format=toggles["keep_format"],
            allow_convert=toggles["allow_convert"],
            strip_metadata=toggles["strip_metadata"],
            min_side=self._config.min_side,
            reduce_motion=toggles["reduce_motion"],
            theme=self._config.theme,
            autostart=toggles["autostart"],
            custom_sizes=self._config.custom_sizes,
        )

        save_config(updated_config, self.config_path)
        self._config = updated_config

        # Synchronize autostart desktop entry
        integrator = AutostartIntegrator()
        if toggles["autostart"]:
            integrator.install()
        else:
            integrator.uninstall()

        self.status_banner.setText("✓ Settings saved successfully.")
        self.status_banner.setStyleSheet(
            "background-color: #064e3b; border: 1px solid #10b981; "
            "color: #d1fae5; border-radius: 6px; padding: 8px 12px; "
            "font-size: 9pt; font-weight: 600;"
        )
        self.status_banner.show()
        self.saved.emit(updated_config)
        return True

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle Esc key to cancel recording or close window."""
        if self.key_capture.is_recording():
            self.key_capture.keyPressEvent(event)
            return

        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return

        super().keyPressEvent(event)
