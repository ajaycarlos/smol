"""Audio shrinking engine matching codec families with bitrate computation.

Implements PLAN.md section 7.3:
- Read duration with ffprobe via probe_media.
- Match codec to input family:
    * MP3 (.mp3) -> libmp3lame
    * AAC / M4A (.m4a, .aac) -> aac
    * Opus / OGG (.opus, .ogg) -> libopus
    * Lossless (.wav, .flac) -> libmp3lame fallback (.mp3)
- Compute bitrate from target with 0.92 safety margin.
- Enforce 24 kbps floor, else fail honestly stating smallest achievable size.
- Post-write size verification (output <= target_bytes).
- Retry ladder: cut bitrate 5% on overshoot (up to 3 retries).
- Atomic destination file write with non-overwriting collision resolution.
- Source audio file is never modified.
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from smol.config import load_config
from smol.core.media_math import (
    AUDIO_BITRATE_FLOOR,
    DEFAULT_SAFETY_FACTOR,
    compute_audio_bitrate,
    probe_media,
)
from smol.core.paths import output_path
from smol.core.result import CancellationError, Result
from smol.core.size import format_size, parse_size
from smol.core.video import _stream_ffmpeg

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BITRATE_CUT = 0.95

# Mapping from input extensions to (ffmpeg_codec, output_extension)
AUDIO_FAMILY_MAP: dict[str, tuple[str, str]] = {
    ".mp3": ("libmp3lame", ".mp3"),
    ".m4a": ("aac", ".m4a"),
    ".aac": ("aac", ".aac"),
    ".opus": ("libopus", ".opus"),
    ".ogg": ("libopus", ".ogg"),
    ".wav": ("libmp3lame", ".mp3"),
    ".flac": ("libmp3lame", ".mp3"),
}


def _resolve_codec_and_ext(src_path: Path) -> tuple[str, str]:
    """Resolve the ffmpeg audio encoder and target extension from input file."""
    ext = src_path.suffix.lower()
    if ext in AUDIO_FAMILY_MAP:
        return AUDIO_FAMILY_MAP[ext]
    # Default fallback to MP3
    return ("libmp3lame", ".mp3")


def shrink_audio(
    src: str | Path,
    target_bytes: float | str,
    options: dict[str, Any] | None = None,
) -> Result:
    """Shrink an audio file to at most target_bytes.

    Args:
        src: Path to the input audio file.
        target_bytes: Maximum allowed byte size (int, float, or string e.g. '100KB').
        options: Optional dict configuring compression behavior:
            - dry_run (bool): If True, predict final size without writing file.
            - strip_metadata (bool): If True (default), strip tags/metadata.
            - out_dir (Path | str): Destination directory.
            - step_callback (Callable): Progress callback (fraction, bytes).

    Returns:
        Result object with ok, output_path, sizes, steps, warning/error.
    """
    src_path = Path(src)
    if not src_path.is_file():
        return Result(ok=False, error=f"Audio file not found: {src_path}")

    opts = options or {}
    config = load_config()

    # Parse target bytes
    if isinstance(target_bytes, str):
        try:
            target_bytes = parse_size(target_bytes)
        except ValueError as exc:
            return Result(ok=False, error=str(exc))
    else:
        target_bytes = int(target_bytes)

    if target_bytes <= 0:
        return Result(
            ok=False,
            error=f"target_bytes must be positive, got {target_bytes}",
        )

    orig_bytes = src_path.stat().st_size

    # Fast bypass: file is already <= target
    if orig_bytes <= target_bytes:
        return Result(
            ok=True,
            output_path=src_path,
            original_bytes=orig_bytes,
            final_bytes=orig_bytes,
            warning=(
                f"File is already small enough "
                f"({format_size(orig_bytes)} <= {format_size(target_bytes)})."
            ),
        )

    # Check ffmpeg availability
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            error="ffmpeg not found on system. Please install ffmpeg.",
        )

    # Probe media duration and streams
    try:
        media_info = probe_media(src_path)
    except (RuntimeError, OSError, ValueError) as exc:
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            error=f"ffprobe inspection failed: {exc}",
        )

    if not media_info.has_audio or media_info.duration <= 0:
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            error=(
                f"No audio stream found or zero duration in {src_path.name} "
                f"(duration: {media_info.duration:.2f}s)."
            ),
        )

    duration = media_info.duration
    safety_factor = float(opts.get("safety_factor", DEFAULT_SAFETY_FACTOR))

    # Compute target audio bitrate
    try:
        bitrate_bps = compute_audio_bitrate(
            duration=duration,
            target_bytes=target_bytes,
            safety_factor=safety_factor,
        )
    except ValueError as exc:
        # Honest failure: target produces bitrate below 24 kbps floor
        min_bytes = int(AUDIO_BITRATE_FLOOR * duration / (8 * safety_factor))
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            error=(
                f"{exc} Smallest achievable size at 24 kbps floor is "
                f"~{format_size(min_bytes)}. Try a larger target."
            ),
        )

    # Dry-run prediction mode
    if opts.get("dry_run", False):
        predicted_bytes = min(orig_bytes, int(duration * bitrate_bps / 8))
        return Result(
            ok=True,
            output_path=None,
            original_bytes=orig_bytes,
            final_bytes=predicted_bytes,
            quality=bitrate_bps // 1000,
            steps=1,
        )

    # Codec and extension resolution
    codec, target_ext = _resolve_codec_and_ext(src_path)

    # Output path setup
    out_dir = opts.get("out_dir")
    try:
        dest_path = output_path(
            src_path,
            target_bytes,
            out_dir=out_dir,
            ext=target_ext,
        )
    except (RuntimeError, OSError, ValueError) as exc:
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            error=f"Failed to generate output path: {exc}",
        )

    temp_out_path = dest_path.with_name(f".tmp_{os.getpid()}_{dest_path.name}")

    strip_meta = opts.get(
        "strip_metadata",
        config.strip_metadata if config else True,
    )
    step_callback: Callable[[float, int], None] | None = opts.get("step_callback")
    cancel_check = opts.get("cancel_check")
    on_process_started = opts.get("on_process_started")

    attempt = 0
    current_bitrate = bitrate_bps
    smallest_achieved: int | None = None

    try:
        while attempt <= MAX_RETRIES:
            attempt += 1
            if temp_out_path.exists():
                temp_out_path.unlink()

            cmd = [
                ffmpeg_bin,
                "-y",
                "-i",
                str(src_path),
                "-vn",
                "-c:a",
                codec,
                "-b:a",
                str(current_bitrate),
            ]

            if codec == "libopus":
                cmd.extend(["-vbr", "constrained"])

            if strip_meta:
                cmd.extend(["-map_metadata", "-1"])
            else:
                cmd.extend(["-map_metadata", "0"])

            cmd.append(str(temp_out_path))

            _stream_ffmpeg(
                cmd=cmd,
                duration=duration,
                orig_bytes=orig_bytes,
                target_bytes=target_bytes,
                pass_index=1,
                total_passes=1,
                step_callback=step_callback,
                cancel_check=cancel_check,
                on_process_started=on_process_started,
            )

            if not temp_out_path.exists():
                raise RuntimeError(
                    "ffmpeg finished but temporary output was not created."
                )

            out_bytes = temp_out_path.stat().st_size
            if smallest_achieved is None or out_bytes < smallest_achieved:
                smallest_achieved = out_bytes

            # Check if output is <= target
            if out_bytes <= target_bytes:
                # Atomic destination replace
                temp_out_path.replace(dest_path)
                final_bytes = dest_path.stat().st_size

                # Post-write guarantee: verify disk file size
                if final_bytes > target_bytes:
                    dest_path.unlink(missing_ok=True)
                    return Result(
                        ok=False,
                        original_bytes=orig_bytes,
                        final_bytes=final_bytes,
                        steps=attempt,
                        error=(
                            f"Post-write check failed: {final_bytes} bytes "
                            f"exceeded target {target_bytes} bytes."
                        ),
                    )

                if step_callback:
                    step_callback(1.0, final_bytes)

                return Result(
                    ok=True,
                    output_path=dest_path,
                    original_bytes=orig_bytes,
                    final_bytes=final_bytes,
                    quality=current_bitrate // 1000,
                    steps=attempt,
                )

            # Overshot target: cut bitrate 5% and retry
            logger.info(
                "Audio output (%d bytes) exceeded target (%d bytes). "
                "Retrying attempt %d/%d with 5%% bitrate reduction.",
                out_bytes,
                target_bytes,
                attempt,
                MAX_RETRIES,
            )
            current_bitrate = int(current_bitrate * RETRY_BITRATE_CUT)
            if current_bitrate < AUDIO_BITRATE_FLOOR:
                break

        # Exhausted retries
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            final_bytes=smallest_achieved or 0,
            steps=attempt,
            error=(
                f"Target {format_size(target_bytes)} unreachable: smallest size "
                f"achieved was {format_size(smallest_achieved or 0)}. "
                "Try a larger target."
            ),
        )

    except CancellationError:
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            steps=attempt,
            error="Audio compression cancelled",
        )
    except (RuntimeError, OSError, ValueError) as exc:
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            steps=attempt,
            error=f"Audio compression failed: {exc}",
        )

    finally:
        if temp_out_path.exists():
            try:
                temp_out_path.unlink()
            except OSError:
                pass
