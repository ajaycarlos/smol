"""Tests for robust drag-and-drop handling and job queueing."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtWidgets import QApplication

from smol.daemon.listener import ListenerCoordinator, SummonMode
from smol.ui.donut_window import DonutWindow, parse_drop_uris


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _create_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    import random

    random.seed(42)
    img = Image.frombytes("RGB", (300, 300), random.randbytes(300 * 300 * 3))
    img.save(path, format="JPEG", quality=90)
    return path


def test_parse_drop_uris_spaces_and_unicode(tmp_path: Path) -> None:
    """Verify parsing drop URIs with spaces, unicode characters, and escapes."""
    file_space = _create_image(tmp_path / "my photo with space.jpg")
    file_unicode = _create_image(tmp_path / "画像_テスト.jpg")

    mime = QMimeData()
    # Emulate file manager text/uri-list with percent-encoded paths
    uri1 = file_space.as_uri()  # file:///.../my%20photo%20with%20space.jpg
    uri2 = file_unicode.as_uri()  # percent encoded unicode
    raw_text = f"# Comment line\r\n{uri1}\r\n\r\n{uri2}\r\n"
    mime.setData("text/uri-list", raw_text.encode("utf-8"))
    mime.setText(raw_text)

    parsed = parse_drop_uris(mime)
    assert len(parsed) == 2
    assert parsed[0] == file_space
    assert parsed[1] == file_unicode


def test_parse_drop_uris_multiple_folders(tmp_path: Path) -> None:
    """Verify drop URIs from different folders are parsed cleanly."""
    dir1 = tmp_path / "folder_alpha"
    dir2 = tmp_path / "folder_beta"
    file1 = _create_image(dir1 / "image1.jpg")
    file2 = _create_image(dir2 / "image2.jpg")

    mime = QMimeData()
    urls = [QUrl.fromLocalFile(str(file1)), QUrl.fromLocalFile(str(file2))]
    mime.setUrls(urls)

    parsed = parse_drop_uris(mime)
    assert len(parsed) == 2
    assert parsed[0] == file1
    assert parsed[1] == file2
    assert parsed[0].parent != parsed[1].parent


def test_parse_drop_uris_localhost_and_crlf(tmp_path: Path) -> None:
    """Verify standard file://localhost/ URIs and CRLF line endings are parsed."""
    file1 = _create_image(tmp_path / "pic.jpg")
    raw_uri = f"file://localhost{file1.resolve().as_posix()}"

    mime = QMimeData()
    mime.setText(f"{raw_uri}\r\n")

    parsed = parse_drop_uris(mime)
    assert len(parsed) == 1
    assert parsed[0] == file1


def test_parse_drop_uris_filters_nonexistent(tmp_path: Path) -> None:
    """Verify nonexistent paths or invalid schemes are filtered out safely."""
    real_file = _create_image(tmp_path / "real.jpg")
    fake_file = tmp_path / "nonexistent.jpg"

    mime = QMimeData()
    mime.setText(
        f"{real_file.as_uri()}\n{fake_file.as_uri()}\nhttp://example.com/test\n"
    )

    parsed = parse_drop_uris(mime)
    assert len(parsed) == 1
    assert parsed[0] == real_file


def test_job_queueing_while_working(qapp: QApplication, tmp_path: Path) -> None:
    """Verify dropping files while working queues them and processes sequentially."""
    file1 = _create_image(tmp_path / "first.jpg")
    file2 = _create_image(tmp_path / "second.jpg")

    donut = DonutWindow(files=[file1])

    # Start first job
    target1 = 20_000
    donut.start_shrink(target1, files=[file1])
    assert donut.state == "working"

    # Now drop second file while first job is working
    target2 = 50_000
    donut.queue_or_start_shrink(target2, files=[file2])

    # Should be queued
    assert len(donut.job_queue) == 1
    assert donut.job_queue[0] == (target2, [file2])
    has_queue_text = (
        "+1 queued" in donut.center_status_text
        or "queued" in donut.center_status_text.lower()
    )
    assert has_queue_text

    # Wait for all workers and queued jobs to complete
    for _ in range(100):
        qapp.processEvents()
        if donut.state in ("success", "failure") and len(donut.job_queue) == 0:
            break
        import time

        time.sleep(0.05)

    assert donut.state == "success"
    assert len(donut.job_queue) == 0
    # Both output files should exist
    assert any("first_" in str(p) for p in tmp_path.iterdir())
    assert any("second_" in str(p) for p in tmp_path.iterdir())


def test_drag_cancelled_midway_resets_state() -> None:
    """Verify cancelling drag midway triggers dismissal and resets coordinator."""
    dismiss_reasons: list[str] = []
    coordinator = ListenerCoordinator(
        mode=SummonMode.PATH_A,
        target_key="Super",
        on_dismiss=lambda r: dismiss_reasons.append(r),
    )

    coordinator.on_key_down("Super")
    coordinator.on_drag_start(100, 200)
    assert coordinator.is_donut_visible is True

    # User cancels drag (e.g. mouse released without dropping)
    coordinator.on_drag_cancelled()
    assert coordinator.is_donut_visible is False
    assert "drag_cancelled" in dismiss_reasons
    assert coordinator.drag_tracker.is_dragging is False


def test_key_released_early_resets_state() -> None:
    """Verify releasing trigger key early dismisses donut and resets tracking."""
    dismiss_reasons: list[str] = []
    coordinator = ListenerCoordinator(
        mode=SummonMode.PATH_A,
        target_key="Super",
        on_dismiss=lambda r: dismiss_reasons.append(r),
    )

    coordinator.on_key_down("Super")
    coordinator.on_drag_start(300, 400)
    assert coordinator.is_donut_visible is True

    # User releases key early before drop
    coordinator.on_key_up("Super", held_ms=250.0)
    assert coordinator.is_donut_visible is False
    assert "key_release" in dismiss_reasons
    assert coordinator.drag_tracker.is_dragging is False


def test_drop_received_protects_against_key_release_and_cancel(tmp_path: Path) -> None:
    """Verify that after a drop, releasing the trigger key does not dismiss."""
    dismiss_reasons: list[str] = []
    coordinator = ListenerCoordinator(
        mode=SummonMode.PATH_A,
        target_key="Super",
        on_dismiss=lambda r: dismiss_reasons.append(r),
    )

    coordinator.on_key_down("Super")
    coordinator.on_drag_start(300, 400)
    assert coordinator.is_donut_visible is True

    # User drops file onto donut
    sample_file = _create_image(tmp_path / "drop_test.jpg")
    coordinator.on_drop_received([sample_file])
    assert coordinator.has_active_drop is True

    # User releases trigger key after drop
    coordinator.on_key_up("Super", held_ms=500.0)
    # Must NOT dismiss!
    assert len(dismiss_reasons) == 0
    assert coordinator.is_donut_visible is True

    # Pointer drag cancellation signal (if any) must also NOT dismiss!
    coordinator.on_drag_cancelled()
    assert len(dismiss_reasons) == 0
    assert coordinator.is_donut_visible is True

