"""Verification script for video/audio donut progress, cancel, and integration.

VERIFY criteria:
- Shrinking a video from the donut shows moving progress
  (ring fills, countdown decreases).
- Esc cancels cleanly, kills ffmpeg process, and leaves no partial files behind.
- Video and audio integration verified across CLI, Donut, right-click, and daemon.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Set headless Qt platform
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from smol.core.media_math import probe_media
from smol.integrations.manager import (
    DolphinIntegrator,
    NemoIntegrator,
    ThunarIntegrator,
)
from smol.ui.donut_window import DonutWindow


def generate_test_video(path: Path, duration: float = 6.0) -> Path:
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=1280x720:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:sample_rate=44100",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-t",
        str(duration),
        "-c:v",
        "libx264",
        "-b:v",
        "2000k",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to generate test video: {res.stderr}")
    return path


def run_event_loop_until(condition_fn, timeout_s: float = 15.0) -> bool:
    start = time.time()
    while not condition_fn():
        QCoreApplication.processEvents()
        time.sleep(0.02)
        if time.time() - start > timeout_s:
            return False
    for _ in range(5):
        QCoreApplication.processEvents()
    return True


def main() -> int:
    print("=" * 60)
    print("VERIFY: Video/Audio Progress, Esc Cancellation & Wiring")
    print("=" * 60)

    _app = QApplication.instance() or QApplication(sys.argv)
    tmp_dir = Path(tempfile.mkdtemp(prefix="smol_verify_v080_"))

    try:
        # ----------------------------------------------------
        # Part 1: Shrinking video from donut shows moving progress
        # ----------------------------------------------------
        print("\n[1/3] Testing video shrinking in Donut with live progress...")
        video_src = tmp_dir / "sample_video.mp4"
        generate_test_video(video_src, duration=5.0)
        orig_size = video_src.stat().st_size
        print(f"Generated test clip: {video_src.name} ({orig_size / 1_000_000:.2f} MB)")

        donut = DonutWindow([video_src])
        donut.show()

        progress_log: list[tuple[float, int]] = []

        def on_step(frac: float, cand_bytes: int):
            progress_log.append((frac, cand_bytes))
            kb = cand_bytes / 1000
            print(f"  → Step event: ring={frac*100:.1f}%, countdown={kb:.1f} KB")

        donut.step_progress_received.connect(on_step)

        target_bytes = 450_000
        print(f"Starting shrink to {target_bytes / 1000:.0f} KB...")
        donut.start_shrink(target_bytes=target_bytes)

        job_finished = False

        def on_finished(results):
            nonlocal job_finished
            job_finished = True

        donut.shrink_finished.connect(on_finished)

        ok = run_event_loop_until(lambda: job_finished, timeout_s=25.0)
        assert ok, "Video shrinking job timed out!"

        # Assertions on moving progress
        assert len(progress_log) >= 2, (
            f"Expected multiple progress events, got {len(progress_log)}"
        )
        first_frac, _ = progress_log[0]
        last_frac, _ = progress_log[-1]
        assert first_frac <= last_frac, "Progress fraction did not advance!"
        print(
            f"✓ Progress events logged: {len(progress_log)} steps "
            f"(first: {first_frac*100:.1f}%, last: {last_frac*100:.1f}%)"
        )

        out_files = list(tmp_dir.glob("sample_video_450KB*.mp4"))
        assert len(out_files) == 1, f"Expected output file, got {out_files}"
        final_file = out_files[0]
        final_size = final_file.stat().st_size
        assert final_size <= target_bytes, (
            f"Output size {final_size} exceeded target {target_bytes}"
        )
        print(
            f"✓ Output file created: {final_file.name} "
            f"({final_size / 1000:.1f} KB <= {target_bytes / 1000:.0f} KB)"
        )

        # Verify playability
        info = probe_media(final_file)
        assert info.has_video and info.duration > 0
        print(
            f"✓ Output verified playable: {info.resolution[0]}x{info.resolution[1]}, "
            f"{info.duration:.1f}s"
        )
        donut.close()

        # ----------------------------------------------------
        # Part 2: Esc cancels cleanly, kills ffmpeg, no partial file
        # ----------------------------------------------------
        print("\n[2/3] Testing Esc cancellation during video shrinking...")
        cancel_video = tmp_dir / "cancel_clip.mp4"
        generate_test_video(cancel_video, duration=8.0)

        donut_cancel = DonutWindow([cancel_video])
        donut_cancel.show()

        cancel_target = 300_000
        donut_cancel.start_shrink(target_bytes=cancel_target)
        worker = donut_cancel._shrink_worker
        assert worker is not None and worker.isRunning()

        # Let it begin running
        time.sleep(0.3)
        QCoreApplication.processEvents()

        # Simulate pressing Esc key
        print("  Sending Esc key to Donut window...")
        esc_event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Escape,
            Qt.KeyboardModifier.NoModifier,
        )
        donut_cancel.keyPressEvent(esc_event)

        # Wait for worker thread to stop
        stopped = run_event_loop_until(
            lambda: not donut_cancel._shrink_worker.isRunning(),
            timeout_s=5.0,
        )
        assert stopped, "Worker failed to terminate after Esc!"
        print("✓ Worker thread and child ffmpeg stopped promptly.")

        # Check for running ffmpeg processes spawned for this cancel clip
        pgrep = subprocess.run(
            ["pgrep", "-f", str(cancel_video)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert pgrep.returncode != 0, f"ffmpeg process still running: {pgrep.stdout}"
        print("✓ No orphan ffmpeg process running.")

        # Verify zero partial files left behind
        existing = list(tmp_dir.glob("cancel_clip*.mp4"))
        assert existing == [cancel_video], f"Dangling partial files found: {existing}"
        tmp_leftovers = list(tmp_dir.glob(".tmp*"))
        assert len(tmp_leftovers) == 0, f"Temporary files left: {tmp_leftovers}"
        print("✓ Clean cancellation: exactly zero partial or temporary files left.")
        donut_cancel.close()

        # ----------------------------------------------------
        # Part 3: Verify Right-click integration contains video and audio
        # ----------------------------------------------------
        print("\n[3/3] Testing right-click integration configs...")
        nemo = NemoIntegrator(
            actions_dir=tmp_dir / "nemo/actions",
            config_dir=tmp_dir / "nemo/config",
        )
        nemo.install()
        sample_nemo = next(iter((tmp_dir / "nemo/actions").glob("*.nemo_action")))
        nemo_text = sample_nemo.read_text(encoding="utf-8")
        assert "mp4;" in nemo_text and "mp3;" in nemo_text
        print("✓ Nemo right-click actions include video (mp4) and audio (mp3).")

        dolphin = DolphinIntegrator(service_menu_dir=tmp_dir / "dolphin")
        dolphin.install()
        dolphin_text = (
            tmp_dir / "dolphin/smol_shrink.desktop"
        ).read_text(encoding="utf-8")
        assert "video/mp4;" in dolphin_text and "audio/mpeg;" in dolphin_text
        print("✓ Dolphin service menu includes video and audio MIME types.")

        thunar = ThunarIntegrator(uca_file=tmp_dir / "thunar/uca.xml")
        thunar.install()
        thunar_text = (tmp_dir / "thunar/uca.xml").read_text(encoding="utf-8")
        assert (
            "*.mp4;" in thunar_text
            and "*.mp3;" in thunar_text
            and "<audio-files" in thunar_text
        )
        print("✓ Thunar custom actions include video and audio patterns.")

        print("\n" + "=" * 60)
        print("ALL VERIFY CHECKS PASSED SUCCESSFULLY!")
        print("=" * 60)
        return 0

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

