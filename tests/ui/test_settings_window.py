"""Unit and UI tests for smol settings window."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from smol.config import load_config
from smol.ui.settings_window import (
    AddSizeDialog,
    OutputRulesWidget,
    SettingsWindow,
    SizeListEditor,
    TogglesWidget,
    TriggerKeyCaptureWidget,
    check_trigger_key_conflict,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_trigger_key_conflict_detection():
    """Verify conflict warnings for Ctrl, Shift, Alt, and safe keys."""
    # Conflicts
    is_conflict, msg = check_trigger_key_conflict("Ctrl")
    assert is_conflict
    assert "Copy" in msg

    is_conflict, msg = check_trigger_key_conflict("Control")
    assert is_conflict
    assert "Copy" in msg

    is_conflict, msg = check_trigger_key_conflict("Shift")
    assert is_conflict
    assert "Move" in msg

    is_conflict, msg = check_trigger_key_conflict("Alt")
    assert is_conflict
    assert "window movement" in msg

    # Safe keys
    is_conflict, msg = check_trigger_key_conflict("Super")
    assert not is_conflict
    assert msg == ""

    is_conflict, msg = check_trigger_key_conflict("Ctrl+Alt")
    assert not is_conflict
    assert msg == ""

    is_conflict, msg = check_trigger_key_conflict("Right Alt")
    assert not is_conflict

    is_conflict, msg = check_trigger_key_conflict("Right Ctrl")
    assert not is_conflict


def test_trigger_key_capture_widget(qapp):
    """Test TriggerKeyCaptureWidget key recording, presets, and conflict display."""
    widget = TriggerKeyCaptureWidget(initial_key="Super")
    try:
        assert widget.get_key() == "Super"
        assert not widget.is_recording()
        assert "Safe trigger key" in widget.warning_label.text()

        # Switch to Ctrl (should show conflict warning)
        widget.set_key("Ctrl")
        assert widget.get_key() == "Ctrl"
        assert not widget.warning_label.isHidden()
        assert "Copy" in widget.warning_label.text()

        # Switch to Ctrl+Alt (safe)
        widget.set_key("Ctrl+Alt")
        assert widget.get_key() == "Ctrl+Alt"
        assert "Safe trigger key" in widget.warning_label.text()

        # Start recording and press Super key
        widget._start_recording()
        assert widget.is_recording()
        assert "Press any key" in widget.key_button.text()

        # Simulate key event for Meta/Super
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Meta,
            Qt.KeyboardModifier.NoModifier,
        )
        widget.keyPressEvent(event)
        assert not widget.is_recording()
        assert widget.get_key() == "Super"

        # Start recording and cancel with Escape
        widget._start_recording()
        assert widget.is_recording()
        esc_event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Escape,
            Qt.KeyboardModifier.NoModifier,
        )
        widget.keyPressEvent(esc_event)
        assert not widget.is_recording()
        assert widget.get_key() == "Super"
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def test_add_size_dialog_validation(qapp):
    """Test AddSizeDialog parses sizes and rejects invalid input."""
    dialog = AddSizeDialog()
    try:
        # Initially empty
        assert not dialog.add_btn.isEnabled()
        assert dialog.get_size_bytes() is None

        # Enter valid size
        dialog.input_edit.setText("75 KB")
        assert dialog.add_btn.isEnabled()
        assert dialog.get_size_bytes() == 75_000
        assert "75,000 bytes" in dialog.preview_label.text()

        # Enter another valid size in MB
        dialog.input_edit.setText("1.5 MB")
        assert dialog.add_btn.isEnabled()
        assert dialog.get_size_bytes() == 1_500_000

        # Enter invalid text
        dialog.input_edit.setText("invalid-size")
        assert not dialog.add_btn.isEnabled()
        assert dialog.get_size_bytes() is None
        assert "Invalid" in dialog.preview_label.text()
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_size_list_editor(qapp):
    """Test SizeListEditor adding, removing, and reordering sizes."""
    editor = SizeListEditor([50_000, 100_000, 200_000])
    try:
        assert editor.get_sizes() == [50_000, 100_000, 200_000]

        # Select first item: move up disabled, move down enabled
        editor.list_widget.setCurrentRow(0)
        assert not editor.up_btn.isEnabled()
        assert editor.down_btn.isEnabled()

        # Move down
        editor._on_move_down()
        assert editor.get_sizes() == [100_000, 50_000, 200_000]
        assert editor.list_widget.currentRow() == 1

        # Move up
        editor._on_move_up()
        assert editor.get_sizes() == [50_000, 100_000, 200_000]
        assert editor.list_widget.currentRow() == 0

        # Remove item
        editor.list_widget.setCurrentRow(1)
        editor._on_remove()
        assert editor.get_sizes() == [50_000, 200_000]

        # Reset defaults
        editor._on_reset()
        assert editor.get_sizes() == [
            20_000,
            50_000,
            100_000,
            200_000,
            500_000,
            1_000_000,
            2_000_000,
        ]
    finally:
        editor.close()
        editor.deleteLater()
        qapp.processEvents()


def test_output_rules_widget(qapp, tmp_path: Path):
    """Test OutputRulesWidget toggle and folder selection."""
    widget = OutputRulesWidget(initial_mode="next to original", initial_folder="")
    try:
        assert widget.get_output_mode() == "next to original"
        assert not widget.folder_edit.isEnabled()
        assert not widget.browse_btn.isEnabled()

        # Switch to fixed folder
        widget.radio_fixed.setChecked(True)
        assert widget.get_output_mode() == "fixed folder"
        assert widget.folder_edit.isEnabled()
        assert widget.browse_btn.isEnabled()

        target_dir = str(tmp_path / "custom_output")
        widget.folder_edit.setText(target_dir)
        assert widget.get_output_folder() == target_dir

        # Programmatic setter
        widget.set_output_rules("next to original", "")
        assert widget.get_output_mode() == "next to original"
        assert not widget.folder_edit.isEnabled()
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def test_toggles_widget(qapp):
    """Test TogglesWidget reading and setting values."""
    widget = TogglesWidget(
        keep_format=True,
        allow_convert=False,
        strip_metadata=True,
        reduce_motion=False,
        autostart=True,
    )
    try:
        t = widget.get_toggles()
        assert t["keep_format"] is True
        assert t["allow_convert"] is False
        assert t["strip_metadata"] is True
        assert t["reduce_motion"] is False
        assert t["autostart"] is True

        widget.set_toggles(
            keep_format=False,
            allow_convert=True,
            strip_metadata=False,
            reduce_motion=True,
            autostart=False,
        )
        t2 = widget.get_toggles()
        assert t2["keep_format"] is False
        assert t2["allow_convert"] is True
        assert t2["strip_metadata"] is False
        assert t2["reduce_motion"] is True
        assert t2["autostart"] is False
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def test_settings_window_validation_and_save(qapp, tmp_path: Path):
    """Test SettingsWindow validates bad inputs and saves good inputs."""
    cfg_file = tmp_path / "config.toml"
    window = SettingsWindow(config_path=cfg_file)
    try:
        # 1. Validation error: empty trigger key
        window.key_capture.set_key("")
        assert not window.save()
        assert "Trigger key cannot be empty" in window.status_banner.text()

        # Restore valid key
        window.key_capture.set_key("Ctrl+Alt")

        # 2. Validation error: fixed folder without path or nonexistent
        window.output_rules.radio_fixed.setChecked(True)
        window.output_rules.folder_edit.setText("")
        assert not window.save()
        assert "select an existing output directory" in window.status_banner.text()

        nonexistent_dir = tmp_path / "nonexistent_subfolder"
        window.output_rules.folder_edit.setText(str(nonexistent_dir))
        assert not window.save()
        assert "does not exist" in window.status_banner.text()

        # Valid folder
        valid_dir = tmp_path / "valid_folder"
        valid_dir.mkdir()
        window.output_rules.folder_edit.setText(str(valid_dir))

        # Configure custom sizes
        window.size_editor.set_sizes([75_000, 150_000])

        # Toggle options
        window.toggles_widget.cb_reduce_motion.setChecked(True)
        window.toggles_widget.cb_allow_convert.setChecked(True)
        window.toggles_widget.cb_autostart.setChecked(False)

        # Mock autostart integrator so tests do not touch ~/.config/autostart
        with patch("smol.ui.settings_window.AutostartIntegrator") as mock_auto_cls:
            mock_integrator = MagicMock()
            mock_auto_cls.return_value = mock_integrator

            assert window.save()
            mock_integrator.uninstall.assert_called_once()

        assert "✓ Settings saved" in window.status_banner.text()
        assert cfg_file.exists()

        # Verify saved file contents
        loaded = load_config(cfg_file)
        assert loaded.trigger_key == "Ctrl+Alt"
        assert loaded.sizes == [75_000, 150_000]
        assert loaded.output_mode == "fixed folder"
        assert loaded.output_folder == str(valid_dir)
        assert loaded.reduce_motion is True
        assert loaded.allow_convert is True
        assert loaded.autostart is False
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_settings_window_ladder_editor_max_7(qapp, tmp_path):
    """Test ladder editor limits entries to max 7 and validates correctly."""
    cfg_file = tmp_path / "config.toml"
    window = SettingsWindow(config_path=cfg_file)
    try:
        # Default ladder has 7 entries
        assert len(window.ladder_editor.get_sizes()) == 7
        assert window.ladder_editor.add_btn.isEnabled() is False

        # Remove an entry -> now 6 entries -> Add button should be enabled
        window.ladder_editor.list_widget.setCurrentRow(0)
        window.ladder_editor._on_remove()
        assert len(window.ladder_editor.get_sizes()) == 6
        assert window.ladder_editor.add_btn.isEnabled() is True

        # Validation succeeds with 6 entries
        valid, msg = window.validate()
        assert valid is True

        # If set to more than 7 entries, validation fails
        window.ladder_editor.set_sizes([10_000 * i for i in range(1, 9)])
        assert len(window.ladder_editor.get_sizes()) == 8
        valid, msg = window.validate()
        assert valid is False
        assert "cannot exceed 7" in msg
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_settings_window_favourites_editor_max_12(qapp, tmp_path):
    """Test favourites editor limits entries to max 12 and validates correctly."""
    cfg_file = tmp_path / "config.toml"
    window = SettingsWindow(config_path=cfg_file)
    try:
        assert window.favourites_editor.allow_empty is True
        assert len(window.favourites_editor.get_sizes()) == 0
        assert window.favourites_editor.add_btn.isEnabled() is True

        # Set 12 favourites -> Add button disabled
        twelve = [10_000 * i for i in range(1, 13)]
        window.favourites_editor.set_sizes(twelve)
        assert len(window.favourites_editor.get_sizes()) == 12
        assert window.favourites_editor.add_btn.isEnabled() is False

        valid, msg = window.validate()
        assert valid is True

        # Set 13 favourites -> validation fails
        thirteen = [10_000 * i for i in range(1, 14)]
        window.favourites_editor.set_sizes(thirteen)
        valid, msg = window.validate()
        assert valid is False
        assert "cannot exceed 12" in msg
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_settings_window_ring_mode_switch_and_persistence(qapp, tmp_path):
    """Test ring mode toggle between Classic and Smart ring and saving."""
    cfg_file = tmp_path / "config.toml"
    window = SettingsWindow(config_path=cfg_file)
    try:
        assert window.ring_mode_widget.get_mode() == "classic"

        # Switch to smart ring
        window.ring_mode_widget.set_mode("smart")
        assert window.ring_mode_widget.get_mode() == "smart"

        # Set pinned favourites
        window.favourites_editor.set_sizes([45_000, 90_000])

        with patch("smol.ui.settings_window.AutostartIntegrator"):
            assert window.save()

        # Reload from disk and verify
        loaded = load_config(cfg_file)
        assert loaded.suggest.mode == "smart"
        assert loaded.sizes.pinned == [45_000, 90_000]
        assert len(loaded.sizes.ladder) == 7
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_settings_window_ladder_change_syncs_right_click_actions(qapp, tmp_path):
    """Test saving modified ladder in Settings regenerates actions or shows hint."""
    cfg_file = tmp_path / "config.toml"
    window = SettingsWindow(config_path=cfg_file)
    try:
        # Change ladder sizes in editor
        window.ladder_editor.set_sizes([30_000, 60_000, 120_000])

        with patch("smol.ui.settings_window.AutostartIntegrator"):
            saved = window.save()
            assert saved is True

        banner_text = window.status_banner.text()
        assert "Settings saved" in banner_text
        assert (
            "Right-click actions regenerated" in banner_text
            or "re-run 'smol integrate install'" in banner_text.lower()
        )
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()

