import os

import pytest

# Ensure Qt can run in headless test environments if no display is active
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from spikes.c_overlay_drop import (
    DropOverlayWindow,
    OverlaySpikeController,
    VariantMode,
    measure_show_latency,
    parse_uri_list,
)


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_parse_uri_list_plain_strings():
    raw_data = (
        "file:///home/user/photo.jpg\r\n"
        "file:///home/user/document%20with%20spaces.pdf\r\n"
        "# Comment\r\n"
    )
    paths = parse_uri_list(raw_data)
    assert len(paths) == 2
    assert paths[0] == "/home/user/photo.jpg"
    assert paths[1] == "/home/user/document with spaces.pdf"


def test_parse_uri_list_empty_and_invalid():
    assert parse_uri_list("") == []
    assert parse_uri_list("   \r\n# comment\r\n") == []
    assert parse_uri_list("not-a-uri") == []


def test_parse_uri_list_qurl_list():
    from PySide6.QtCore import QUrl

    urls = [
        QUrl.fromLocalFile("/tmp/sample_image.png"),
        QUrl("file:///home/user/My%20Photo%20%231.jpg"),
    ]
    paths = parse_uri_list(urls)
    assert len(paths) == 2
    assert paths[0] == "/tmp/sample_image.png"
    assert paths[1] == "/home/user/My Photo #1.jpg"


def test_overlay_window_geometry_and_flags(qapp):
    from PySide6.QtCore import Qt

    window = DropOverlayWindow(size=300)

    # 300x300 size
    assert window.width() == 300
    assert window.height() == 300

    # Round frameless always-on-top flags
    flags = window.windowFlags()
    assert bool(flags & Qt.WindowType.FramelessWindowHint) is True
    assert bool(flags & Qt.WindowType.WindowStaysOnTopHint) is True

    # Translucent background attribute
    assert window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) is True

    # Accepts drops
    assert window.acceptDrops() is True


def test_overlay_drag_enter_accepts_uri_list(qapp):
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDragEnterEvent

    window = DropOverlayWindow(size=300)

    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile("/path/to/test.jpg")])

    event = QDragEnterEvent(
        QPointF(150.0, 150.0),
        Qt.DropAction.CopyAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dragEnterEvent(event)
    assert event.isAccepted()


def test_overlay_drag_enter_rejects_unsupported_mime(qapp):
    from PySide6.QtCore import QMimeData, QPointF, Qt
    from PySide6.QtGui import QDragEnterEvent

    window = DropOverlayWindow(size=300)

    mime_data = QMimeData()
    mime_data.setText("just plain text without urls")

    event = QDragEnterEvent(
        QPointF(150.0, 150.0),
        Qt.DropAction.CopyAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dragEnterEvent(event)
    assert not event.isAccepted()


def test_overlay_drop_event_triggers_callback(qapp):
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent

    dropped_records = []

    def on_drop_cb(files):
        dropped_records.extend(files)

    window = DropOverlayWindow(size=300, on_drop=on_drop_cb)

    mime_data = QMimeData()
    mime_data.setUrls([
        QUrl.fromLocalFile("/home/user/pic1.png"),
        QUrl.fromLocalFile("/home/user/pic2.jpg"),
    ])

    event = QDropEvent(
        QPointF(150.0, 150.0),
        Qt.DropAction.CopyAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(event)

    assert event.isAccepted()
    assert dropped_records == ["/home/user/pic1.png", "/home/user/pic2.jpg"]
    assert window.last_dropped_files == ["/home/user/pic1.png", "/home/user/pic2.jpg"]


def test_controller_variant_modes():
    controller = OverlaySpikeController()
    assert controller.current_variant == VariantMode.BEFORE_DRAG

    controller.set_variant(VariantMode.DURING_DRAG, delay_s=3.0)
    assert controller.current_variant == VariantMode.DURING_DRAG
    assert controller.delay_s == 3.0


def test_controller_records_pass_fail():
    controller = OverlaySpikeController()

    # Initial state
    assert controller.get_variant_status(VariantMode.BEFORE_DRAG) == "PENDING"
    assert controller.get_variant_status(VariantMode.DURING_DRAG) == "PENDING"

    # Variant 1 drop recorded
    controller.record_drop(VariantMode.BEFORE_DRAG, ["/tmp/file1.png"])
    assert controller.get_variant_status(VariantMode.BEFORE_DRAG) == "PASS"
    assert controller.dropped_files[VariantMode.BEFORE_DRAG] == ["/tmp/file1.png"]

    # Variant 2 failed
    controller.record_failure(VariantMode.DURING_DRAG, "Timeout waiting for drop")
    assert controller.get_variant_status(VariantMode.DURING_DRAG) == "FAIL"


def test_controller_summary_formatting():
    controller = OverlaySpikeController()
    controller.record_drop(VariantMode.BEFORE_DRAG, ["/home/user/photo.jpg"])
    controller.record_drop(VariantMode.DURING_DRAG, ["/home/user/photo.jpg"])
    controller.record_appearance(VariantMode.BEFORE_DRAG, latency_ms=12.4)
    controller.record_appearance(VariantMode.DURING_DRAG, latency_ms=14.1)

    summary = controller.format_summary()
    assert "Variant 1 (visible BEFORE drag): PASS" in summary
    assert "Variant 2 (appears DURING drag):  PASS" in summary
    assert "Appearance latency: ~1" in summary
    assert "Blocks file manager: NO" in summary


def test_measure_show_latency(qapp):
    window = DropOverlayWindow(size=300)
    latency = measure_show_latency(window)
    assert isinstance(latency, float)
    assert latency >= 0.0
    window.close()


def test_run_spike_c_automated(qapp, capsys):
    from spikes.c_overlay_drop import run_spike_c

    ret = run_spike_c(
        auto_files_v1=["/tmp/test1.png"],
        auto_files_v2=["/tmp/test2.jpg"],
        delay_seconds=0.01,
        timeout_seconds=1.0,
    )
    assert ret == 0
    captured = capsys.readouterr().out
    assert "Variant 1 (visible BEFORE drag): PASS" in captured
    assert "Variant 2 (appears DURING drag):  PASS" in captured
    assert "Blocks file manager: NO" in captured

