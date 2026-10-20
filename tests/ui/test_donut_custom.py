from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from smol.core.config import get_custom_sizes, save_config
from smol.ui.donut_window import DonutWindow


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_donut_loads_custom_sizes_from_config(app, tmp_path: Path):
    sample = tmp_path / "test.jpg"
    sample.write_bytes(b"x" * 200_000)

    config_file = tmp_path / "config.toml"
    save_config({"custom_sizes": [75_000, 150_000]}, config_file)

    donut = DonutWindow(files=[sample], config_path=config_file)
    # D-007: Maximum 8 segments including Custom…; custom sizes live in Custom dialog
    assert len(donut.segments) <= 8
    assert donut.segments[-1].label == "Custom…"

    from smol.ui.custom_input import CustomInputDialog

    dialog = CustomInputDialog(config_path=config_file)
    items = [
        dialog.items_list.item(i).text() for i in range(dialog.items_list.count())
    ]
    assert any("75 KB" in it or "150 KB" in it for it in items)

    dialog.close()
    donut.close()


def test_donut_click_custom_opens_dialog_and_shrinks(app, tmp_path: Path, monkeypatch):
    sample = tmp_path / "test.jpg"
    sample.write_bytes(b"x" * 200_000)

    config_file = tmp_path / "config.toml"
    save_config({"custom_sizes": []}, config_file)

    donut = DonutWindow(files=[sample], config_path=config_file)
    donut.show()

    shrink_started = []
    original_start_shrink = donut.start_shrink

    def mock_start_shrink(target_bytes, files=None):
        shrink_started.append(target_bytes)
        original_start_shrink(target_bytes, files)

    monkeypatch.setattr(donut, "start_shrink", mock_start_shrink)

    # Find index of "Custom…" segment
    custom_idx = next(i for i, s in enumerate(donut.segments) if s.label == "Custom…")
    anchor_x, anchor_y = donut.geometry_calc.segments[custom_idx].label_anchor
    center = donut.rect().center()
    click_pos = center + QPointF(anchor_x, anchor_y).toPoint()

    # Click Custom… segment
    QTest.mouseClick(
        donut, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click_pos
    )

    # Custom input dialog should now be open
    dialog = donut._custom_dialog
    assert dialog is not None
    assert dialog.isVisible()

    # Enter 85 KB and confirm
    dialog.line_edit.setText("85")
    QTest.keyClick(dialog.line_edit, Qt.Key.Key_Return)

    assert shrink_started == [85_000]
    # Config file should remember 85_000
    assert get_custom_sizes(config_file) == [85_000]

    donut.close()


def test_donut_drop_on_custom_opens_dialog(app, tmp_path: Path, monkeypatch):
    sample = tmp_path / "dropped.jpg"
    sample.write_bytes(b"x" * 300_000)

    config_file = tmp_path / "config.toml"
    save_config({"custom_sizes": []}, config_file)

    donut = DonutWindow(files=[], config_path=config_file)
    donut.show()

    custom_idx = next(i for i, s in enumerate(donut.segments) if s.label == "Custom…")
    anchor_x, anchor_y = donut.geometry_calc.segments[custom_idx].label_anchor
    center = donut.rect().center()
    drop_pos = center + QPointF(anchor_x, anchor_y).toPoint()

    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile(str(sample))])
    drop_event = QDropEvent(
        QPointF(drop_pos),
        Qt.DropAction.CopyAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    donut.dropEvent(drop_event)

    # Dialog should be opened and pending dropped files stored
    dialog = donut._custom_dialog
    assert dialog is not None
    assert dialog.isVisible()
    assert donut._pending_custom_files == [sample]

    shrink_started = []
    monkeypatch.setattr(
        donut,
        "start_shrink",
        lambda tb, files=None: shrink_started.append((tb, files)),
    )

    # Confirm 1.2 MB
    dialog.line_edit.setText("1.2")
    dialog.set_unit("MB")
    QTest.keyClick(dialog.line_edit, Qt.Key.Key_Return)

    assert len(shrink_started) == 1
    target_bytes, files = shrink_started[0]
    assert target_bytes == 1_200_000
    assert files == [sample]
    assert get_custom_sizes(config_file) == [1_200_000]

    donut.close()


def test_donut_custom_cancel_no_shrink(app, tmp_path: Path, monkeypatch):
    sample = tmp_path / "test.jpg"
    sample.write_bytes(b"x" * 200_000)

    config_file = tmp_path / "config.toml"
    donut = DonutWindow(files=[sample], config_path=config_file)
    donut.show()

    shrink_started = []
    monkeypatch.setattr(
        donut, "start_shrink", lambda tb, files=None: shrink_started.append(tb)
    )

    custom_idx = next(i for i, s in enumerate(donut.segments) if s.label == "Custom…")
    anchor_x, anchor_y = donut.geometry_calc.segments[custom_idx].label_anchor
    center = donut.rect().center()
    click_pos = center + QPointF(anchor_x, anchor_y).toPoint()

    QTest.mouseClick(
        donut, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click_pos
    )

    dialog = donut._custom_dialog
    assert dialog is not None
    assert dialog.isVisible()

    # Cancel via Esc
    QTest.keyClick(dialog, Qt.Key.Key_Escape)

    assert not dialog.isVisible()
    assert len(shrink_started) == 0

    donut.close()
