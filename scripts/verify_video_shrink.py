#!/usr/bin/env python3
"""Verification script for video shrinking engine.

Verifies: A 30s test clip lands at 90–100% of an 8 MB target and plays correctly.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from smol.core.media_math import probe_media
from smol.core.size import format_size
from smol.core.video import shrink_video


def generate_30s_clip(path: Path) -> Path:
    """Generate a 30-second 1080p synthetic video (~20 MB) with video and audio."""
    print("Generating 30s synthetic 1080p video clip via lavfi (testsrc2 + sine)...")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=1920x1080:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:sample_rate=44100",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-t",
        "30.0",
        "-c:v",
        "libx264",
        "-b:v",
        "5000k",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


def verify_playback(path: Path) -> bool:
    """Verify that the video file decodes completely without errors."""
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(path),
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        print(f"Playback decode error: {proc.stderr}")
        return False
    return True


def main() -> int:
    target_bytes = 8_000_000  # 8 MB (decimal 1 KB = 1000 B, 8 MB = 8,000,000 B)
    min_acceptable = int(target_bytes * 0.90)  # 7,200,000 bytes (90%)

    with tempfile.TemporaryDirectory() as td:
        src_path = Path(td) / "test_clip_30s.mp4"
        generate_30s_clip(src_path)

        orig_bytes = src_path.stat().st_size
        print(
            f"Original clip created: {format_size(orig_bytes)} ({orig_bytes:,} bytes)"
        )

        print(f"Target size: {format_size(target_bytes)} ({target_bytes:,} bytes)")
        print(
            f"Acceptable range (90–100%): {min_acceptable:,} – {target_bytes:,} bytes"
        )

        print("\nRunning shrink_video with two-pass x264...")
        result = shrink_video(src_path, target_bytes=target_bytes)

        if not result.ok:
            print(f"ERROR: shrink_video failed: {result.error}", file=sys.stderr)
            return 1

        output_path = result.output_path
        if not output_path or not output_path.exists():
            print("ERROR: Output file does not exist!", file=sys.stderr)
            return 1

        final_bytes = output_path.stat().st_size
        pct = (final_bytes / target_bytes) * 100.0

        print(f"\nShrunk file created: {output_path.name}")
        print(
            f"Final size: {format_size(final_bytes)} ({final_bytes:,} bytes) "
            f"-> {pct:.2f}% of target"
        )
        print(f"Resolution: {result.width}x{result.height}")
        print(f"Encode steps: {result.steps}")

        # 1. Size bounds check
        if final_bytes > target_bytes:
            print(
                f"FAILED: Final size {final_bytes} exceeds target {target_bytes}!",
                file=sys.stderr,
            )
            return 1

        if final_bytes < min_acceptable:
            print(
                f"FAILED: Final size {final_bytes} is below 90% floor "
                f"({min_acceptable})!",
                file=sys.stderr,
            )
            return 1

        print(
            f"✓ Size check PASSED: {final_bytes:,} bytes is within 90–100% ({pct:.2f}%)"
        )

        # 2. ffprobe media verification
        info = probe_media(output_path)
        print(f"✓ Probed duration: {info.duration:.2f}s (expected ~30.0s)")
        print(f"✓ Probed resolution: {info.resolution} (fps: {info.fps})")
        print(f"✓ Streams present: video={info.has_video}, audio={info.has_audio}")

        if not info.has_video or not info.has_audio:
            print(
                "FAILED: Output media missing video or audio stream!",
                file=sys.stderr,
            )
            return 1

        if abs(info.duration - 30.0) > 1.0:
            print(
                f"FAILED: Output duration {info.duration}s deviated from 30s!",
                file=sys.stderr,
            )
            return 1

        # 3. Decode playback test
        print("Testing video decode playback with ffmpeg...")
        if not verify_playback(output_path):
            print("FAILED: Playback decode failed!", file=sys.stderr)
            return 1
        print("✓ Playback decode check PASSED: complete stream decoded with 0 errors.")

        print("\n========================================================")
        print("VERIFY PASSED: 30s clip landed at 90–100% of 8 MB and plays correctly!")
        print("========================================================")
        return 0


if __name__ == "__main__":
    sys.exit(main())
