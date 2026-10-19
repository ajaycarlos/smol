"""Media math and ffprobe utilities for video and audio compression.

Pure functions for bitrate calculation and resolution ladder step-down,
along with a secure ffprobe wrapper for metadata discovery.
Zero ffmpeg calls.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SAFETY_FACTOR = 0.92
DEFAULT_AUDIO_BITRATE = 64_000  # 64 kbps in bps
AUDIO_BITRATE_FLOOR = 24_000  # 24 kbps in bps
DEFAULT_MIN_BPP = 0.06  # Bits per pixel threshold for video step-down
RESOLUTION_LADDER = (1080, 720, 480, 360)


@dataclass(frozen=True)
class MediaInfo:
    """Media information discovered via ffprobe."""

    duration: float
    resolution: tuple[int, int] | None
    fps: float | None
    has_audio: bool
    has_video: bool


def compute_video_bitrate(
    duration: float,
    target_bytes: int,
    audio_bitrate: int = DEFAULT_AUDIO_BITRATE,
    safety_factor: float = DEFAULT_SAFETY_FACTOR,
) -> int:
    """Compute target video bitrate in bits per second (bps).

    Formula:
        Total bits = target_bytes * 8 * safety_factor
        Total bps = Total bits / duration
        Video bps = Total bps - audio_bitrate

    Args:
        duration: Duration in seconds (> 0).
        target_bytes: Target file size in bytes (> 0).
        audio_bitrate: Allocated audio bitrate in bps (default 64,000 bps).
        safety_factor: Safety factor margin (0 < safety_factor <= 1.0, default 0.92).

    Returns:
        Target video bitrate in bits per second (bps).

    Raises:
        ValueError: If parameters are invalid or target is impossible.
    """
    if duration <= 0:
        raise ValueError(f"duration must be positive, got {duration}")
    if target_bytes <= 0:
        raise ValueError(f"target_bytes must be positive, got {target_bytes}")
    if not (0 < safety_factor <= 1.0):
        raise ValueError(f"safety_factor must be in (0, 1.0], got {safety_factor}")
    if audio_bitrate < 0:
        raise ValueError(f"audio_bitrate cannot be negative, got {audio_bitrate}")

    total_bits = target_bytes * 8 * safety_factor
    total_bps = total_bits / duration
    video_bps = total_bps - audio_bitrate

    if video_bps <= 0:
        raise ValueError(
            f"Target {target_bytes} bytes is too small for {duration:.2f}s clip: "
            f"total available bandwidth {total_bps / 1000:.1f} kbps cannot accommodate "
            f"audio at {audio_bitrate / 1000:.1f} kbps plus video."
        )

    return int(video_bps)


def decide_resolution(
    source_width: int,
    source_height: int,
    fps: float,
    video_bitrate: int,
    min_bpp: float = DEFAULT_MIN_BPP,
) -> tuple[int, int]:
    """Decide resolution step-down (1080 -> 720 -> 480 -> 360) from bits-per-pixel.

    Formula:
        bpp = video_bitrate / (width * height * fps)
        If bpp < min_bpp, step down resolution ladder until bpp >= min_bpp
        or floor (360) is reached.
        Dimensions are always even numbers (required by h264/ffmpeg encoders).
        Never upscales above the source resolution.

    Args:
        source_width: Original video width in pixels.
        source_height: Original video height in pixels.
        fps: Frames per second (> 0).
        video_bitrate: Target video bitrate in bps (> 0).
        min_bpp: Minimum bits-per-pixel threshold (default 0.06).

    Returns:
        (width, height) tuple with even dimensions.
    """
    if source_width <= 0 or source_height <= 0:
        raise ValueError(
            f"Dimensions must be positive, got {source_width}x{source_height}"
        )
    if fps <= 0:
        raise ValueError(f"fps must be positive, got {fps}")
    if video_bitrate <= 0:
        raise ValueError(f"video_bitrate must be positive, got {video_bitrate}")

    aspect_ratio = source_width / source_height

    def make_even(val: float) -> int:
        n = round(val)
        return n if n % 2 == 0 else n + 1

    # Check source resolution first
    source_w = make_even(source_width)
    source_h = make_even(source_height)
    current_bpp = video_bitrate / (source_w * source_h * fps)

    if current_bpp >= min_bpp:
        return (source_w, source_h)

    # Filter ladder tiers: only consider tiers <= source_height (no upscaling)
    candidate_tiers = [h for h in RESOLUTION_LADDER if h < source_height]

    # If source_height is already <= 360, don't step down further
    if not candidate_tiers:
        return (source_w, source_h)

    # Step down the ladder
    for target_h in candidate_tiers:
        target_w = make_even(target_h * aspect_ratio)
        tier_bpp = video_bitrate / (target_w * target_h * fps)

        if tier_bpp >= min_bpp or target_h == candidate_tiers[-1]:
            return (target_w, target_h)

    floor_h = candidate_tiers[-1]
    return (make_even(floor_h * aspect_ratio), floor_h)


def compute_audio_bitrate(
    duration: float,
    target_bytes: int,
    safety_factor: float = DEFAULT_SAFETY_FACTOR,
) -> int:
    """Compute audio-only bitrate in bps with 24 kbps floor.

    Formula:
        Total bits = target_bytes * 8 * safety_factor
        Audio bps = Total bits / duration

    Args:
        duration: Audio duration in seconds (> 0).
        target_bytes: Target file size in bytes (> 0).
        safety_factor: Safety margin (default 0.92).

    Returns:
        Audio bitrate in bits per second (bps).

    Raises:
        ValueError: If target cannot meet 24 kbps floor or inputs are invalid.
    """
    if duration <= 0:
        raise ValueError(f"duration must be positive, got {duration}")
    if target_bytes <= 0:
        raise ValueError(f"target_bytes must be positive, got {target_bytes}")
    if not (0 < safety_factor <= 1.0):
        raise ValueError(f"safety_factor must be in (0, 1.0], got {safety_factor}")

    total_bits = target_bytes * 8 * safety_factor
    audio_bps = total_bits / duration

    if audio_bps < AUDIO_BITRATE_FLOOR:
        raise ValueError(
            f"Target {target_bytes} bytes for {duration:.2f}s audio produces "
            f"{audio_bps / 1000:.1f} kbps, which cannot meet 24 kbps floor."
        )

    return int(audio_bps)


def _parse_fps(stream: dict) -> float | None:
    """Parse frame rate from stream dictionary."""
    for key in ("avg_frame_rate", "r_frame_rate"):
        val = stream.get(key)
        if not val or val == "0/0":
            continue
        if "/" in val:
            try:
                num, den = val.split("/", 1)
                den_f = float(den)
                if den_f > 0:
                    fps = float(num) / den_f
                    if fps > 0:
                        return fps
            except (ValueError, ZeroDivisionError):
                continue
        else:
            try:
                fps = float(val)
                if fps > 0:
                    return fps
            except ValueError:
                continue
    return None


def probe_media(file_path: str | Path) -> MediaInfo:
    """Inspect media file using ffprobe.

    Calls ffprobe with subprocess list arguments (never shell strings).

    Args:
        file_path: Path to media file.

    Returns:
        MediaInfo containing duration, resolution, fps, and stream presence.

    Raises:
        FileNotFoundError: If the file does not exist.
        RuntimeError: If ffprobe fails or is not available.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Media file not found: {path}")

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=index,codec_type,width,height,r_frame_rate,avg_frame_rate,duration",
        "-of",
        "json",
        str(path),
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as err:
        raise RuntimeError(
            "ffprobe not found on system. Please install ffmpeg."
        ) from err

    if proc.returncode != 0:
        err_msg = proc.stderr.strip() or f"ffprobe exit code {proc.returncode}"
        raise RuntimeError(f"ffprobe failed for {path}: {err_msg}")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as err:
        raise RuntimeError(f"Failed to parse ffprobe JSON output for {path}") from err

    # Extract duration
    duration: float = 0.0
    format_info = data.get("format", {})
    if "duration" in format_info:
        try:
            duration = float(format_info["duration"])
        except (ValueError, TypeError):
            duration = 0.0

    streams = data.get("streams", [])
    has_audio = False
    has_video = False
    resolution: tuple[int, int] | None = None
    fps: float | None = None

    for s in streams:
        codec_type = s.get("codec_type")
        if codec_type == "video" and not has_video:
            has_video = True
            w = s.get("width")
            h = s.get("height")
            if isinstance(w, int) and isinstance(h, int):
                resolution = (w, h)
            stream_fps = _parse_fps(s)
            if stream_fps is not None:
                fps = stream_fps
            if duration <= 0 and "duration" in s:
                try:
                    duration = float(s["duration"])
                except (ValueError, TypeError):
                    pass
        elif codec_type == "audio":
            has_audio = True
            if duration <= 0 and "duration" in s:
                try:
                    duration = float(s["duration"])
                except (ValueError, TypeError):
                    pass

    return MediaInfo(
        duration=duration,
        resolution=resolution,
        fps=fps,
        has_audio=has_audio,
        has_video=has_video,
    )
