import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from smol.core.media_math import (
    MediaInfo,
    compute_audio_bitrate,
    compute_video_bitrate,
    decide_resolution,
    probe_media,
)


def test_compute_video_bitrate_standard():
    # 10s video, 5 MB target, 64 kbps audio, 0.92 safety
    # Total bits = 5_000_000 * 8 * 0.92 = 36_800_000 bits
    # Total bps = 3,680,000 bps
    # Video bps = 3,680,000 - 64,000 = 3,616,000 bps (~3616 kbps)
    bitrate = compute_video_bitrate(
        duration=10.0,
        target_bytes=5_000_000,
        audio_bitrate=64_000,
        safety_factor=0.92,
    )
    assert bitrate == 3_616_000


def test_compute_video_bitrate_short_clip():
    # 0.5s clip, 1 MB target, 64 kbps audio
    # Total bits = 1_000_000 * 8 * 0.92 = 7_360_000 bits
    # Total bps = 7_360_000 / 0.5 = 14_720_000 bps
    # Video bps = 14,720,000 - 64,000 = 14,656,000 bps
    bitrate = compute_video_bitrate(
        duration=0.5,
        target_bytes=1_000_000,
        audio_bitrate=64_000,
        safety_factor=0.92,
    )
    assert bitrate == 14_656_000


def test_compute_video_bitrate_huge_target():
    # 60s clip, 1 GB target (1,000,000,000 bytes)
    # Total bits = 1,000,000,000 * 8 * 0.92 = 7,360,000,000 bits
    # Total bps = 7,360,000,000 / 60 = 122,666,666 bps
    bitrate = compute_video_bitrate(
        duration=60.0,
        target_bytes=1_000_000_000,
        audio_bitrate=128_000,
        safety_factor=0.92,
    )
    assert bitrate == 122_538_666


def test_compute_video_bitrate_impossible_target():
    # 60s clip, target 100 KB = 100_000 bytes
    # Total bits = 100_000 * 8 * 0.92 = 736_000 bits
    # Total bps = 736_000 / 60 = 12,266 bps (~12.2 kbps)
    # Audio alone at 64 kbps exceeds total available bandwidth
    with pytest.raises(ValueError, match="too small"):
        compute_video_bitrate(
            duration=60.0,
            target_bytes=100_000,
            audio_bitrate=64_000,
            safety_factor=0.92,
        )


def test_compute_video_bitrate_edge_cases():
    # Zero or negative duration
    with pytest.raises(ValueError, match="duration must be positive"):
        compute_video_bitrate(duration=0.0, target_bytes=1_000_000)

    with pytest.raises(ValueError, match="duration must be positive"):
        compute_video_bitrate(duration=-5.0, target_bytes=1_000_000)

    # Zero or negative target
    with pytest.raises(ValueError, match="target_bytes must be positive"):
        compute_video_bitrate(duration=10.0, target_bytes=0)

    with pytest.raises(ValueError, match="target_bytes must be positive"):
        compute_video_bitrate(duration=10.0, target_bytes=-1000)

    # Safety factor <= 0 or > 1
    with pytest.raises(ValueError, match="safety_factor"):
        compute_video_bitrate(duration=10.0, target_bytes=1_000_000, safety_factor=0.0)

    with pytest.raises(ValueError, match="safety_factor"):
        compute_video_bitrate(duration=10.0, target_bytes=1_000_000, safety_factor=1.5)


def test_decide_resolution_high_bpp_keeps_source():
    # 1080p source @ 30 fps, video bitrate 5,000,000 bps
    # bpp = 5_000_000 / (1920 * 1080 * 30) = 5_000_000 / 62_208_000 ~= 0.0803 > 0.06
    w, h = decide_resolution(
        source_width=1920,
        source_height=1080,
        fps=30.0,
        video_bitrate=5_000_000,
    )
    assert (w, h) == (1920, 1080)


def test_decide_resolution_step_down_ladder():
    # 1080p source @ 30 fps
    # If bitrate is 1,500,000 bps:
    # 1080p bpp = 1,500,000 / 62_208_000 ~= 0.024 (< 0.06) -> step down to 720p
    # 720p bpp = 1,500,000 / (1280 * 720 * 30) ~= 0.054 (< 0.06)
    # -> step down to 480p (854x480 or 852x480, aspect 16:9)
    # 480p (854x480) bpp = 1,500,000 / (854 * 480 * 30) ~= 0.122 (>= 0.06) -> 480p!
    w, h = decide_resolution(
        source_width=1920,
        source_height=1080,
        fps=30.0,
        video_bitrate=1_500_000,
    )
    assert h == 480
    assert w % 2 == 0  # Even dimensions for video encoding
    assert abs(w / h - 16 / 9) < 0.05

    # Very low bitrate: 300,000 bps -> steps down all the way to 360p floor
    w360, h360 = decide_resolution(
        source_width=1920,
        source_height=1080,
        fps=30.0,
        video_bitrate=300_000,
    )
    assert h360 == 360
    assert w360 % 2 == 0


def test_decide_resolution_aspect_ratio_preservation():
    # 4:3 aspect ratio video (1440x1080)
    w, h = decide_resolution(
        source_width=1440,
        source_height=1080,
        fps=30.0,
        video_bitrate=800_000,
    )
    assert h in (720, 480, 360)
    assert w % 2 == 0
    # aspect ratio should be ~4:3 (1.333)
    assert abs((w / h) - (4 / 3)) < 0.05


