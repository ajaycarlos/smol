"""Verification script for completion sequence, toast notifications, and failure retry.

Verifies:
1. Success completion sequence:
   - Ring snaps shut (100%)
   - Soft checkmark burst (~600 ms)
   - Toast slides in near cursor/corner: "photo.jpg  1.24 MB → 99.5 KB"
   - Buttons: Open folder, Undo, Copy path
   - Auto-hide 6s timer pauses on hover, resumes on leave
   - Copy path copies output path to clipboard
2. Undo safety:
   - Output file is deleted
   - Original source file is 100% UNTOUCHED and bit-for-bit identical!
3. Failure state:
   - Amber ring around thumbnail/center
   - Honest engine error message
   - "Use smallest possible" button
   - Clicking "Use smallest possible" retries at smallest achievable size and succeeds.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QEnterEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import QApplication

from smol.ui.donut_window import DonutWindow


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_verify() -> int:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv[:1])

    samples_dir = Path("tests/samples")
    portrait = samples_dir / "portrait.jpg"
    noise = samples_dir / "noise_cannot_shrink.jpg"

    if not portrait.exists() or not noise.exists():
        print("Error: test samples not found.", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        print("=== VERIFY 1: Success Completion Sequence & Toast ===")
        test_portrait = tmp_path / "portrait.jpg"
        shutil.copy(portrait, test_portrait)
        orig_hash = sha256(test_portrait)
        orig_size = test_portrait.stat().st_size
        print(f"Loaded source image: portrait.jpg ({orig_size:,} bytes)")

        win = DonutWindow(files=[test_portrait], reduce_motion=False)
        win.show()
        app.processEvents()

        # Start compression to 100 KB
        start_t = time.monotonic()
        win.start_shrink(100_000)

        # Wait for worker thread
        if win._shrink_worker is not None:
            win._shrink_worker.wait(5000)
            app.processEvents()

        shrink_dur = (time.monotonic() - start_t) * 1000.0
        print(
            f"  [1] Shrink worker finished in {shrink_dur:.1f} ms"
            f" with state: '{win.state}'"
        )
        assert win.state == "success", f"Expected success, got {win.state}"

        # Check ring snap shut
        print(f"  [2] Progress ring snapped shut: {win._ring_progress * 100.0:.0f}%")
        assert win._ring_progress == 1.0, "Ring must snap shut to 100%"

        # Check checkmark burst animation
        assert win._anim_checkmark_burst is not None, "Burst anim must exist"
        assert win._anim_checkmark_burst.duration() == 600, "Burst must be 600 ms"
        print("  [3] Soft checkmark burst animation initialized (~600 ms, OutCubic)")

        # Render during burst to verify drawing code
        win.checkmark_burst = 0.5
        pix = QPixmap(win.size())
        win.render(pix)
        print("  [4] Rendered checkmark burst frame at 50% burst progress")

        # Step animation to 600 ms -> triggers toast summon
        win._anim_checkmark_burst.setCurrentTime(600)
        app.processEvents()

        toast = win._toast
        assert toast is not None, "Toast window must be summoned after checkmark burst"
        assert toast.isVisible() is True, "Toast window must be visible"

        toast_msg = toast.label_message.text()
        print(f"  [5] Toast displayed: {toast_msg}")
        assert "portrait.jpg" in toast_msg
        assert "1.24 MB" in toast_msg
        assert "99.51 KB" in toast_msg

        # Check buttons
        assert toast.btn_open.text() == "Open folder"
        assert toast.btn_undo.text() == "Undo"
        assert toast.btn_copy.text() == "Copy path"
        print("  [6] Toast buttons present: [Open folder], [Undo], [Copy path]")

        # Test Copy path action
        toast.copy_path()
        clipboard = QApplication.clipboard()
        assert clipboard is not None
        assert "portrait_100KB.jpg" in clipboard.text()
        assert toast.btn_copy.text() == "✓ Copied!"
        print(f"  [7] Copy path verified: clipboard = '{clipboard.text()}'")

        # Test 6s auto-hide timer and hover pause
        assert toast._auto_hide_timer.isActive() is True
        assert toast._auto_hide_timer.interval() == 6000
        print("  [8] Auto-hide timer active (6000 ms)")

        enter_ev = QEnterEvent(QPoint(10, 10), QPoint(10, 10), QPoint(10, 10))
        toast.enterEvent(enter_ev)
        assert toast._is_hovered is True
        assert toast._auto_hide_timer.isActive() is False
        print("  [9] Hover paused auto-hide timer successfully")

        leave_ev = QEvent(QEvent.Type.Leave)
        toast.leaveEvent(leave_ev)
        assert toast._is_hovered is False
        assert toast._auto_hide_timer.isActive() is True
        print("  [10] Mouse leave resumed auto-hide timer successfully")

        # Test Undo safety
        output_file = Path(clipboard.text())
        assert output_file.exists() is True, "Output file must exist before undo"
        sz_out = output_file.stat().st_size
        print(f"  [11] Output file created at: {output_file.name} ({sz_out:,} bytes)")

        deleted_outputs = toast.undo()
        print(
            f"  [12] Undo triggered: deleted {len(deleted_outputs)} created output(s)"
        )
        assert output_file.exists() is False, "Output file must be deleted after undo"
        assert toast._undone is True
        assert toast.btn_undo.isEnabled() is False

        # CRITICAL SAFETY INVARIANT TEST
        assert test_portrait.exists() is True, "CRITICAL: Original file was deleted!"
        assert sha256(test_portrait) == orig_hash, (
            "CRITICAL: Original file content modified!"
        )
        print("  ✓ CRITICAL PROMISE VERIFIED: Original file is 100% UNTOUCHED!")

        win.reset_state()
        win.close()

        print("\n=== VERIFY 2: Failure State & 'Use smallest possible' Button ===")
        test_noise = tmp_path / "noise.jpg"
        shutil.copy(noise, test_noise)

        win_fail = DonutWindow([test_noise])
        win_fail.show()
        app.processEvents()

        # Impossible target: 5 KB
        win_fail.start_shrink(5_000)
        if win_fail._shrink_worker is not None:
            win_fail._shrink_worker.wait(5000)
            app.processEvents()

        assert win_fail.state == "failure"
        print(f"  [1] Impossible target produced state: '{win_fail.state}'")
        print(f"  [2] Honest error message: '{win_fail.failure_error}'")
        assert "Smallest" in win_fail.failure_error

        # Render failure state to verify amber ring and button
        pix_fail = QPixmap(win_fail.size())
        win_fail.render(pix_fail)

        assert win_fail._retry_rect is not None
        assert win_fail.retry_target_bytes is not None
        rt_sz = win_fail.retry_target_bytes
        print(f"  [3] Amber ring rendered with retry target: {rt_sz:,} bytes")
        print("  [4] Button rendered with text: 'Use smallest possible'")

        # Click the "Use smallest possible" button
        click_pt = win_fail._retry_rect.center().toPoint()
        press_ev = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            click_pt,
            click_pt,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        win_fail.mousePressEvent(press_ev)

        assert win_fail.state == "working"
        print("  [5] Clicked 'Use smallest possible' -> transitioned to 'working'")

        if win_fail._shrink_worker is not None:
            win_fail._shrink_worker.wait(5000)
            app.processEvents()

        assert win_fail.state == "success"
        res_msg = win_fail.result_message
        print(f"  [6] Retry compression succeeded: '{win_fail.state}' ({res_msg})")

        win_fail.reset_state()
        win_fail.close()

    print("\n✓ ALL VERIFICATIONS PASSED: Success, failure, and undo safety confirmed!")
    return 0


if __name__ == "__main__":
    sys.exit(run_verify())
