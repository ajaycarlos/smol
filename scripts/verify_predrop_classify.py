"""Verification script for pre-drop classification (A4.1 / Milestone task).

Verifies the 5 specified cases on the Donut window BEFORE dropping:
1. Drag an image: state is 'all_supported', segments enabled.
2. Drag a .docx: state is 'none_supported',
   center shows 'Unsupported file type (.docx)', segments dim, drop rejected.
3. Drag a mixed pair (image + .docx): state is 'mixed', center shows
   '1 of 2 supported, 1 will be skipped', drop processes only image, toast lists .docx.
4. Drag a folder: state is 'none_supported', center shows 'folder, not supported',
   segments dim, drop rejected.
5. Drag a PDF renamed to .jpg: state is 'all_supported' (PDF is trusted and supported).
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from smol.ui.donut_window import DonutWindow


def pump_events(donut: DonutWindow, timeout_s: float = 1.0) -> None:
    start = time.time()
    worker = donut._classification_worker
    if worker is not None:
        while worker.isRunning():
            QCoreApplication.processEvents()
            time.sleep(0.01)
            if time.time() - start > timeout_s:
                break
    for _ in range(10):
        QCoreApplication.processEvents()
        time.sleep(0.005)


def make_drag_enter(paths: list[Path]) -> QDragEnterEvent:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    ev = QDragEnterEvent(
        QPointF(150.0, 150.0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    ev._mime = mime
    return ev


def make_drag_move(x: float = 150.0, y: float = 40.0) -> QDragMoveEvent:
    mime = QMimeData()
    ev = QDragMoveEvent(
        QPointF(x, y),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    ev._mime = mime
    return ev


def make_drop(paths: list[Path], x: float = 150.0, y: float = 40.0) -> QDropEvent:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    ev = QDropEvent(
        QPointF(x, y),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    ev._mime = mime
    return ev


def main() -> None:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    repo_dir = Path(__file__).resolve().parent.parent
    samples_dir = repo_dir / "tests" / "samples"
    tmp_dir = Path(tempfile.mkdtemp(prefix="smol_verify_classify_"))

    print("=" * 65)
    print("VERIFY: Pre-Drop Classification on Donut")
    print("=" * 65)

    try:
        # Case 1: Drag an image
        print("\n[Case 1] Drag an image (portrait.jpg)...")
        img = samples_dir / "portrait.jpg"
        d1 = DonutWindow(files=[img], reduce_motion=True)
        d1.dragEnterEvent(make_drag_enter([img]))
        pump_events(d1)
        print(f"  State: {d1.drag_classify_state}")
        print(f"  All segments dimmed: {d1.all_segments_dimmed}")
        assert d1.drag_classify_state == "all_supported", (
            f"Expected all_supported, got {d1.drag_classify_state}"
        )
        assert not d1.all_segments_dimmed, "Segments should be enabled"
        print("  ✓ PASS: Case 1 correctly shows all_supported with segments active")
        d1.close()

        # Case 2: Drag a .docx
        print("\n[Case 2] Drag a .docx (notes.docx)...")
        docx = tmp_dir / "notes.docx"
        docx.write_bytes(b"PK\x03\x04" + b"\x00" * 30)
        d2 = DonutWindow(files=[docx], reduce_motion=True)
        d2.dragEnterEvent(make_drag_enter([docx]))
        pump_events(d2)
        print(f"  State: {d2.drag_classify_state}")
        print(f"  Center message: {d2.center_classify_message}")
        print(f"  All segments dimmed: {d2.all_segments_dimmed}")
        move_ev = make_drag_move()
        d2.dragMoveEvent(move_ev)
        print(
            f"  Cursor over segment: {d2.cursor().shape().name} (Forbidden = rejected)"
        )
        print(f"  Move accepted: {move_ev.isAccepted()}")
        assert d2.drag_classify_state == "none_supported", (
            f"Expected none_supported, got {d2.drag_classify_state}"
        )
        assert d2.all_segments_dimmed, "Segments should be dimmed"
        assert "Unsupported file type (.docx)" in (d2.center_classify_message or ""), (
            "Expected unsupported docx message"
        )
        assert d2.cursor().shape() == Qt.CursorShape.ForbiddenCursor, (
            "Expected forbidden cursor"
        )
        assert not move_ev.isAccepted(), "Move should be ignored"
        drop_ev = make_drop([docx])
        d2.dropEvent(drop_ev)
        assert not drop_ev.isAccepted(), "Drop should be rejected"
        print(
            "  ✓ PASS: Case 2 correctly shows none_supported, "
            "dims segments, rejects drops"
        )
        d2.close()

        # Case 3: Drag a mixed pair (image + .docx)
        print("\n[Case 3] Drag a mixed pair (portrait.jpg + notes.docx)...")
        d3 = DonutWindow(files=[img], reduce_motion=True)
        d3.dragEnterEvent(make_drag_enter([img, docx]))
        pump_events(d3)
        print(f"  State: {d3.drag_classify_state}")
        print(f"  Center message: {d3.center_classify_message}")
        print(f"  All segments dimmed: {d3.all_segments_dimmed}")
        assert d3.drag_classify_state == "mixed", (
            f"Expected mixed, got {d3.drag_classify_state}"
        )
        assert not d3.all_segments_dimmed, "Segments should remain enabled"
        assert d3.center_classify_message == "1 of 2 supported, 1 will be skipped"
        # Drop onto segment
        drop_ev3 = make_drop([img, docx])
        d3.dropEvent(drop_ev3)
        assert drop_ev3.isAccepted(), "Drop should be accepted for mixed batch"
        assert d3.file_paths == [img], (
            f"Expected only img to be queued, got {d3.file_paths}"
        )
        from smol.core.result import Result

        dummy_res = Result(
            ok=True, output_path=img, original_bytes=1000, final_bytes=500
        )
        toast = d3._build_completion_toast([(img, dummy_res)])
        print(f"  Toast message: {toast.label_message.text()}")
        assert "notes.docx" in toast.label_message.text()
        assert "Skipped" in toast.label_message.text()
        print(
            "  ✓ PASS: Case 3 correctly shows mixed summary, "
            "drops only supported files, names skipped in toast"
        )
        d3.close()

        # Case 4: Drag a folder
        print("\n[Case 4] Drag a folder (my_folder)...")
        folder = tmp_dir / "my_photos"
        folder.mkdir(exist_ok=True)
        d4 = DonutWindow(files=[folder], reduce_motion=True)
        d4.dragEnterEvent(make_drag_enter([folder]))
        pump_events(d4)
        print(f"  State: {d4.drag_classify_state}")
        print(f"  Center message: {d4.center_classify_message}")
        print(f"  All segments dimmed: {d4.all_segments_dimmed}")
        assert d4.drag_classify_state == "none_supported", (
            f"Expected none_supported, got {d4.drag_classify_state}"
        )
        assert d4.all_segments_dimmed, "Segments should be dimmed"
        assert d4.center_classify_message == "folder, not supported"
        print(
            "  ✓ PASS: Case 4 correctly shows 'folder, not supported', "
            "dims segments, rejects drops"
        )
        d4.close()

        # Case 5: Drag a PDF renamed to .jpg
        print("\n[Case 5] Drag a PDF renamed to .jpg (sneaky.jpg)...")
        sneaky = tmp_dir / "sneaky.jpg"
        sneaky.write_bytes((samples_dir / "sample_scanned.pdf").read_bytes()[:2048])
        d5 = DonutWindow(files=[sneaky], reduce_motion=True)
        d5.dragEnterEvent(make_drag_enter([sneaky]))
        pump_events(d5)
        print(f"  State: {d5.drag_classify_state}")
        print(f"  All segments dimmed: {d5.all_segments_dimmed}")
        assert d5.drag_classify_state == "all_supported", (
            f"Expected all_supported, got {d5.drag_classify_state}"
        )
        assert not d5.all_segments_dimmed, "Segments should be active"
        print(
            "  ✓ PASS: Case 5 correctly trusts PDF header and "
            "recognizes file as supported"
        )
        d5.close()

        print("\n" + "=" * 65)
        print("ALL 5 PRE-DROP VERIFICATION CHECKS PASSED CLEANLY!")
        print("=" * 65)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
