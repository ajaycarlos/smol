import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from smol.ui.custom_input import CustomInputDialog


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_custom_input_confirm_kb(app):
    dialog = CustomInputDialog()
    confirmed_val = []
    dialog.confirmed.connect(lambda val: confirmed_val.append(val))

    # Type 75 into input
    dialog.line_edit.setText("75")
    # Unit defaults to KB
    assert dialog.unit == "KB"

    # Confirm with Enter key
    QTest.keyClick(dialog.line_edit, Qt.Key.Key_Return)

    assert confirmed_val == [75_000]
    assert not dialog.isVisible()


def test_custom_input_confirm_mb(app):
    dialog = CustomInputDialog()
    confirmed_val = []
    dialog.confirmed.connect(lambda val: confirmed_val.append(val))

    dialog.line_edit.setText("2.5")
    dialog.set_unit("MB")
    assert dialog.unit == "MB"

    QTest.keyClick(dialog.line_edit, Qt.Key.Key_Return)

    assert confirmed_val == [2_500_000]
    assert not dialog.isVisible()


def test_custom_input_toggle_unit(app):
    dialog = CustomInputDialog()
    assert dialog.unit == "KB"

    # Click toggle button
    QTest.mouseClick(dialog.unit_toggle_btn, Qt.MouseButton.LeftButton)
    assert dialog.unit == "MB"

    QTest.mouseClick(dialog.unit_toggle_btn, Qt.MouseButton.LeftButton)
    assert dialog.unit == "KB"


def test_custom_input_validation_zero(app):
    dialog = CustomInputDialog()
    confirmed_val = []
    dialog.confirmed.connect(lambda val: confirmed_val.append(val))

    dialog.line_edit.setText("0")
    QTest.keyClick(dialog.line_edit, Qt.Key.Key_Return)

    # Must reject zero
    assert len(confirmed_val) == 0
    assert dialog.has_error()


def test_custom_input_validation_negative(app):
    dialog = CustomInputDialog()
    confirmed_val = []
    dialog.confirmed.connect(lambda val: confirmed_val.append(val))

    dialog.line_edit.setText("-10")
    QTest.keyClick(dialog.line_edit, Qt.Key.Key_Return)

    # Must reject negative
    assert len(confirmed_val) == 0
    assert dialog.has_error()


def test_custom_input_validation_empty_or_non_numeric(app):
    dialog = CustomInputDialog()
    confirmed_val = []
    dialog.confirmed.connect(lambda val: confirmed_val.append(val))

    dialog.line_edit.setText("")
    QTest.keyClick(dialog.line_edit, Qt.Key.Key_Return)
    assert len(confirmed_val) == 0
    assert dialog.has_error()

    dialog.line_edit.setText("abc")
    QTest.keyClick(dialog.line_edit, Qt.Key.Key_Return)
    assert len(confirmed_val) == 0
    assert dialog.has_error()


def test_custom_input_esc_cancels(app):
    dialog = CustomInputDialog()
    dialog.show()
    cancelled_called = []
    dialog.cancelled.connect(lambda: cancelled_called.append(True))

    QTest.keyClick(dialog, Qt.Key.Key_Escape)

    assert cancelled_called == [True]
    assert not dialog.isVisible()


def test_custom_input_position_near(app):
    dialog = CustomInputDialog()
    anchor = QPoint(300, 400)
    dialog.position_near(anchor)

    # Ensure dialog is positioned in the vicinity of anchor
    rect = dialog.geometry()
    # Distance between dialog center and anchor should be reasonable (< 200px)
    center = rect.center()
    dx = center.x() - anchor.x()
    dy = center.y() - anchor.y()
    assert (dx**2 + dy**2) ** 0.5 < 250


def test_custom_input_floor_validation(app):
    """Typing a size below estimated floor displays the exact honest failure message."""
    dialog = CustomInputDialog(floor_bytes=14_000)
    confirmed_val = []
    dialog.confirmed.connect(lambda val: confirmed_val.append(val))

    # Type 10 KB (< 14 KB floor)
    dialog.line_edit.setText("10")
    QTest.keyClick(dialog.line_edit, Qt.Key.Key_Return)

    assert len(confirmed_val) == 0
    assert dialog.has_error()
    assert dialog.error_label.text() == "Smallest I can make this is about 14 KB"

    # Type 14 KB (== floor) -> accepts
    dialog.line_edit.setText("14")
    QTest.keyClick(dialog.line_edit, Qt.Key.Key_Return)
    assert confirmed_val == [14_000]


def test_custom_input_lists_pinned_and_recents_and_arrow_keys(app, tmp_path):
    """Custom popup lists favourites and recents and supports arrow keys + Enter."""
    from smol.config import SmolConfig, save_config

    cfg_file = tmp_path / "config.toml"
    cfg = SmolConfig()
    cfg.sizes.pinned = [120_000]
    cfg.sizes.recents = [85_000, 250_000]
    save_config(cfg, cfg_file)

    dialog = CustomInputDialog(config_path=cfg_file)
    confirmed_val = []
    dialog.confirmed.connect(lambda val: confirmed_val.append(val))

    assert hasattr(dialog, "items_list")
    # Pinned and recents should be in the list
    list_items = [
        dialog.items_list.item(i).text() for i in range(dialog.items_list.count())
    ]
    assert any("120 KB" in t for t in list_items)
    assert any("85 KB" in t for t in list_items)

    # Press Down arrow from line_edit into list
    QTest.keyClick(dialog.line_edit, Qt.Key.Key_Down)
    assert dialog.items_list.currentRow() >= 0

    # Press Enter to pick the selected item
    QTest.keyClick(dialog.items_list, Qt.Key.Key_Return)
    assert len(confirmed_val) == 1
    assert confirmed_val[0] in (120_000, 85_000, 250_000)


def test_custom_input_records_into_recents(app, tmp_path):
    """Picked custom size is recorded into sizes.recents with 5% deduplication."""
    from smol.config import SmolConfig, load_config, save_config

    cfg_file = tmp_path / "config.toml"
    cfg = SmolConfig()
    cfg.sizes.recents = [200_000]
    save_config(cfg, cfg_file)

    dialog = CustomInputDialog(config_path=cfg_file)
    dialog.line_edit.setText("75")
    QTest.keyClick(dialog.line_edit, Qt.Key.Key_Return)

    reloaded = load_config(cfg_file)
    assert reloaded.sizes.recents[0] == 75_000
    assert 200_000 in reloaded.sizes.recents