def test_decide_resolution_lower_than_1080_source():
    # Source is already 720p (1280x720). It should never upscale even with huge bitrate.
    w, h = decide_resolution(
        source_width=1280,
        source_height=720,
        fps=30.0,
        video_bitrate=10_000_000,
    )
    assert (w, h) == (1280, 720)


def test_compute_audio_bitrate_standard():
    # 60s audio, 1 MB target (1,000,000 bytes), safety factor 0.92
    # Total bits = 1,000,000 * 8 * 0.92 = 7,360,000 bits
    # Bitrate = 7,360,000 / 60 = 122,666 bps (~122.6 kbps)
    bitrate = compute_audio_bitrate(
        duration=60.0,
        target_bytes=1_000_000,
        safety_factor=0.92,
    )
    assert bitrate == 122_666


def test_compute_audio_bitrate_floor():
    # 60s audio, 250 KB target = 250_000 bytes
    # Total bits = 250_000 * 8 * 0.92 = 1,840_000 bits
    # Bitrate = 1,840_000 / 60 = 30,666 bps (~30.6 kbps > 24 kbps floor)
    bitrate = compute_audio_bitrate(
        duration=60.0,
        target_bytes=250_000,
        safety_factor=0.92,
    )
    assert bitrate == 30_666
    assert bitrate >= 24_000


def test_compute_audio_bitrate_impossible_target():
    # 60s audio, 100 KB target = 100_000 bytes
    # Total bits = 100_000 * 8 * 0.92 = 736_000 bits
    # Bitrate = 736_000 / 60 = 12,266 bps (< 24 kbps floor)
    with pytest.raises(ValueError, match="cannot meet 24 kbps floor"):
        compute_audio_bitrate(
            duration=60.0,
            target_bytes=100_000,
            safety_factor=0.92,
        )


def test_compute_audio_bitrate_edge_cases():
    with pytest.raises(ValueError, match="duration must be positive"):
        compute_audio_bitrate(duration=0, target_bytes=100_000)

    with pytest.raises(ValueError, match="target_bytes must be positive"):
        compute_audio_bitrate(duration=10, target_bytes=0)


def test_probe_media_video_and_audio(tmp_path: Path):
    sample = tmp_path / "sample.mp4"
    sample.write_bytes(b"dummy video data")

    mock_ffprobe_output = json.dumps({
        "format": {
            "duration": "12.345",
        },
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30/1",
                "avg_frame_rate": "30/1",
                "duration": "12.345",
            },
            {
                "codec_type": "audio",
                "duration": "12.340",
            },
        ],
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = mock_ffprobe_output
        mock_run.return_value.stderr = ""

        info = probe_media(sample)

        assert isinstance(info, MediaInfo)
        assert info.duration == 12.345
        assert info.resolution == (1920, 1080)
        assert info.fps == 30.0
        assert info.has_audio is True
        assert info.has_video is True


def test_probe_media_audio_only(tmp_path: Path):
    sample = tmp_path / "voice.mp3"
    sample.write_bytes(b"dummy audio data")

    mock_ffprobe_output = json.dumps({
        "format": {
            "duration": "45.678",
        },
        "streams": [
            {
                "codec_type": "audio",
                "duration": "45.678",
            },
        ],
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = mock_ffprobe_output
        mock_run.return_value.stderr = ""

        info = probe_media(sample)

        assert info.duration == 45.678
        assert info.resolution is None
        assert info.fps is None
        assert info.has_audio is True
        assert info.has_video is False


def test_probe_media_fractional_fps(tmp_path: Path):
    sample = tmp_path / "clip.mp4"
    sample.write_bytes(b"dummy video data")

    mock_ffprobe_output = json.dumps({
        "format": {
            "duration": "5.0",
        },
        "streams": [
            {
                "codec_type": "video",
                "width": 1280,
                "height": 720,
                "avg_frame_rate": "30000/1001",
            },
        ],
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = mock_ffprobe_output
        mock_run.return_value.stderr = ""

        info = probe_media(sample)
        assert info.fps is not None
        assert round(info.fps, 2) == 29.97
        assert info.has_audio is False
        assert info.has_video is True


def test_probe_media_missing_file():
    with pytest.raises(FileNotFoundError):
        probe_media("non_existent_file.mp4")


def test_probe_media_invalid_output(tmp_path: Path):
    corrupt_file = tmp_path / "bad.mp4"
    corrupt_file.write_text("not a video")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "Invalid data found when processing input"

        with pytest.raises(RuntimeError, match="ffprobe failed"):
            probe_media(corrupt_file)


def test_probe_media_real_ffprobe(tmp_path: Path):
    import shutil

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg or ffprobe not installed")

    real_clip = tmp_path / "synthetic.mp4"
    # Generate a tiny 1-second synthetic video with audio
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=1:size=320x240:rate=25",
        "-f",
        "lavfi",
        "-i",
        "sine=duration=1:frequency=440",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(real_clip),
    ]
    subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )

    info = probe_media(real_clip)
    assert isinstance(info, MediaInfo)
    assert 0.9 <= info.duration <= 1.2
    assert info.resolution == (320, 240)
    assert info.fps == 25.0
    assert info.has_video is True
    assert info.has_audio is True
