import os
import shutil
import stat

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from smol.core.image import shrink_image
from smol.core.size import format_size
from smol.ui.donut_window import DonutWindow

# Ensure headless Qt
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def wait_for_worker(window: DonutWindow, timeout_ms: int = 5000) -> None:
    """Helper to synchronously wait for DonutWindow worker to complete."""
    if window._shrink_worker is None:
        return
    if not window._shrink_worker.isRunning():
        return
    loop = QEventLoop()
    window._shrink_worker.finished.connect(loop.quit)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(timeout_ms)
    loop.exec()


def test_donut_centre_shows_file_count_and_finds_image_thumbnail(
    qapp, samples_dir, tmp_path
):
    """Centre shows '3 files', aggregates size, and picks first valid thumbnail."""
    a_jpg = tmp_path / "a.jpg"
    b_png = tmp_path / "b.png"
    c_txt = tmp_path / "c.txt"

    shutil.copy(samples_dir / "portrait.jpg", a_jpg)
    shutil.copy(samples_dir / "screenshot.png", b_png)
    c_txt.write_text("Hello smol! This is a plain text file.\n")

    # Put c.txt first to test that thumbnail skips c.txt and finds a.jpg
    window = DonutWindow([c_txt, a_jpg, b_png])

    assert window.file_name == "3 files"
    expected_total = a_jpg.stat().st_size + b_png.stat().st_size + c_txt.stat().st_size
    assert window.file_size_text == format_size(expected_total, spaced=True)
    assert window.thumbnail_pixmap is not None
    assert not window.thumbnail_pixmap.isNull()
    window.close()


def test_mixed_types_skips_unsupported_with_message(qapp, samples_dir, tmp_path):
    """Unsupported files get a clear message, are skipped, and valid images shrink."""
    a_jpg = tmp_path / "a.jpg"
    b_png = tmp_path / "b.png"
    c_txt = tmp_path / "c.txt"

    shutil.copy(samples_dir / "portrait.jpg", a_jpg)
    shutil.copy(samples_dir / "screenshot.png", b_png)
    c_txt.write_text("Plain text not compressible as image\n")

    window = DonutWindow([a_jpg, b_png, c_txt])
    window.show()

    # Shrink to 100 KB
    window.start_shrink(100_000)
    wait_for_worker(window)

    # Valid files should have shrunk and succeeded; c_txt skipped with clear message
    assert window.state == "success"
    assert window.last_results is not None
    assert len(window.last_results) == 3

    res_map = {path.name: res for path, res in window.last_results}

    # a.jpg shrunk
    assert res_map["a.jpg"].ok is True
    assert res_map["a.jpg"].output_path is not None
    assert res_map["a.jpg"].output_path.exists()
    assert res_map["a.jpg"].final_bytes <= 100_000

    # b.png shrunk
    assert res_map["b.png"].ok is True
    assert res_map["b.png"].output_path is not None
    assert res_map["b.png"].output_path.exists()
    assert res_map["b.png"].final_bytes <= 100_000

    # c.txt skipped with a clear message
    assert res_map["c.txt"].output_path is None
    c_msg = res_map["c.txt"].warning or res_map["c.txt"].error or ""
    assert "unsupported" in c_msg.lower() or "skipped" in c_msg.lower()

    # Result message summarizes
    msg = window.result_message
    assert "2 shrunk" in msg or "2 files shrunk" in msg
    assert "1 skipped" in window.result_message
    window.close()


def test_already_small_files_inform_and_do_not_recompress(
    qapp, samples_dir, tmp_path
):
    """Files already <= target_bytes are untouched and inform the user."""
    small_jpg = tmp_path / "small.jpg"
    shutil.copy(samples_dir / "already_small.jpg", small_jpg)  # ~30 KB
    orig_mtime = small_jpg.stat().st_mtime
    orig_bytes = small_jpg.stat().st_size

    window = DonutWindow([small_jpg])
    window.show()

    # Target 100 KB > 30 KB
    window.start_shrink(100_000)
    wait_for_worker(window)

    assert window.state == "success"
    # Original file is unmodified
    assert small_jpg.stat().st_size == orig_bytes
    assert small_jpg.stat().st_mtime == orig_mtime
    # No new output file created
    assert window.last_results[0][1].output_path is None
    # User informed
    msg = window.result_message.lower()
    assert "already" in msg or "smaller" in msg
    window.close()


def test_batch_with_all_three_types(qapp, samples_dir, tmp_path):
    """Handles normal image, already-small image, and unsupported text file together."""
    large_jpg = tmp_path / "a.jpg"
    small_jpg = tmp_path / "b.jpg"
    txt_file = tmp_path / "c.txt"

    shutil.copy(samples_dir / "portrait.jpg", large_jpg)  # ~1.2 MB
    shutil.copy(samples_dir / "already_small.jpg", small_jpg)  # ~30 KB
    txt_file.write_text("Hello world")

    window = DonutWindow([large_jpg, small_jpg, txt_file])
    window.show()

    window.start_shrink(100_000)
    wait_for_worker(window)

    assert window.state == "success"
    res_map = {path.name: res for path, res in window.last_results}

    # large shrunk
    assert res_map["a.jpg"].ok is True
    assert res_map["a.jpg"].output_path is not None
    assert res_map["a.jpg"].final_bytes <= 100_000

    # small untouched
    assert res_map["b.jpg"].ok is True
    assert res_map["b.jpg"].output_path is None

    # txt skipped
    assert res_map["c.txt"].output_path is None
    c_msg = res_map["c.txt"].warning or res_map["c.txt"].error or ""
    assert "unsupported" in c_msg.lower() or "skipped" in c_msg.lower()

    # Informative center message
    assert "1 shrunk" in window.result_message
    window.close()


def test_readonly_output_folder_suggests_alternative(samples_dir, tmp_path):
    """When the destination directory is read-only, suggest an alternative folder."""
    src_file = tmp_path / "photo.jpg"
    shutil.copy(samples_dir / "portrait.jpg", src_file)

    readonly_dir = tmp_path / "readonly_out"
    readonly_dir.mkdir(parents=True, exist_ok=True)
    # Remove write permissions
    readonly_dir.chmod(stat.S_IREAD | stat.S_IEXEC)

    try:
        res = shrink_image(
            src_file,
            100_000,
            options={"out_dir": str(readonly_dir)},
        )
        assert res.ok is False
        assert res.error is not None
        assert "read-only" in res.error.lower() or "permission" in res.error.lower()
        # Must suggest an alternative folder
        assert (
            "try" in res.error.lower()
            or "downloads" in res.error.lower()
            or "desktop" in res.error.lower()
            or "alternative" in res.error.lower()
        )
    finally:
        # Restore write permissions so pytest can clean up
        readonly_dir.chmod(stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
