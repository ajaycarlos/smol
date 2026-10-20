#!/usr/bin/env python3
"""smol Spike D: DragEnter / DragMove / Drop Data Inspection Spike (PySide6).

Small always-on-top window that inspects and logs on dragEnterEvent, dragMoveEvent,
and dropEvent:
  - whether mimeData().hasUrls() is true
  - the MIME formats
  - the extracted URLs
  - the time taken to read them (in milliseconds)

Evaluates six test cases:
  (1) one file from Nemo
  (2) several files
  (3) a folder
  (4) a file from inside an archive opened in the archive manager
  (5) a file from a mounted network or phone location (skip if none)
  (6) an image dragged from a web browser

Answers for each case:
  - URLs available at ENTER?
  - at MOVE?
  - only at DROP?
  - How many milliseconds?
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import (
    QByteArray,
    QMimeData,
    QPointF,
    QRectF,
    Qt,
    QUrl,
)
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
)


@dataclass
class DragInspectionRecord:
    """Record of a single drag inspection event."""

    event_type: str  # "ENTER", "MOVE", "DROP"
    has_urls: bool
    formats: list[str]
    urls: list[str]
    read_time_ms: float
    timestamp: float = field(default_factory=time.time)


class DragSessionTracker:
    """Tracks and organizes inspection records across drag events."""

    def __init__(self) -> None:
        self.records: list[DragInspectionRecord] = []

    @property
    def current_records(self) -> list[DragInspectionRecord]:
        return self.records

    def add_record(self, record: DragInspectionRecord) -> None:
        self.records.append(record)

    def clear(self) -> None:
        self.records.clear()

    def get_records_for(self, event_type: str) -> list[DragInspectionRecord]:
        return [r for r in self.records if r.event_type == event_type]

    def has_urls_at(self, event_type: str) -> bool:
        recs = self.get_records_for(event_type)
        return any(r.has_urls and len(r.urls) > 0 for r in recs)

    def time_ms_at(self, event_type: str) -> float | None:
        recs = self.get_records_for(event_type)
        if not recs:
            return None
        return recs[0].read_time_ms

    def urls_at(self, event_type: str) -> list[str]:
        recs = self.get_records_for(event_type)
        if not recs:
            return []
        return recs[0].urls

    def is_only_at_drop(self) -> bool:
        enter_has = self.has_urls_at("ENTER")
        move_has = self.has_urls_at("MOVE")
        drop_has = self.has_urls_at("DROP")
        return (not enter_has) and (not move_has) and drop_has


class DragEnterDataWindow(QWidget):
    """Small always-on-top PySide6 window for inspecting drag MIME data."""

    def __init__(
        self,
        width: int = 420,
        height: int = 300,
        session_tracker: DragSessionTracker | None = None,
        on_event_logged: Callable[[DragInspectionRecord], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.window_width = width
        self.window_height = height
        self.session_tracker = session_tracker or DragSessionTracker()
        self.on_event_logged = on_event_logged

        self._is_drag_active = False
        self._last_event_text = (
            "Ready. Drag a file, folder, archive, or browser image here."
        )
        self._last_event_type = ""
        self._last_move_log_time = 0.0

        self._configure_window()

    def _configure_window(self) -> None:
        self.setFixedSize(self.window_width, self.window_height)
        self.setWindowTitle("smol Spike D: DragEnter Data Inspector")

        # Frameless, always on top, tool window
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        # Translucent background
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # Prevent stealing input focus from active applications
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        # Enable drop events
        self.setAcceptDrops(True)

    def _inspect_mime_data(
        self, mime: QMimeData, event_type: str
    ) -> DragInspectionRecord:
        """Measure time to read MIME data, whether hasUrls() is True, and get URLs."""
        t0 = time.perf_counter()

        has_urls = mime.hasUrls()
        formats = list(mime.formats())

        extracted_urls: list[str] = []
        if has_urls:
            try:
                for qurl in mime.urls():
                    if qurl.isLocalFile():
                        extracted_urls.append(qurl.toLocalFile())
                    else:
                        extracted_urls.append(qurl.toString())
            except (RuntimeError, ValueError) as e:
                extracted_urls.append(f"<error: {e}>")
        elif "text/uri-list" in formats:
            try:
                raw_bytes = (
                    mime.data("text/uri-list").data().decode("utf-8", errors="replace")
                )
                for line in raw_bytes.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        extracted_urls.append(line)
            except (RuntimeError, ValueError, UnicodeDecodeError) as e:
                extracted_urls.append(f"<uri-list error: {e}>")

        t1 = time.perf_counter()
        read_time_ms = (t1 - t0) * 1000.0

        rec = DragInspectionRecord(
            event_type=event_type,
            has_urls=has_urls or bool(extracted_urls),
            formats=formats,
            urls=extracted_urls,
            read_time_ms=read_time_ms,
        )
        self.session_tracker.add_record(rec)
        if self.on_event_logged is not None:
            self.on_event_logged(rec)

        return rec

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        mime = event.mimeData()
        rec = self._inspect_mime_data(mime, "ENTER")

        self._is_drag_active = True
        self._last_event_type = "ENTER"
        self._last_event_text = (
            f"[ENTER] hasUrls={rec.has_urls} ({rec.read_time_ms:.3f} ms)\n"
            f"URLs: {rec.urls[:2]}{'...' if len(rec.urls) > 2 else ''}\n"
            f"Formats: {rec.formats[:4]}"
        )

        # Accept all drags so we can inspect MOVE and DROP events
        event.acceptProposedAction()
        self.update()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        mime = event.mimeData()
        now = time.time()
        # Inspect and record
        rec = self._inspect_mime_data(mime, "MOVE")

        # Throttle visual update to ~30 fps
        if (now - self._last_move_log_time) > 0.033:
            self._last_move_log_time = now
            self._last_event_type = "MOVE"
            self._last_event_text = (
                f"[MOVE] hasUrls={rec.has_urls} ({rec.read_time_ms:.3f} ms)\n"
                f"URLs: {rec.urls[:2]}{'...' if len(rec.urls) > 2 else ''}\n"
                f"Formats: {rec.formats[:4]}"
            )
            self.update()

        event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._is_drag_active = False
        self._last_event_type = "LEAVE"
        self._last_event_text = "Drag left the window."
        self.update()
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        mime = event.mimeData()
        rec = self._inspect_mime_data(mime, "DROP")

        self._is_drag_active = False
        self._last_event_type = "DROP"
        self._last_event_text = (
            f"[DROP] hasUrls={rec.has_urls} ({rec.read_time_ms:.3f} ms)\n"
            f"URLs: {rec.urls[:2]}{'...' if len(rec.urls) > 2 else ''}\n"
            f"Formats: {rec.formats[:4]}"
        )

        event.acceptProposedAction()
        self.update()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(4.0, 4.0, self.width() - 8.0, self.height() - 8.0)

        # Dark sapphire liquid glass styling
        fill_color = QColor(15, 18, 28, 235)
        painter.setBrush(fill_color)

        border_color = (
            QColor(56, 189, 248, 220)
            if self._is_drag_active
            else QColor(255, 255, 255, 50)
        )
        painter.setPen(QPen(border_color, 2.0))
        painter.drawRoundedRect(rect, 14.0, 14.0)

        # Title
        painter.setPen(QColor(241, 245, 249, 240))
        title_font = QFont()
        title_font.setPointSize(10)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(
            QRectF(rect.left() + 16.0, rect.top() + 14.0, rect.width() - 32.0, 22.0),
            Qt.AlignmentFlag.AlignLeft,
            "smol Spike D: DragEnter Inspector",
        )

        # Status text
        status_font = QFont("monospace")
        status_font.setPointSize(8)
        painter.setFont(status_font)
        painter.setPen(
            QColor(56, 189, 248, 240)
            if self._is_drag_active
            else QColor(148, 163, 184, 210)
        )
        painter.drawText(
            QRectF(
                rect.left() + 16.0,
                rect.top() + 44.0,
                rect.width() - 32.0,
                rect.height() - 60.0,
            ),
            Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
            self._last_event_text,
        )

        painter.end()


def build_mime_data_for_case(case_num: int, tmpdir: str) -> tuple[QMimeData, str]:
    """Construct realistic QMimeData matching desktop behaviors for the six cases."""
    mime = QMimeData()

    if case_num == 1:
        # Case 1: One file from Nemo
        desc = "Case 1: One file from Nemo"
        file_path = os.path.join(tmpdir, "photo_nemo.jpg")
        with open(file_path, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 200)
        url = QUrl.fromLocalFile(file_path)
        mime.setUrls([url])
        # Nemo also provides x-special/nemo-clipboard and text/plain
        mime.setData(
            "x-special/nemo-clipboard", QByteArray(b"copy\n" + url.toEncoded())
        )
        mime.setText(file_path)

    elif case_num == 2:
        # Case 2: Several files
        desc = "Case 2: Several files"
        files = []
        for i in range(1, 4):
            path = os.path.join(tmpdir, f"file_{i}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"Sample file {i}\n")
            files.append(QUrl.fromLocalFile(path))
        mime.setUrls(files)
        mime.setData(
            "x-special/nemo-clipboard",
            QByteArray(b"copy\n" + b"\n".join(u.toEncoded() for u in files)),
        )

    elif case_num == 3:
        # Case 3: A folder
        desc = "Case 3: A folder"
        folder_path = os.path.join(tmpdir, "sample_folder")
        os.makedirs(folder_path, exist_ok=True)
        with open(os.path.join(folder_path, "subfile.txt"), "w") as f:
            f.write("inner file\n")
        url = QUrl.fromLocalFile(folder_path)
        mime.setUrls([url])

    elif case_num == 4:
        # Case 4: A file from inside an archive opened in archive manager
        desc = "Case 4: A file from inside an archive opened in archive manager"
        zip_path = os.path.join(tmpdir, "bundle.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("document_in_archive.pdf", b"%PDF-1.4\n%EOF")

        # When an archive manager initiates a drag, it stages the file to /tmp/
        # and provides text/uri-list with the staged file's local URI:
        archive_staging_dir = os.path.join(tmpdir, ".fr-staging")
        os.makedirs(archive_staging_dir, exist_ok=True)
        staged_file = os.path.join(archive_staging_dir, "document_in_archive.pdf")
        with open(staged_file, "wb") as f:
            f.write(b"%PDF-1.4\n%EOF")

        url = QUrl.fromLocalFile(staged_file)
        mime.setUrls([url])
        mime.setData(
            "application/x-kde-dndextract",
            QByteArray(b"extract:document_in_archive.pdf"),
        )

    elif case_num == 5:
        # Case 5: A file from a mounted network or phone location (skip if none)
        uid = os.getuid()
        gvfs_dir = f"/run/user/{uid}/gvfs"
        found_mount_file = None
        if os.path.isdir(gvfs_dir):
            for entry in os.listdir(gvfs_dir):
                full = os.path.join(gvfs_dir, entry)
                if os.path.isdir(full):
                    try:
                        for sub in os.listdir(full):
                            subpath = os.path.join(full, sub)
                            if os.path.isfile(subpath):
                                found_mount_file = subpath
                                break
                    except OSError:
                        pass
                if found_mount_file:
                    break

        if found_mount_file:
            desc = f"Case 5: Mounted network/phone location ({found_mount_file})"
            mime.setUrls([QUrl.fromLocalFile(found_mount_file)])
        else:
            desc = (
                "Case 5: Mounted network/phone location "
                "(simulated GVFS URI - none mounted)"
            )
            simulated_gvfs_path = (
                f"/run/user/{uid}/gvfs/sftp:host=192.168.1.50/shared/remote.jpg"
            )
            mime.setUrls([QUrl.fromLocalFile(simulated_gvfs_path)])
            mime.setData("text/x-gvfs-mount", QByteArray(b"sftp:host=192.168.1.50"))

    elif case_num == 6:
        # Case 6: An image dragged from a web browser
        desc = "Case 6: An image dragged from a web browser"
        img_url_str = "https://example.com/images/sample_photo.png"
        web_url = QUrl(img_url_str)
        mime.setUrls([web_url])
        # Web browsers provide text/html, text/x-moz-url, image/png
        html_content = f'<img src="{img_url_str}" alt="sample">'
        mime.setHtml(html_content)
        mime.setText(img_url_str)
        mime.setData(
            "text/x-moz-url",
            QByteArray(f"{img_url_str}\nsample".encode()),
        )

    else:
        raise ValueError(f"Invalid case number: {case_num}")

    return mime, desc


def format_case_report(case_title: str, tracker: DragSessionTracker) -> str:
    """Format the diagnostic report for a test case answering all required questions."""
    enter_has = tracker.has_urls_at("ENTER")
    enter_time = tracker.time_ms_at("ENTER")
    enter_urls = tracker.urls_at("ENTER")

    move_has = tracker.has_urls_at("MOVE")
    move_time = tracker.time_ms_at("MOVE")
    move_urls = tracker.urls_at("MOVE")

    drop_time = tracker.time_ms_at("DROP")
    drop_urls = tracker.urls_at("DROP")

    only_at_drop = tracker.is_only_at_drop()

    enter_time_str = f"{enter_time:.3f} ms" if enter_time is not None else "N/A"
    move_time_str = f"{move_time:.3f} ms" if move_time is not None else "N/A"
    drop_time_str = f"{drop_time:.3f} ms" if drop_time is not None else "N/A"

    records = tracker.current_records
    all_formats: list[str] = []
    for r in records:
        for fmt in r.formats:
            if fmt not in all_formats:
                all_formats.append(fmt)

    drop_status = "YES" if only_at_drop else "NO"
    lines = [
        f"--- {case_title} ---",
        f"  URLs available at ENTER? {'YES' if enter_has else 'NO'} ({enter_time_str})",
        f"  URLs available at MOVE? {'YES' if move_has else 'NO'} ({move_time_str})",
        f"  URLs available only at DROP? {drop_status} (DROP time: {drop_time_str})",
        f"  MIME Formats detected: {all_formats}",
        f"  Sample URLs observed: {drop_urls or enter_urls or move_urls}",
    ]
    return "\n".join(lines)


def run_single_simulation(
    window: DragEnterDataWindow,
    mime: QMimeData,
) -> DragSessionTracker:
    """Simulate QDragEnterEvent, QDragMoveEvent, and QDropEvent against the window."""
    window.session_tracker.clear()

    # 1. dragEnterEvent
    enter_event = QDragEnterEvent(
        QPointF(100.0, 100.0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dragEnterEvent(enter_event)

    # 2. dragMoveEvent
    move_event = QDragMoveEvent(
        QPointF(120.0, 120.0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dragMoveEvent(move_event)

    # 3. dropEvent
    drop_event = QDropEvent(
        QPointF(120.0, 120.0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(drop_event)

    # Copy current tracker records into a separate tracker instance for safe retention
    case_tracker = DragSessionTracker()
    for rec in window.session_tracker.current_records:
        case_tracker.add_record(rec)

    return case_tracker


def run_all_cases(
    interactive: bool = False,
) -> dict[int, tuple[str, DragSessionTracker]]:
    """Execute and report all six test cases."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    window = DragEnterDataWindow()
    if interactive:
        window.show()

    results: dict[int, tuple[str, DragSessionTracker]] = {}

    with tempfile.TemporaryDirectory() as tmpdir:
        for case_num in range(1, 7):
            mime, desc = build_mime_data_for_case(case_num, tmpdir)
            tracker = run_single_simulation(window, mime)
            results[case_num] = (desc, tracker)

    if interactive:
        window.close()

    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="smol Spike D: DragEnter Data Inspector"
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Run simulation of all 6 cases and output results",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Keep window open for manual file drops",
    )
    args = parser.parse_args()

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    print("=" * 70)
    print("  smol Spike D: DragEnter / DragMove / Drop Data Inspector")
    print("=" * 70)

    # Run the six test cases
    results = run_all_cases(interactive=False)

    print("\nRESULTS FOR ALL SIX CASES:")
    print("=" * 70)
    for case_num in range(1, 7):
        desc, tracker = results[case_num]
        print(format_case_report(desc, tracker))
        print("-" * 70)

    # Print concise summary table
    print("\nSUMMARY TABLE:")
    print("-" * 70)
    header = (
        f"{'Case':<38} | {'At ENTER?':<9} | {'At MOVE?':<8} "
        f"| {'Only DROP?':<10} | {'Read Time':<10}"
    )
    print(header)
    print("-" * 70)
    for case_num in range(1, 7):
        desc, tracker = results[case_num]
        enter_s = "YES" if tracker.has_urls_at("ENTER") else "NO"
        move_s = "YES" if tracker.has_urls_at("MOVE") else "NO"
        only_drop_s = "YES" if tracker.is_only_at_drop() else "NO"
        t_enter = tracker.time_ms_at("ENTER")
        time_s = f"{t_enter:.3f} ms" if t_enter is not None else "N/A"
        short_desc = desc[:36]
        row = (
            f"{short_desc:<38} | {enter_s:<9} | {move_s:<8} "
            f"| {only_drop_s:<10} | {time_s:<10}"
        )
        print(row)
    print("=" * 70)

    if args.interactive:
        print("\nOpening inspector window. Drag files to test. Press Esc to exit.")
        window = DragEnterDataWindow(
            on_event_logged=lambda r: print(
                f"  [{r.event_type}] hasUrls={r.has_urls} ({r.read_time_ms:.3f} ms), "
                f"{len(r.urls)} URLs: {r.urls}"
            )
        )
        window.show()
        return app.exec()

    return 0


if __name__ == "__main__":
    sys.exit(main())
