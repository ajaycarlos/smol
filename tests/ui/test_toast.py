"""Unit and safety tests for ToastWindow (smol.ui.toast).

Asserts:
- Text formatting: "photo.jpg  1.02 MB → 97 KB"
- Action buttons: "Open folder", "Undo", "Copy path"
- 6-second auto-hide timer that stays paused while hovered
- Hard safety invariant: Undo deletes ONLY output files, NEVER the original.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import QApplication

from smol.core.result import Result
from smol.ui.toast import ToastWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_toast_formatting_single_file(qapp, tmp_path: Path) -> None:
    """Toast displays 'photo.jpg  1.02 MB → 97 KB' for single file jobs."""
    src = tmp_path / "photo.jpg"
    out = tmp_path / "photo_100KB.jpg"
    src.write_bytes(b"x" * 1_020_000)
    out.write_bytes(b"y" * 97_000)

    res = Result(
        ok=True,
        output_path=out,
        original_bytes=1_020_000,
        final_bytes=97_000,
        width=800,
        height=600,
        quality=85,
        steps=3,
    )

    toast = ToastWindow(results=[(src, res)], reduce_motion=True)
    try:
        msg = toast.label_message.text()
        assert "photo.jpg" in msg
        assert "1.02 MB" in msg
        assert "97 KB" in msg
        assert "→" in msg
        assert toast.btn_open.text() == "Open folder"
        assert toast.btn_undo.text() == "Undo"
        assert toast.btn_copy.text() == "Copy path"
        assert toast.btn_undo.isEnabled() is True
    finally:
        toast.close()


def test_toast_formatting_multi_file(qapp, tmp_path: Path) -> None:
    """Toast aggregates counts and total sizes for multi-file batches."""
    src1 = tmp_path / "a.jpg"
    out1 = tmp_path / "a_100KB.jpg"
    src2 = tmp_path / "b.jpg"
    out2 = tmp_path / "b_100KB.jpg"
    src1.write_bytes(b"1" * 1_000_000)
    out1.write_bytes(b"1" * 90_000)
    src2.write_bytes(b"2" * 2_400_000)
    out2.write_bytes(b"2" * 220_000)

    r1 = Result(
        ok=True, output_path=out1, original_bytes=1_000_000, final_bytes=90_000
    )
    r2 = Result(
        ok=True, output_path=out2, original_bytes=2_400_000, final_bytes=220_000
    )

    toast = ToastWindow(results=[(src1, r1), (src2, r2)], reduce_motion=True)
    try:
        msg = toast.label_message.text()
        assert "2 files" in msg
        assert "3.4 MB" in msg
        assert "310 KB" in msg
    finally:
        toast.close()


def test_toast_formatting_already_small(qapp, tmp_path: Path) -> None:
    """Toast handles files that were already <= target size."""
    src = tmp_path / "tiny.jpg"
    src.write_bytes(b"t" * 30_000)

    res = Result(
        ok=True,
        output_path=None,
        original_bytes=30_000,
        final_bytes=30_000,
        warning="Already <= target",
    )

    toast = ToastWindow(results=[(src, res)], reduce_motion=True)
    try:
        msg = toast.label_message.text()
        assert "tiny.jpg" in msg
        assert "Already ≤ target" in msg
        assert toast.btn_undo.isEnabled() is False
        assert toast.btn_copy.isEnabled() is False
    finally:
        toast.close()


def test_toast_auto_hide_and_hover_pause(qapp, tmp_path: Path) -> None:
    """Toast auto-hides after 6 s, but stays active while hovered."""
    src = tmp_path / "img.jpg"
    out = tmp_path / "img_out.jpg"
    src.write_bytes(b"src")
    out.write_bytes(b"out")

    res = Result(ok=True, output_path=out, original_bytes=1000, final_bytes=500)
    toast = ToastWindow(results=[(src, res)], auto_hide_ms=6000)
    try:
        toast.show()
        assert toast._auto_hide_timer.isActive() is True
        assert toast._auto_hide_timer.interval() == 6000

        # Simulate mouse enter -> timer pauses
        enter_ev = QEnterEvent(QPoint(10, 10), QPoint(10, 10), QPoint(10, 10))
        toast.enterEvent(enter_ev)
        assert toast._is_hovered is True
        assert toast._auto_hide_timer.isActive() is False

        # Simulate mouse leave -> timer restarts at 6000 ms
        from PySide6.QtCore import QEvent
        leave_ev = QEvent(QEvent.Type.Leave)
        toast.leaveEvent(leave_ev)
        assert toast._is_hovered is False
        assert toast._auto_hide_timer.isActive() is True
        assert toast._auto_hide_timer.interval() == 6000
    finally:
        toast.close()


def test_toast_copy_path_action(qapp, tmp_path: Path) -> None:
    """Copy path button copies the output file path to clipboard."""
    src = tmp_path / "p.jpg"
    out = tmp_path / "p_shrunk.jpg"
    src.write_bytes(b"s")
    out.write_bytes(b"o")

    res = Result(ok=True, output_path=out, original_bytes=500, final_bytes=200)
    toast = ToastWindow(results=[(src, res)], reduce_motion=True)
    try:
        copied_paths: list[str] = []
        toast.path_copied.connect(lambda p: copied_paths.append(p))

        toast.copy_path()

        assert len(copied_paths) == 1
        assert copied_paths[0] == str(out)
        clipboard = QApplication.clipboard()
        assert clipboard.text() == str(out)
        assert toast.btn_copy.text() == "✓ Copied!"
    finally:
        toast.close()


def test_toast_open_folder_action(qapp, tmp_path: Path) -> None:
    """Open folder button triggers folder opening in file manager."""
    src = tmp_path / "photo.jpg"
    out = tmp_path / "photo_shrunk.jpg"
    src.write_bytes(b"src")
    out.write_bytes(b"out")

    res = Result(ok=True, output_path=out, original_bytes=100, final_bytes=50)
    toast = ToastWindow(results=[(src, res)], reduce_motion=True)
    try:
        opened_folders: list[Path] = []
        toast.folder_opened.connect(lambda f: opened_folders.append(f))

        with patch("PySide6.QtGui.QDesktopServices.openUrl") as mock_open:
            toast.open_folder()
            assert len(opened_folders) == 1
            assert opened_folders[0] == tmp_path
            assert mock_open.called
    finally:
        toast.close()


def test_toast_undo_deletes_only_output_and_never_original(
    qapp, tmp_path: Path
) -> None:
    """HARD PROMISE: Undo deletes only the created output file, NEVER the original."""
    src = tmp_path / "family_vacation.jpg"
    out = tmp_path / "family_vacation_100KB.jpg"

    original_bytes = b"ORIGINAL_PHOTO_CONTENT_DO_NOT_TOUCH" * 1000
    src.write_bytes(original_bytes)
    out.write_bytes(b"COMPRESSED_DATA" * 50)

    assert src.exists() is True
    assert out.exists() is True

    res = Result(
        ok=True,
        output_path=out,
        original_bytes=len(original_bytes),
        final_bytes=750,
    )

    toast = ToastWindow(results=[(src, res)], reduce_motion=True)
    try:
        undone_list: list[list[Path]] = []
        toast.undone.connect(lambda d: undone_list.append(d))

        deleted = toast.undo()

        # Output was deleted
        assert deleted == [out.resolve()]
        assert out.exists() is False

        # CRITICAL SAFETY: Original file MUST exist and be bit-for-bit identical!
        assert src.exists() is True
        assert src.read_bytes() == original_bytes

        # Toast state updated
        assert toast._undone is True
        assert toast.btn_undo.isEnabled() is False
        assert toast.btn_undo.text() == "Undone"
        assert "Output deleted" in toast.label_status.text()
    finally:
        toast.close()


def test_toast_undo_safety_guards(qapp, tmp_path: Path) -> None:
    """Defensive guards strictly reject deleting original file even on
    corrupt inputs.
    """
    src = tmp_path / "important.jpg"
    src.write_bytes(b"CRITICAL_DATA")

    # Corrupt case 1: output_path matches source_path
    corrupt_res = Result(ok=True, output_path=src, original_bytes=100, final_bytes=100)
    toast1 = ToastWindow(results=[(src, corrupt_res)], reduce_motion=True)
    try:
        deleted = toast1.undo()
        assert deleted == []
        # Original is untouched
        assert src.exists() is True
        assert src.read_bytes() == b"CRITICAL_DATA"
    finally:
        toast1.close()

    # Corrupt case 2: output_path is a symlink pointing to source
    symlink_out = tmp_path / "symlink_out.jpg"
    symlink_out.symlink_to(src)
    assert symlink_out.resolve() == src.resolve()

    sym_res = Result(
        ok=True, output_path=symlink_out, original_bytes=100, final_bytes=100
    )
    toast2 = ToastWindow(results=[(src, sym_res)], reduce_motion=True)
    try:
        deleted = toast2.undo()
        assert deleted == []
        assert src.exists() is True
        assert src.read_bytes() == b"CRITICAL_DATA"
    finally:
        toast2.close()
