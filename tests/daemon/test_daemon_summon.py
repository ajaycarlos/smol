"""Integration tests for daemon summoning, drop execution, dismissal, and logging."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPoint, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

from smol.daemon.listener import (
    ListenerCoordinator,
    SummonMode,
)
from smol.daemon.service import DaemonService, get_log_path
from smol.ui.donut_window import DonutWindow


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def test_image_file(tmp_path: Path) -> Path:
    f = tmp_path / "sample.jpg"
    # Create simple valid JPEG
    from PIL import Image

    img = Image.new("RGB", (300, 300), color="blue")
    img.save(f, format="JPEG", quality=90)
    return f


def test_daemon_path_a_summon_and_key_release_dismiss(qapp: QApplication) -> None:
    donut = DonutWindow(files=[])
    summon_coords: list[tuple[int | None, int | None]] = []
    dismiss_reasons: list[str] = []

    def on_summon(x: int | None, y: int | None) -> None:
        summon_coords.append((x, y))
        donut.center_at(x, y)
        donut.show()

    def on_dismiss(reason: str) -> None:
        dismiss_reasons.append(reason)
        donut.hide()
        donut.reset_state()

    coordinator = ListenerCoordinator(
        mode=SummonMode.PATH_A,
        target_key="Super",
        on_summon=on_summon,
        on_dismiss=on_dismiss,
    )

    # 1. Press Super -> Path A does NOT summon yet
    coordinator.on_key_down("Super")
    assert len(summon_coords) == 0
    assert coordinator.is_donut_visible is False

    # 2. Drag starts at (450, 350) -> summons donut
    coordinator.on_drag_start(450, 350)
    assert len(summon_coords) == 1
    assert summon_coords[0] == (450, 350)
    assert coordinator.is_donut_visible is True
    assert donut.isVisible() is True

    # 3. Release Super without dropping -> dismisses donut
    coordinator.on_key_up("Super", held_ms=250.0)
    assert len(dismiss_reasons) == 1
    assert dismiss_reasons[0] == "key_release"
    assert coordinator.is_donut_visible is False
    assert donut.isVisible() is False

    donut.close()


def test_daemon_path_c_summon_and_esc_dismiss(qapp: QApplication) -> None:
    donut = DonutWindow(files=[])
    summon_coords: list[tuple[int | None, int | None]] = []
    dismiss_reasons: list[str] = []

    def on_summon(x: int | None, y: int | None) -> None:
        summon_coords.append((x, y))
        donut.center_on_screen()
        donut.show()

    def on_dismiss(reason: str) -> None:
        dismiss_reasons.append(reason)
        donut.hide()
        donut.reset_state()

    coordinator = ListenerCoordinator(
        mode=SummonMode.PATH_C,
        target_key="Super",
        on_summon=on_summon,
        on_dismiss=on_dismiss,
    )

    # 1. Press Super -> Path C immediately summons at screen centre
    coordinator.on_key_down("Super")
    assert len(summon_coords) == 1
    assert summon_coords[0] == (None, None)
    assert coordinator.is_donut_visible is True
    assert donut.isVisible() is True

    # 2. Press Esc -> dismisses donut
    coordinator.on_esc_pressed()
    assert len(dismiss_reasons) == 1
    assert dismiss_reasons[0] == "esc"
    assert coordinator.is_donut_visible is False
    assert donut.isVisible() is False

    donut.close()


def test_daemon_drop_handling_and_shrink_execution(
    qapp: QApplication, test_image_file: Path
) -> None:
    donut = DonutWindow(files=[])
    coordinator = ListenerCoordinator(
        mode=SummonMode.PATH_A,
        target_key="Super",
        on_summon=lambda x, y: donut.show(),
        on_dismiss=lambda r: donut.hide(),
    )

    donut.drop_received.connect(coordinator.on_drop_received)

    # Summon donut
    coordinator.on_key_down("Super")
    coordinator.on_drag_start(400, 300)
    assert coordinator.is_donut_visible is True

    # Construct drop event on a valid segment
    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile(str(test_image_file))])

    # Segment index 1 (50 KB target) at anchor point
    seg1 = donut.geometry_calc.segments[1]
    pt_x = int(donut.width() / 2.0 + seg1.label_anchor[0])
    pt_y = int(donut.height() / 2.0 + seg1.label_anchor[1])

    from PySide6.QtCore import Qt

    drop_event = QDropEvent(
        QPoint(pt_x, pt_y),
        Qt.DropAction.CopyAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    donut.dropEvent(drop_event)

    # Verify drop was registered
    assert coordinator.has_active_drop is True

    # Release key -> donut MUST stay visible to show shrinking progress / result
    coordinator.on_key_up("Super", held_ms=600.0)
    assert coordinator.is_donut_visible is True
    assert donut.isVisible() is True

    # Wait for shrink worker to finish
    if donut._shrink_worker is not None:
        donut._shrink_worker.wait(5000)

    assert donut.state in ("success", "working")
    donut.close()


def test_daemon_logging_transitions(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    service = DaemonService(state_dir=state_dir)
    logger = service.setup_logging()

    log_entries: list[str] = []

    def on_log(msg: str) -> None:
        logger.info(msg)
        log_entries.append(msg)

    coordinator = ListenerCoordinator(
        mode=SummonMode.PATH_A,
        target_key="Super",
        on_log=on_log,
    )

    coordinator.on_key_down("Super")
    coordinator.on_drag_start(500, 400)
    coordinator.on_drop_received(["sample.jpg"])
    coordinator.on_key_up("Super", held_ms=450.0)
    coordinator.on_esc_pressed()

    for h in logger.handlers:
        h.flush()

    log_file = get_log_path(state_dir)
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")

    assert "Trigger key 'Super' pressed" in content
    assert "Drag started at x=500, y=400" in content
    assert "Drop received: 1 files" in content
    assert "Donut dismissed via Esc key" in content
