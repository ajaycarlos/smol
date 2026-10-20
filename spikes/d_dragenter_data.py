#!/usr/bin/env python3
"""smol Spike D: Real DragEnter / DragMove / Drop Data Inspector (Interactive).

Visible always-on-top window (~320x320) waiting for real drags from other apps.
Logs all drag events to spikes/d_log.txt:
  - perf_counter timestamp
  - event type (ENTER, MOVE, LEAVE, DROP)
  - whether event.source() is None (external app)
  - proposed action
  - mime formats
  - hasUrls()
  - raw URLs (toString and toLocalFile)
  - read time in milliseconds measured with time.perf_counter

Keys:
  1-6 : Tag NEXT drag session with case number
  Esc : Quit and print summary table
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field

from PySide6.QtCore import (
    QRectF,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QKeyEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
)

DEFAULT_LOG_PATH = os.path.join(os.path.dirname(__file__), "d_log.txt")

CASE_DESCRIPTIONS: dict[int, str] = {
    1: "One file from Nemo",
    2: "Several files from Nemo",
    3: "A folder from Nemo",
    4: "A file dragged out of archive manager",
    5: "A file from mounted network/phone location",
    6: "An image dragged from a web browser",
}


@dataclass
class DragEventRecord:
    """Record of a single drag event appended to the log file."""

    timestamp: float
    event_type: str  # "ENTER", "MOVE", "LEAVE", "DROP"
    source_is_none: bool | None
    proposed_action: str | None
    formats: list[str]
    has_urls: bool | None
    urls: list[dict[str, str]]
    read_time_ms: float
    case_tag: int | None = None


@dataclass
class SessionSummary:
    """Summary of a drag session (enter through leave/drop)."""

    case_num: int
    enter_has_urls: bool = False
    enter_read_ms: float = 0.0
    move_has_urls: bool = False
    move_read_ms: float = 0.0
    drop_has_urls: bool = False
    drop_read_ms: float = 0.0
    formats: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)

    @property
    def urls_only_at_drop(self) -> bool:
        return (
            (not self.enter_has_urls)
            and (not self.move_has_urls)
            and self.drop_has_urls
        )


def format_log_line(record: DragEventRecord) -> str:
    """Format a single-line log entry for spikes/d_log.txt."""
    return (
        f"{record.timestamp:.6f} | "
        f"{record.event_type:<5} | "
        f"case={record.case_tag or 'None'} | "
        f"source_is_none={record.source_is_none} | "
        f"action={record.proposed_action or 'None'} | "
        f"hasUrls={record.has_urls} | "
        f"read_time_ms={record.read_time_ms:.4f} | "
        f"formats={record.formats} | "
        f"urls={record.urls}"
    )


def format_summary_table(sessions: dict[int, SessionSummary]) -> str:
    """Format summary table for cases 1-6. Untested cases print NOT TESTED."""
    lines: list[str] = [
        "=" * 74,
        "  smol Spike D: Drag-and-Drop Diagnostic Summary",
        "=" * 74,
    ]
    for case_num in range(1, 7):
        desc = CASE_DESCRIPTIONS[case_num]
        sess = sessions.get(case_num)
        if sess is None:
            lines.append(f"Case {case_num}: {desc} -> NOT TESTED")
        else:
            enter_s = (
                f"YES ({sess.enter_read_ms:.3f} ms)" if sess.enter_has_urls else "NO"
            )
            move_s = f"YES ({sess.move_read_ms:.3f} ms)" if sess.move_has_urls else "NO"
            only_drop_s = "YES" if sess.urls_only_at_drop else "NO"
            lines.append(f"Case {case_num}: {desc}")
            lines.append(f"  - URLs at ENTER?     {enter_s}")
            lines.append(f"  - URLs at MOVE?      {move_s}")
            lines.append(f"  - URLs only at DROP? {only_drop_s}")
            if sess.drop_has_urls:
                lines.append(f"  - Read time at DROP: {sess.drop_read_ms:.3f} ms")
            lines.append(f"  - Formats detected:  {sess.formats}")
            lines.append(f"  - Sample URLs:       {sess.urls[:2]}")
        lines.append("-" * 74)
    lines.append("=" * 74)
    return "\n".join(lines)


class DragDataInspectorWindow(QWidget):
    """Small always-on-top window that accepts real drags and logs diagnostics."""

    def __init__(
        self,
        log_path: str = DEFAULT_LOG_PATH,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.log_path = log_path
        self.current_case_tag: int | None = None
        self.active_session_case: int | None = None
        self.current_session: SessionSummary | None = None
        self.sessions: dict[int, SessionSummary] = {}

        self._last_move_log_time = 0.0
        self._status_text = (
            "Ready for REAL drags.\n\n"
            "Press 1-6 to tag the NEXT case.\n"
            "Drop files/folders here.\n"
            "Press Esc to exit & show summary."
        )

        self._configure_window()

    def _configure_window(self) -> None:
        self.setFixedSize(320, 320)
        self.setWindowTitle("smol Spike D: Real Drag Inspector")

        # Always-on-top tool window
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)

        self.setAcceptDrops(True)

    def _append_log(self, record: DragEventRecord) -> None:
        line = format_log_line(record)
        os.makedirs(os.path.dirname(os.path.abspath(self.log_path)), exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        ts = time.perf_counter()
        mime = event.mimeData()

        # Measure urls() call duration
        t0 = time.perf_counter()
        urls_list = mime.urls() if mime.hasUrls() else []
        t1 = time.perf_counter()
        read_time_ms = (t1 - t0) * 1000.0

        is_ext = event.source() is None
        formats = list(mime.formats())
        has_urls = mime.hasUrls()
        url_records = [
            {"toString": u.toString(), "toLocalFile": u.toLocalFile()}
            for u in urls_list
        ]
        sample_urls = [
            u.toLocalFile() if u.isLocalFile() else u.toString() for u in urls_list
        ]

        action_name = (
            event.proposedAction().name
            if hasattr(event.proposedAction(), "name")
            else str(event.proposedAction())
        )

        # Start session
        self.active_session_case = self.current_case_tag
        tag = self.active_session_case

        sess = SessionSummary(
            case_num=tag if tag is not None else 0,
            enter_has_urls=has_urls and bool(urls_list),
            enter_read_ms=read_time_ms,
            formats=formats,
            urls=sample_urls,
        )
        self.current_session = sess
        if tag is not None:
            self.sessions[tag] = sess

        rec = DragEventRecord(
            timestamp=ts,
            event_type="ENTER",
            source_is_none=is_ext,
            proposed_action=action_name,
            formats=formats,
            has_urls=has_urls,
            urls=url_records,
            read_time_ms=read_time_ms,
            case_tag=tag,
        )
        self._append_log(rec)

        tag_str = (
            f"Case {tag} ({CASE_DESCRIPTIONS.get(tag, 'Custom')})"
            if tag
            else "Untagged"
        )
        self._status_text = (
            f"[{tag_str}]\n"
            f"ENTER: hasUrls={has_urls} ({read_time_ms:.3f} ms)\n"
            f"ExtApp: {is_ext} | Action: {action_name}\n"
            f"URLs: {sample_urls[:1]}\n"
            f"Formats: {len(formats)} types"
        )
        self.update()
        event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        now = time.perf_counter()
        # Log at most every 100 ms (0.10s)
        if (now - self._last_move_log_time) >= 0.10:
            self._last_move_log_time = now
            mime = event.mimeData()

            t0 = time.perf_counter()
            urls_list = mime.urls() if mime.hasUrls() else []
            t1 = time.perf_counter()
            read_time_ms = (t1 - t0) * 1000.0

            is_ext = event.source() is None
            formats = list(mime.formats())
            has_urls = mime.hasUrls()
            url_records = [
                {"toString": u.toString(), "toLocalFile": u.toLocalFile()}
                for u in urls_list
            ]
            action_name = (
                event.proposedAction().name
                if hasattr(event.proposedAction(), "name")
                else str(event.proposedAction())
            )

            rec = DragEventRecord(
                timestamp=now,
                event_type="MOVE",
                source_is_none=is_ext,
                proposed_action=action_name,
                formats=formats,
                has_urls=has_urls,
                urls=url_records,
                read_time_ms=read_time_ms,
                case_tag=self.active_session_case,
            )
            self._append_log(rec)

            if self.current_session is not None:
                self.current_session.move_has_urls = has_urls and bool(urls_list)
                self.current_session.move_read_ms = read_time_ms

            self.update()

        event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        ts = time.perf_counter()
        rec = DragEventRecord(
            timestamp=ts,
            event_type="LEAVE",
            source_is_none=None,
            proposed_action=None,
            formats=[],
            has_urls=None,
            urls=[],
            read_time_ms=0.0,
            case_tag=self.active_session_case,
        )
        self._append_log(rec)

        self._status_text = (
            "Drag LEFT window without dropping.\n\n"
            "Ready for next drag.\n"
            "Press 1-6 to tag case."
        )
        self.active_session_case = None
        self.update()
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        ts = time.perf_counter()
        mime = event.mimeData()

        t0 = time.perf_counter()
        urls_list = mime.urls() if mime.hasUrls() else []
        t1 = time.perf_counter()
        read_time_ms = (t1 - t0) * 1000.0

        is_ext = event.source() is None
        formats = list(mime.formats())
        has_urls = mime.hasUrls()
        url_records = [
            {"toString": u.toString(), "toLocalFile": u.toLocalFile()}
            for u in urls_list
        ]
        sample_urls = [
            u.toLocalFile() if u.isLocalFile() else u.toString() for u in urls_list
        ]
        action_name = (
            event.proposedAction().name
            if hasattr(event.proposedAction(), "name")
            else str(event.proposedAction())
        )

        tag = self.active_session_case
        rec = DragEventRecord(
            timestamp=ts,
            event_type="DROP",
            source_is_none=is_ext,
            proposed_action=action_name,
            formats=formats,
            has_urls=has_urls,
            urls=url_records,
            read_time_ms=read_time_ms,
            case_tag=tag,
        )
        self._append_log(rec)

        if self.current_session is not None:
            self.current_session.drop_has_urls = has_urls and bool(urls_list)
            self.current_session.drop_read_ms = read_time_ms
            if sample_urls and not self.current_session.urls:
                self.current_session.urls = sample_urls

        tag_str = f"Case {tag}" if tag else "Untagged"
        print(
            f"\n[DROP RECORDED] {tag_str}: "
            f"{len(sample_urls)} URL(s) in {read_time_ms:.3f} ms"
        )
        for u in sample_urls[:3]:
            print(f"  -> {u}")

        self._status_text = (
            f"[DROP SUCCESS - {tag_str}]\n"
            f"Read {len(sample_urls)} URL(s) in {read_time_ms:.3f} ms\n"
            f"ExtApp: {is_ext}\n\n"
            "Press 1-6 to tag next case.\n"
            "Press Esc when done."
        )

        # Clear tag for next drag so user can choose next case
        self.current_case_tag = None
        self.active_session_case = None
        self.update()
        event.acceptProposedAction()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (
            Qt.Key.Key_1,
            Qt.Key.Key_2,
            Qt.Key.Key_3,
            Qt.Key.Key_4,
            Qt.Key.Key_5,
            Qt.Key.Key_6,
        ):
            case_num = key - Qt.Key.Key_0
            self.current_case_tag = case_num
            desc = CASE_DESCRIPTIONS[case_num]
            print(f"\n>>> Tagged NEXT drag as Case {case_num}: {desc}")
            self._status_text = (
                f"NEXT DRAG TAGGED:\n"
                f"Case {case_num}: {desc}\n\n"
                f"Drag your file here now!\n"
                f"(Press Esc to finish & view table)"
            )
            self.update()
        elif key == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        event.accept()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(4.0, 4.0, self.width() - 8.0, self.height() - 8.0)

        # Dark sapphire liquid glass background
        painter.setBrush(QColor(15, 23, 42, 245))
        painter.setPen(QPen(QColor(56, 189, 248, 180), 2.0))
        painter.drawRoundedRect(rect, 14.0, 14.0)

        # Header bar
        painter.setPen(QColor(248, 250, 252))
        title_font = QFont()
        title_font.setPointSize(10)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(
            QRectF(rect.left() + 14.0, rect.top() + 12.0, rect.width() - 28.0, 20.0),
            Qt.AlignmentFlag.AlignLeft,
            "smol Spike D: Real Drag Inspector",
        )

        # Body status text
        body_font = QFont("monospace")
        body_font.setPointSize(9)
        painter.setFont(body_font)
        painter.setPen(QColor(148, 163, 184))
        painter.drawText(
            QRectF(
                rect.left() + 14.0,
                rect.top() + 40.0,
                rect.width() - 28.0,
                rect.height() - 50.0,
            ),
            Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
            self._status_text,
        )

        painter.end()


def main() -> int:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    log_path = DEFAULT_LOG_PATH
    # Clear prior log file for clean new interactive run
    if os.path.exists(log_path):
        os.remove(log_path)

    window = DragDataInspectorWindow(log_path=log_path)
    window.show()

    print("=" * 74)
    print("  smol Spike D: Interactive Real Drag-and-Drop Inspector")
    print("=" * 74)
    print(f"Logging real events to: {log_path}\n")
    print("Instructions:")
    print("  1. Press 1 to 6 to tag the NEXT drag with a case number.")
    print("  2. Perform the drag from the corresponding app onto the window.")
    print("  3. Repeat for any/all of the cases you wish to test:")
    for num, desc in CASE_DESCRIPTIONS.items():
        print(f"     [{num}] {desc}")
    print("  4. Press Esc on the window when finished to print the summary table.\n")

    exit_code = app.exec()

    # Print summary table upon closing window
    print("\n" + format_summary_table(window.sessions))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
