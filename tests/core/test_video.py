"""Tests for video shrinking engine using two-pass x264 via ffmpeg."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from smol.core.media_math import probe_media
from smol.core.video import shrink_video


def _generate_synthetic_video(
    path: Path,
    duration: float = 3.0,
    width: int = 640,
    height: int = 360,
    fps: int = 25,
    has_audio: bool = True,
) -> Path:
    """Generate a synthetic test video using ffmpeg lavfi (testsrc2 + sine)."""
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size={width}x{height}:rate={fps}",
    ]
    if has_audio:
        cmd.extend([
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=44100",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
        ])
    cmd.extend([
        "-t",
        str(duration),
        "-c:v",
        "libx264",
        "-b:v",
        "2500k",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ])
    subprocess.run(cmd, check=True, capture_output=True)
    return path


@pytest.fixture(scope="module")
def sample_clip(tmp_path_factory) -> Path:
    """Module-level fixture providing a 4-second 720p synthetic clip (~1.5 MB)."""
    tmp_dir = tmp_path_factory.mktemp("video_samples")
    clip_path = tmp_dir / "sample_720p.mp4"
    return _generate_synthetic_video(clip_path, duration=4.0, width=1280, height=720)


def test_shrink_video_file_not_found(tmp_path: Path):
    """Missing source file returns ok=False with helpful error."""
    non_existent = tmp_path / "does_not_exist.mp4"
    res = shrink_video(non_existent, target_bytes=500_000)
    assert not res.ok
    assert "not found" in res.error.lower()


def test_shrink_video_already_small(sample_clip: Path, tmp_path: Path):
    """File already <= target_bytes is not re-encoded or touched."""
    orig_bytes = sample_clip.stat().st_size
    large_target = orig_bytes + 500_000

    res = shrink_video(sample_clip, target_bytes=large_target)
    assert res.ok
    assert res.output_path == sample_clip
    assert res.final_bytes == orig_bytes
    assert res.warning is not None
    assert "already" in res.warning.lower()


def test_shrink_video_impossible_target(sample_clip: Path):
    """Target too small for duration & audio floor returns honest failure."""
    # Target of 1000 bytes for a 4s video is impossible (cannot fit audio + video)
    res = shrink_video(sample_clip, target_bytes=1000)
    assert not res.ok
    assert res.error is not None
    assert "too small" in res.error.lower() or "impossible" in res.error.lower()


def test_shrink_video_standard_clip(sample_clip: Path, tmp_path: Path):
    """Shrink a 4s clip to 500 KB: output <= target, playable, >= 85% of target."""
    target_bytes = 500_000
    test_src = tmp_path / "input.mp4"
    shutil.copy2(sample_clip, test_src)
    orig_mtime = test_src.stat().st_mtime_ns

    res = shrink_video(test_src, target_bytes=target_bytes)

    assert res.ok
    assert res.output_path is not None
    assert res.output_path.exists()
    assert res.output_path != test_src
    # Source file must be completely untouched
    assert test_src.stat().st_mtime_ns == orig_mtime

    # Output size must be <= target and aim for 90-100% (safe margin >= 85%)
    assert res.final_bytes <= target_bytes
    assert res.final_bytes >= target_bytes * 0.85
    assert res.output_path.stat().st_size == res.final_bytes

    # Verify output is valid playable media with ffprobe
    info = probe_media(res.output_path)
    assert info.has_video
    assert info.has_audio
    assert info.duration >= 3.8
    assert res.width == info.resolution[0]
    assert res.height == info.resolution[1]


def test_shrink_video_resolution_stepdown(tmp_path: Path):
    """When bitrate produces too low bpp, resolution steps down ladder."""
    # Create a 1080p clip (1920x1080) of 3s
    src_1080p = tmp_path / "clip_1080p.mp4"
    _generate_synthetic_video(src_1080p, duration=3.0, width=1920, height=1080)

    # Shrink to 200 KB (very small for 1080p, bpp will trigger stepdown)
    res = shrink_video(src_1080p, target_bytes=200_000)

    assert res.ok
    assert res.output_path is not None
    assert res.output_path.exists()
    assert res.final_bytes <= 200_000
    # Height must have stepped down below 1080
    assert res.height is not None
    assert res.height < 1080
    assert res.height in (720, 480, 360)


def test_shrink_video_pass_log_cleanup_on_success_and_failure(
    sample_clip: Path, tmp_path: Path
):
    """Pass-log temp files are always cleaned up even on success or failure."""
    test_src = tmp_path / "input_cleanup.mp4"
    shutil.copy2(sample_clip, test_src)

    # We track files before and after in tmp directory
    temp_dir_before = set(os.listdir(tempfile.gettempdir()))

    res = shrink_video(test_src, target_bytes=400_000)
    assert res.ok

    # Verify no dangling passlog files in /tmp or next to output
    temp_dir_after = set(os.listdir(tempfile.gettempdir()))
    new_temp_files = temp_dir_after - temp_dir_before
    dangling_logs = [
        f for f in new_temp_files if "pass" in f.lower() or "ffmpeg" in f.lower()
    ]
    assert not dangling_logs, f"Found dangling pass logs in temp dir: {dangling_logs}"

    local_logs = list(tmp_path.glob("*pass*.log*"))
    assert not local_logs, f"Found dangling pass logs in local dir: {local_logs}"


def test_shrink_video_retry_on_overshoot(
    monkeypatch, sample_clip: Path, tmp_path: Path
):
    """If output is over target, bitrate is cut by 5% and retried (max 3 retries)."""
    test_src = tmp_path / "input_retry.mp4"
    shutil.copy2(sample_clip, test_src)

    from smol.core import video

    original_run_ffmpeg = video._run_ffmpeg_two_pass
    calls: list[int] = []

    def mock_run_ffmpeg(*args, **kwargs):
        v_bitrate = kwargs.get("video_bitrate", args[2] if len(args) > 2 else None)
        calls.append(v_bitrate)
        temp_out = kwargs.get("temp_out_path", args[1] if len(args) > 1 else None)
        if len(calls) == 1:
            # First attempt produces a file exceeding target (360 KB > 350 KB)
            with open(temp_out, "wb") as f:
                f.write(b"\x00" * 360_000)
            return
        return original_run_ffmpeg(*args, **kwargs)

    monkeypatch.setattr(video, "_run_ffmpeg_two_pass", mock_run_ffmpeg)

    res = shrink_video(test_src, target_bytes=350_000)
    assert res.ok
    assert res.final_bytes <= 350_000
    assert len(calls) == 2
    # Verify exact 5% reduction on retry
    assert calls[1] == int(calls[0] * 0.95)


def test_shrink_video_collision_resolution(sample_clip: Path, tmp_path: Path):
    """Running shrink multiple times increments collision suffix -1, -2."""
    test_src = tmp_path / "collision_test.mp4"
    shutil.copy2(sample_clip, test_src)

    res1 = shrink_video(test_src, target_bytes=450_000)
    assert res1.ok
    assert res1.output_path.name == "collision_test_450KB.mp4"

    res2 = shrink_video(test_src, target_bytes=450_000)
    assert res2.ok
    assert res2.output_path.name == "collision_test_450KB-1.mp4"
    assert res1.output_path.exists()
    assert res2.output_path.exists()


def test_shrink_video_retry_exhaustion(monkeypatch, sample_clip: Path, tmp_path: Path):
    """When retries are exhausted without fitting target, returns honest failure."""
    test_src = tmp_path / "input_exhaust.mp4"
    shutil.copy2(sample_clip, test_src)

    from smol.core import video

    calls: list[int] = []

    def mock_run_ffmpeg(*args, **kwargs):
        calls.append(1)
        temp_out = kwargs.get("temp_out_path", args[1] if len(args) > 1 else None)
        # Always write an oversized file
        with open(temp_out, "wb") as f:
            f.write(b"\x00" * 400_000)

    monkeypatch.setattr(video, "_run_ffmpeg_two_pass", mock_run_ffmpeg)

    res = video.shrink_video(test_src, target_bytes=350_000)
    assert not res.ok
    assert res.error is not None
    assert "unreachable" in res.error.lower()
    # Initial attempt + 3 retries = 4 calls
    assert len(calls) == 4
    # Destination file should not exist
    assert not (tmp_path / "input_exhaust_350KB.mp4").exists()


def test_shrink_video_cleanup_on_exception(
    monkeypatch, sample_clip: Path, tmp_path: Path
):
    """Temporary pass logs and output files are cleaned up on exception."""
    test_src = tmp_path / "input_fail.mp4"
    shutil.copy2(sample_clip, test_src)

    from smol.core import video

    def mock_fail(*args, **kwargs):
        raise RuntimeError("Simulated crash")

    monkeypatch.setattr(video, "_run_ffmpeg_two_pass", mock_fail)

    temp_dir_before = set(os.listdir(tempfile.gettempdir()))
    res = video.shrink_video(test_src, target_bytes=300_000)
    assert not res.ok
    assert "Simulated crash" in res.error

    temp_dir_after = set(os.listdir(tempfile.gettempdir()))
    new_temp_files = [
        f for f in temp_dir_after - temp_dir_before if "pass" in f.lower()
    ]
    assert not new_temp_files


def test_shrink_video_without_audio(tmp_path: Path):
    """Video with no audio track compresses cleanly with -an."""
    src_no_audio = tmp_path / "clip_silent.mp4"
    _generate_synthetic_video(
        src_no_audio, duration=3.0, width=640, height=360, has_audio=False
    )

    res = shrink_video(src_no_audio, target_bytes=300_000)
    assert res.ok
    assert res.output_path.exists()
    assert res.final_bytes <= 300_000

    info = probe_media(res.output_path)
    assert info.has_video
    assert not info.has_audio

