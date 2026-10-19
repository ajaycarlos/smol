#!/usr/bin/env python3
"""Standalone verification script for audio shrinking engine.

VERIFY check from task:
A 3-minute generated tone shrinks to the target size and plays.
Generates test audio with ffmpeg lavfi sine (no real audio in the repo).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from smol.core.audio import shrink_audio
from smol.core.media_math import probe_media
from smol.core.size import format_size


def verify_playback(path: Path) -> None:
    """Verify that an audio file decodes cleanly without errors."""
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(path),
        "-f",
        "null",
        "/dev/null",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"Audio playback/decode failed: {res.stderr}")


def main() -> int:
    print("=" * 60)
    print("smol VERIFY: 3-Minute Tone Audio Shrinking")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="smol_audio_verify_") as tmpdir:
        tmp_path = Path(tmpdir)
        src_path = tmp_path / "three_minute_tone.mp3"

        # Step 1: Generate 3-minute tone (180s) using ffmpeg lavfi sine
        print("1. Generating 3-minute synthetic sine tone (180s)...")
        gen_cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=180",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(src_path),
        ]
        res = subprocess.run(gen_cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            print(f"FAILED to generate test audio: {res.stderr}")
            return 1

        orig_bytes = src_path.stat().st_size
        probe = probe_media(src_path)
        print(f"   Original file: {src_path.name}")
        print(f"   Size: {orig_bytes:,} bytes ({format_size(orig_bytes)})")
        print(f"   Duration: {probe.duration:.2f}s, Audio stream: {probe.has_audio}")

        # Step 2: Target 1 MB
        target_bytes = 1_000_000  # 1 MB
        t_fmt = format_size(target_bytes)
        print(f"\n2. Shrinking to target {target_bytes:,} bytes ({t_fmt})...")
        result = shrink_audio(src_path, target_bytes=target_bytes)

        if not result.ok:
            print(f"   FAILED: {result.error}")
            return 1

        f_fmt = format_size(result.final_bytes)
        print(f"   ✓ Shrink successful: {result.steps} step(s)")
        print(f"   Output path: {result.output_path}")
        print(f"   Final size:  {result.final_bytes:,} bytes ({f_fmt})")
        print(f"   Target size: {target_bytes:,} bytes ({t_fmt})")
        pct = (result.final_bytes / target_bytes) * 100
        print(f"   Landing percentage: {pct:.2f}% of target")

        # Step 3: Promise verifications
        print("\n3. Verifying core promises...")
        assert result.output_path is not None, "Missing output path"
        assert result.output_path.is_file(), "Output file does not exist"
        assert result.final_bytes <= target_bytes, (
            f"Output ({result.final_bytes}) exceeds target ({target_bytes})!"
        )
        assert result.final_bytes == result.output_path.stat().st_size, "Size mismatch"
        assert src_path.stat().st_size == orig_bytes, "Original file was modified!"
        print("   ✓ Output file exists and is strictly <= target bytes")
        print("   ✓ Output disk size matches Result.final_bytes")
        print("   ✓ Original file is completely untouched")

        # Step 4: Playback / decode verification
        print("\n4. Verifying playback / audio decoding...")
        try:
            verify_playback(result.output_path)
            print("   ✓ ffmpeg decode test passed with 0 errors (plays cleanly)")
        except RuntimeError as exc:
            print(f"   ✗ Playback verification failed: {exc}")
            return 1

        out_probe = probe_media(result.output_path)
        print(f"   ✓ Output stream duration verified: {out_probe.duration:.2f}s")

    print("\n" + "=" * 60)
    print("ALL VERIFICATIONS PASSED")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
