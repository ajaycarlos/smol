"""Video shrinking engine using two-pass x264 via ffmpeg.

Implements PLAN.md section 7.3:
- Read duration, resolution, fps with ffprobe.
- Total bits = target * 8 * 0.92 (safety margin). Audio 64 kbps (if present).
  Video bitrate = remainder.
- If bits-per-pixel is too low, step resolution down (1080 -> 720 -> 480 -> 360).
- Two-pass x264 with subprocess list arguments (never shell strings).
- Verify output size <= target.
- If output is over target: cut bitrate 5% and retry (max 3 retries).
- Pass-log temporary files are always cleaned up, even on failure or cancel.
- Atomic destination file write with non-overwriting collision resolution.
- Honest failure when impossible.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from smol.config import load_config
from smol.core.media_math import (
    DEFAULT_AUDIO_BITRATE,
    DEFAULT_SAFETY_FACTOR,
    decide_resolution,
    probe_media,
)
from smol.core.paths import output_path
from smol.core.result import CancellationError, Result
from smol.core.size import format_size, parse_size

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BITRATE_CUT = 0.95  # 5% cut per retry


def _parse_time_to_seconds(time_str: str) -> float | None:
    """Parse HH:MM:SS.micro or seconds into float."""
    try:
        parts = time_str.split(":")
        if len(parts) == 3:
            return float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2])
        elif len(parts) == 2:
            return float(parts[0]) * 60.0 + float(parts[1])
        return float(time_str)
    except (ValueError, TypeError):
        return None


def _stream_ffmpeg(
    cmd: list[str],
    duration: float,
    orig_bytes: int,
    target_bytes: int,
    pass_index: int,
    total_passes: int,
    step_callback: Callable[[float, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_process_started: Callable[[subprocess.Popen | None], None] | None = None,
) -> None:
    """Execute ffmpeg command, parsing -progress pipe:1 into progress events."""
    full_cmd = list(cmd)
    if "-progress" not in full_cmd:
        full_cmd.extend(["-progress", "pipe:1", "-nostats"])

    proc = subprocess.Popen(
        full_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    if on_process_started:
        on_process_started(proc)

    current_out_s = 0.0
    try:
        if proc.stdout:
            for line in proc.stdout:
                if cancel_check and cancel_check():
                    if proc.poll() is None:
                        try:
                            proc.kill()
                        except OSError:
                            pass
                    break

                line = line.strip()
                if not line or "=" not in line:
                    continue

                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()

                if k == "out_time_us":
                    try:
                        current_out_s = max(0.0, float(v) / 1_000_000.0)
                    except ValueError:
                        pass
                elif k == "out_time" and current_out_s == 0.0 and v != "N/A":
                    parsed = _parse_time_to_seconds(v)
                    if parsed is not None:
                        current_out_s = max(0.0, parsed)
                elif k == "progress" and step_callback:
                    if v == "end":
                        pass_frac = 1.0
                    elif duration > 0:
                        pass_frac = min(1.0, max(0.0, current_out_s / duration))
                    else:
                        pass_frac = 0.0

                    if total_passes == 2:
                        if pass_index == 1:
                            overall_p = 0.5 * pass_frac
                        else:
                            overall_p = 0.5 + 0.5 * pass_frac
                    else:
                        overall_p = pass_frac

                    diff = orig_bytes - target_bytes
                    if diff > 0:
                        cand_bytes = int(orig_bytes - diff * overall_p)
                    else:
                        cand_bytes = target_bytes
                    cand_bytes = max(1, cand_bytes)

                    step_callback(overall_p, cand_bytes)


        stderr_out = proc.stderr.read() if proc.stderr else ""
        proc.wait()

        if cancel_check and cancel_check():
            raise CancellationError("Video compression cancelled")

        if proc.returncode in (-9, -15):
            raise CancellationError("Video compression cancelled (killed)")

        if proc.returncode != 0:
            err = stderr_out.strip() or f"exit code {proc.returncode}"
            raise RuntimeError(f"ffmpeg failed: {err}")

    finally:
        if on_process_started:
            on_process_started(None)
        if proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
            proc.wait()


def _run_ffmpeg_two_pass(
    src_path: Path,
    temp_out_path: Path,
    video_bitrate: int,
    audio_bitrate: int | None,
    target_res: tuple[int, int] | None,
    source_res: tuple[int, int] | None,
    duration: float = 0.0,
    orig_bytes: int = 0,
    target_bytes: int = 0,
    step_callback: Callable[[float, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_process_started: Callable[[subprocess.Popen | None], None] | None = None,
) -> None:
    """Execute two-pass ffmpeg encoding with strict pass-log cleanup.

    Uses list arguments exclusively (never shell strings).
    Pass logs are written to an isolated temporary directory and deleted
    in a finally block.
    """
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise RuntimeError("ffmpeg not found on system. Please install ffmpeg.")

    # Isolated temporary directory for pass logs
    pass_log_dir = tempfile.mkdtemp(prefix="smol_passlog_")
    pass_log_prefix = str(Path(pass_log_dir) / "ffmpeg2pass")

    try:
        # Build scale filter if resolution differs
        vf_args: list[str] = []
        if target_res and source_res and target_res != source_res:
            vf_args = ["-vf", f"scale={target_res[0]}:{target_res[1]}"]

        # Initial progress emit
        if step_callback and orig_bytes > 0:
            step_callback(0.01, orig_bytes)

        # -----------------
        # PASS 1
        # -----------------
        pass1_cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(src_path),
            "-c:v",
            "libx264",
            "-b:v",
            str(video_bitrate),
            "-pass",
            "1",
            "-passlogfile",
            pass_log_prefix,
            "-preset",
            "fast",
            *vf_args,
            "-an",
            "-f",
            "null",
            "/dev/null",
        ]

        _stream_ffmpeg(
            cmd=pass1_cmd,
            duration=duration,
            orig_bytes=orig_bytes,
            target_bytes=target_bytes,
            pass_index=1,
            total_passes=2,
            step_callback=step_callback,
            cancel_check=cancel_check,
            on_process_started=on_process_started,
        )

        # -----------------
        # PASS 2
        # -----------------
        pass2_cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(src_path),
            "-c:v",
            "libx264",
            "-b:v",
            str(video_bitrate),
            "-pass",
            "2",
            "-passlogfile",
            pass_log_prefix,
            "-preset",
            "fast",
            *vf_args,
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
        ]

        if audio_bitrate and audio_bitrate > 0:
            pass2_cmd.extend(["-c:a", "aac", "-b:a", str(audio_bitrate)])
        else:
            pass2_cmd.append("-an")

        pass2_cmd.append(str(temp_out_path))

        _stream_ffmpeg(
            cmd=pass2_cmd,
            duration=duration,
            orig_bytes=orig_bytes,
            target_bytes=target_bytes,
            pass_index=2,
            total_passes=2,
            step_callback=step_callback,
            cancel_check=cancel_check,
            on_process_started=on_process_started,
        )

    finally:
        # Guarantee 100% cleanup of pass-log files and temporary directory
        shutil.rmtree(pass_log_dir, ignore_errors=True)



def shrink_video(
    src: str | Path,
    target_bytes: int,
    options: dict[str, Any] | None = None,
) -> Result:
    """Shrink a video file to at most target_bytes.

    Pipeline:
    1. Check tools (ffmpeg, ffprobe) and source validity.
    2. Check if already <= target_bytes (no-op unless force_reencode).
    3. Probe duration, resolution, fps, and stream presence with ffprobe.
    4. Compute target video bitrate with 0.92 safety factor.
    5. Decide resolution stepdown via bits-per-pixel ladder.
    6. Execute two-pass x264 encoding with isolated pass logs.
    7. Verify output size <= target. If over target, cut bitrate 5%
       and retry (max 3 retries).
    8. Atomically write to destination and clean up all temporary files.

    Args:
        src: Path to source video file.
        target_bytes: Maximum allowed output file size in bytes.
        options: Optional settings dictionary:
            - out_dir: Destination directory override.
            - safety_factor: Safety factor margin (default 0.92).
            - force_reencode: Re-encode even if source is <= target_bytes.
            - step_callback: Callable[[float, int], None] emitting progress.

    Returns:
        Result dataclass representing success or honest failure.
    """
    src_path = Path(src)
    if not src_path.exists():
        return Result(ok=False, error=f"File not found: {src_path}")

    orig_bytes = src_path.stat().st_size
    if orig_bytes == 0:
        return Result(ok=False, original_bytes=0, error="File is empty (0 bytes).")

    # Normalize target_bytes
    if isinstance(target_bytes, str):
        target_bytes = parse_size(target_bytes)
    else:
        target_bytes = int(target_bytes)

    # Load configuration
    cfg = load_config()
    opts = options or {}
    force_reencode = opts.get("force_reencode", False)
    safety_factor = float(opts.get("safety_factor", DEFAULT_SAFETY_FACTOR))
    step_callback: Callable[[float, int], None] | None = opts.get("step_callback")

    # Destination directory
    out_dir_opt = opts.get("out_dir")
    if out_dir_opt:
        dest_dir = Path(out_dir_opt)
    elif cfg.output_mode == "fixed" and cfg.output_folder:
        dest_dir = Path(cfg.output_folder)
    else:
        dest_dir = src_path.parent

    # Check external tools
    if not shutil.which("ffmpeg"):
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            error=(
                "ffmpeg is required to shrink video files. "
                "Install it with: sudo apt install ffmpeg"
            ),
        )
    if not shutil.which("ffprobe"):
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            error=(
                "ffprobe is required to shrink video files. "
                "Install it with: sudo apt install ffmpeg"
            ),
        )

    # 1. Already <= target_bytes bypass
    if not force_reencode and orig_bytes <= target_bytes:
        return Result(
            ok=True,
            output_path=src_path,
            original_bytes=orig_bytes,
            final_bytes=orig_bytes,
            warning=(
                f"File is already small enough ({format_size(orig_bytes)} <= "
                f"target {format_size(target_bytes)}); kept original."
            ),
        )

    # 2. Probe media info
    try:
        media_info = probe_media(src_path)
    except (RuntimeError, OSError, ValueError) as exc:
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            error=f"Failed to inspect video with ffprobe: {exc}",
        )

    if not media_info.has_video:
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            error=f"No video stream found in {src_path.name}",
        )

    if media_info.duration <= 0:
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            error=f"Could not determine video duration for {src_path.name}",
        )

    # 3. Bandwidth check & bitrate allocation
    # Only reject pre-emptively if total bandwidth is below
    # minimum viable threshold (50 kbps)
    MIN_TOTAL_BPS = 50_000
    total_avail_bps = (target_bytes * 8 * safety_factor) / media_info.duration
    if total_avail_bps < MIN_TOTAL_BPS:
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            error=(
                f"Target {format_size(target_bytes)} is too small for "
                f"{media_info.duration:.1f}s video: available bandwidth "
                f"({total_avail_bps / 1000:.1f} kbps) is below minimum "
                "viable threshold (50 kbps)."
            ),
        )

    # Allocate audio and video bitrates without pre-emptive rejection
    audio_bitrate: int | None = None
    if media_info.has_audio:
        if total_avail_bps >= 128_000:
            audio_bitrate = DEFAULT_AUDIO_BITRATE  # 64 kbps
        else:
            # Scale audio down on tight budgets so video has room
            audio_bitrate = max(24_000, int(total_avail_bps * 0.25))
        video_bitrate = max(16_000, int(total_avail_bps - audio_bitrate))
    else:
        video_bitrate = max(16_000, int(total_avail_bps))

    # 4. Decide resolution
    source_res = media_info.resolution
    fps = media_info.fps or 25.0
    target_res = source_res
    if source_res:
        target_res = decide_resolution(
            source_width=source_res[0],
            source_height=source_res[1],
            fps=fps,
            video_bitrate=video_bitrate,
        )

    # Dry-run prediction for UI hover
    dry_run = bool(opts.get("dry_run", False))
    if dry_run:
        predicted_bytes = min(orig_bytes, int(target_bytes * safety_factor))
        return Result(
            ok=True,
            output_path=None,
            original_bytes=orig_bytes,
            final_bytes=predicted_bytes,
            width=target_res[0] if target_res else None,
            height=target_res[1] if target_res else None,
            steps=0,
        )

    # 5. Prepare destination and atomic temp file
    dest_path = output_path(src_path, target_bytes, out_dir=dest_dir, ext=".mp4")
    temp_out_path = dest_path.with_suffix(f".tmp.{os.getpid()}.mp4")

    # 6. Two-pass encoding with retry ladder on overshoot (max 3 retries, -5%)
    current_video_bitrate = video_bitrate
    attempt = 0
    smallest_achieved: int | None = None
    cancel_check = opts.get("cancel_check")
    on_process_started = opts.get("on_process_started")

    try:
        while attempt <= MAX_RETRIES:
            attempt += 1
            if temp_out_path.exists():
                temp_out_path.unlink()

            _run_ffmpeg_two_pass(
                src_path=src_path,
                temp_out_path=temp_out_path,
                video_bitrate=current_video_bitrate,
                audio_bitrate=audio_bitrate,
                target_res=target_res,
                source_res=source_res,
                duration=media_info.duration,
                orig_bytes=orig_bytes,
                target_bytes=target_bytes,
                step_callback=step_callback,
                cancel_check=cancel_check,
                on_process_started=on_process_started,
            )

            if not temp_out_path.exists():
                raise RuntimeError("ffmpeg completed but output file was not created.")

            out_bytes = temp_out_path.stat().st_size
            if smallest_achieved is None or out_bytes < smallest_achieved:
                smallest_achieved = out_bytes

            # Check if output is <= target
            if out_bytes <= target_bytes:
                # Success! Atomic replace
                temp_out_path.replace(dest_path)
                final_bytes = dest_path.stat().st_size

                final_w = target_res[0] if target_res else None
                final_h = target_res[1] if target_res else None

                return Result(
                    ok=True,
                    output_path=dest_path,
                    original_bytes=orig_bytes,
                    final_bytes=final_bytes,
                    width=final_w,
                    height=final_h,
                    steps=attempt * 2,
                )

            # Overshot target: cut bitrate 5% and retry
            logger.info(
                "Video output (%d bytes) exceeded target (%d bytes). "
                "Retrying attempt %d/%d with 5%% bitrate reduction.",
                out_bytes,
                target_bytes,
                attempt,
                MAX_RETRIES,
            )
            current_video_bitrate = int(current_video_bitrate * RETRY_BITRATE_CUT)

        # Exhausted retries without fitting target
        if temp_out_path.exists():
            temp_out_path.unlink()

        return Result(
            ok=False,
            original_bytes=orig_bytes,
            final_bytes=smallest_achieved or 0,
            steps=attempt * 2,
            error=(
                f"Target {format_size(target_bytes)} unreachable: smallest size "
                f"achieved was {format_size(smallest_achieved or 0)}. "
                "Try a larger target."
            ),
        )

    except CancellationError:
        if temp_out_path.exists():
            temp_out_path.unlink(missing_ok=True)
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            error="Video compression cancelled",
        )
    except (RuntimeError, OSError, ValueError) as exc:
        if temp_out_path.exists():
            temp_out_path.unlink(missing_ok=True)
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            error=f"Video compression failed: {exc}",
        )

