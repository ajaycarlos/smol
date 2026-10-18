from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from smol.core.paths import output_path
from smol.core.result import Result
from smol.core.size import format_size


def _encode_jpeg(img: Image.Image, quality: int) -> bytes:
    """Encode Pillow image as baseline JPEG with 4:2:0 subsampling and optimization."""
    buf = io.BytesIO()
    img.save(
        buf,
        format="JPEG",
        quality=quality,
        optimize=True,
        subsampling="4:2:0",
        progressive=False,
    )
    return buf.getvalue()


def shrink_image(
    src: str | Path,
    target_bytes: int,
    options: dict[str, Any] | None = None,
) -> Result:
    """Shrink an image to at most target_bytes.

    Pipeline (JPEG):
    1. Decode → apply EXIF rotation → strip metadata → convert to sRGB
    2. If already <= target: return ok with note, copy nothing
    3. Binary search quality between 60 and 95 (optimize=True, 4:2:0, baseline)
    4. If quality floor 60 exceeds target: return clean failure (no downscaling yet)
    5. Verify output by reopening
    6. Write atomically (temp file then rename)
    """
    src_path = Path(src)
    if not src_path.exists():
        return Result(ok=False, error=f"File not found: {src_path}")

    opts = options or {}
    quality_floor = int(opts.get("quality_floor", 60))
    quality_max = int(opts.get("quality_max", 95))

    original_bytes = src_path.stat().st_size

    # Check if already small enough
    if original_bytes <= target_bytes:
        try:
            with Image.open(src_path) as im:
                w, h = im.size
        except (OSError, ValueError):
            w, h = None, None
        return Result(
            ok=True,
            output_path=None,
            original_bytes=original_bytes,
            final_bytes=original_bytes,
            width=w,
            height=h,
            warning=(
                "File is already smaller than or equal to target size; "
                "no compression needed."
            ),
        )

    # Decode and prepare image
    try:
        with Image.open(src_path) as raw_img:
            # Apply EXIF rotation
            img = ImageOps.exif_transpose(raw_img)
            if img is None:
                img = raw_img.copy()

            # Strip metadata & convert to sRGB
            # Flatten alpha onto white if transparent
            has_alpha = img.mode in ("RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info
            )
            if has_alpha:
                rgba = img.convert("RGBA")
                white_bg = Image.new("RGB", rgba.size, (255, 255, 255))
                white_bg.paste(rgba, mask=rgba.split()[3])
                img = white_bg
            elif img.mode != "RGB":
                img = img.convert("RGB")
            else:
                img = img.copy()

            img.info = {}
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        return Result(
            ok=False,
            original_bytes=original_bytes,
            error=f"Failed to open or decode image: {exc}",
        )

    width, height = img.size
    steps = 0
    cache: dict[int, bytes] = {}

    def get_jpeg(q: int) -> bytes:
        nonlocal steps
        if q not in cache:
            steps += 1
            cache[q] = _encode_jpeg(img, q)
        return cache[q]

    # Evaluate quality floor
    floor_bytes = get_jpeg(quality_floor)
    if len(floor_bytes) > target_bytes:
        floor_len = len(floor_bytes)
        return Result(
            ok=False,
            output_path=None,
            original_bytes=original_bytes,
            final_bytes=0,
            width=width,
            height=height,
            quality=None,
            steps=steps,
            error=(
                f"Cannot fit target ({format_size(target_bytes)}) without "
                f"downscaling. Smallest size at quality floor {quality_floor} "
                f"is {format_size(floor_len)} ({floor_len:,} bytes)."
            ),
        )

    # Evaluate maximum quality
    max_bytes = get_jpeg(quality_max)
    if len(max_bytes) <= target_bytes:
        best_q = quality_max
        best_data = max_bytes
    else:
        # Binary search in [quality_floor, quality_max - 1]
        low = quality_floor
        high = quality_max - 1
        best_q = quality_floor
        best_data = floor_bytes

        while low <= high:
            mid = (low + high) // 2
            mid_data = get_jpeg(mid)
            if len(mid_data) <= target_bytes:
                best_q = mid
                best_data = mid_data
                low = mid + 1  # Seek higher quality that still fits
            else:
                high = mid - 1

    # Verify output by reopening
    try:
        with Image.open(io.BytesIO(best_data)) as check_im:
            check_im.verify()
        with Image.open(io.BytesIO(best_data)) as check_im:
            if check_im.size != (width, height) or check_im.format != "JPEG":
                return Result(
                    ok=False,
                    original_bytes=original_bytes,
                    error=(
                        "Verification failed: reopened image format or "
                        "dimensions mismatch."
                    ),
                )
    except (OSError, ValueError) as exc:
        return Result(
            ok=False,
            original_bytes=original_bytes,
            error=f"Verification failed on reopening: {exc}",
        )

    # Determine destination path and write atomically
    dest_path = output_path(src_path, target_bytes)
    parent_dir = dest_path.parent
    parent_dir.mkdir(parents=True, exist_ok=True)

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=parent_dir,
            prefix=f".{dest_path.stem}_",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(best_data)
            temp_file.flush()
            os.fsync(temp_file.fileno())

        temp_path.replace(dest_path)
    except OSError as exc:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
        return Result(
            ok=False,
            original_bytes=original_bytes,
            error=f"Failed to write output atomically: {exc}",
        )

    final_bytes = dest_path.stat().st_size
    return Result(
        ok=True,
        output_path=dest_path,
        original_bytes=original_bytes,
        final_bytes=final_bytes,
        width=width,
        height=height,
        quality=best_q,
        steps=steps,
    )
