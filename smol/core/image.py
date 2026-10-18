from __future__ import annotations

import io
import math
import os
import tempfile
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image, ImageCms, ImageOps, UnidentifiedImageError

from smol.core.paths import output_path
from smol.core.result import Result
from smol.core.size import format_size


def _encode_jpeg(
    img: Image.Image,
    quality: int,
    exif: bytes | Image.Exif | None = None,
) -> bytes:
    """Encode Pillow image as baseline JPEG with 4:2:0 subsampling and optimization."""
    buf = io.BytesIO()
    kwargs: dict[str, Any] = {
        "format": "JPEG",
        "quality": quality,
        "optimize": True,
        "subsampling": "4:2:0",
        "progressive": False,
    }
    if exif:
        kwargs["exif"] = exif
    img.save(buf, **kwargs)
    return buf.getvalue()


def shrink_image(
    src: str | Path,
    target_bytes: int,
    options: dict[str, Any] | None = None,
) -> Result:
    """Shrink an image to at most target_bytes.

    Pipeline (JPEG):
    1. Decode → apply EXIF rotation → strip metadata → convert to sRGB
    2. If already <= target: return ok with note, copy nothing (unless force_reencode)
    4. If quality floor 60 exceeds target: estimate scale = sqrt(target / floor) * 0.98,
       resize with Lanczos, search quality 60-90, repeat with 0.9 steps down to min
       short-side (default 200 px).
    5. If still too large at min dimension: fail honestly stating smallest size.
    6. Verify output by reopening
    7. Write atomically (temp file then rename)
    """
    src_path = Path(src)
    if not src_path.exists():
        return Result(ok=False, error=f"File not found: {src_path}")

    opts = options or {}
    quality_floor = int(opts.get("quality_floor", 60))
    quality_max = int(opts.get("quality_max", 95))
    min_dim = int(opts.get("min_dim", 200))
    strip_metadata = bool(opts.get("strip_metadata", True))
    force_reencode = bool(
        opts.get("force_reencode", False) or opts.get("force", False)
    )
    max_pixels = int(
        opts.get(
            "max_pixels",
            getattr(Image, "MAX_IMAGE_PIXELS", 89_478_485) or 89_478_485,
        )
    )

    original_bytes = src_path.stat().st_size

    # Check if already small enough
    if not force_reencode and original_bytes <= target_bytes:
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
            scale=1.0,
            warning=(
                "File is already smaller than or equal to target size; "
                "no compression needed."
            ),
        )

    # Decode and prepare image
    output_exif: Image.Exif | None = None
    old_max_pixels = Image.MAX_IMAGE_PIXELS
    try:
        Image.MAX_IMAGE_PIXELS = max_pixels
        with Image.open(src_path) as raw_img:
            # Guard against decompression bomb by pixel count
            total_pixels = raw_img.width * raw_img.height
            if total_pixels > max_pixels:
                return Result(
                    ok=False,
                    original_bytes=original_bytes,
                    error=(
                        f"Image dimensions ({raw_img.width}x{raw_img.height} = "
                        f"{total_pixels:,} pixels) exceed safety limit of "
                        f"{max_pixels:,} pixels (decompression bomb protection)."
                    ),
                )

            # Metadata handling: preserve if strip_metadata is False
            if not strip_metadata:
                raw_exif = raw_img.getexif()
                if raw_exif:
                    if ExifTags.Base.Orientation in raw_exif:
                        raw_exif[ExifTags.Base.Orientation] = 1
                    try:
                        output_exif = raw_exif.tobytes()
                    except (OSError, ValueError, TypeError):
                        output_exif = None

            # Apply EXIF rotation (bakes rotation into pixels)
            img = ImageOps.exif_transpose(raw_img)
            if img is None:
                img = raw_img.copy()

            # Convert ICC profile to sRGB
            icc_profile = raw_img.info.get("icc_profile")
            if icc_profile:
                try:
                    in_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc_profile))
                    srgb_profile = ImageCms.createProfile("sRGB")
                    target_mode = "RGBA" if img.mode in ("RGBA", "LA") else "RGB"
                    img = ImageCms.profileToProfile(
                        img, in_profile, srgb_profile, outputMode=target_mode
                    )
                except (ImageCms.PyCMSError, OSError, ValueError):
                    pass

            # Flatten alpha onto white if transparent, convert to sRGB
            has_alpha = img.mode in ("RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info
            )
            if has_alpha:
                rgba = img.convert("RGBA")
                white_bg = Image.new("RGB", rgba.size, (255, 255, 255))
                white_bg.paste(rgba, mask=rgba.split()[3])
                img = white_bg
            elif img.mode != "RGB":
                # Convert CMYK, grayscale (L, 1), and other modes to RGB (sRGB)
                img = img.convert("RGB")
            else:
                img = img.copy()

            img.info = {}
    except Image.DecompressionBombError as exc:
        return Result(
            ok=False,
            original_bytes=original_bytes,
            error=f"Decompression bomb protection triggered: {exc}",
        )
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        return Result(
            ok=False,
            original_bytes=original_bytes,
            error=f"Failed to open or decode image: {exc}",
        )
    finally:
        Image.MAX_IMAGE_PIXELS = old_max_pixels

    width, height = img.size
    steps = 0

    def encode_jpeg(im: Image.Image, q: int) -> bytes:
        nonlocal steps
        steps += 1
        return _encode_jpeg(im, q, exif=output_exif)

    resampling = getattr(Image, "Resampling", Image).LANCZOS

    # Evaluate quality floor at full resolution
    floor_bytes = encode_jpeg(img, quality_floor)

    if len(floor_bytes) <= target_bytes:
        # Full resolution fits within target; search quality in [floor, max]
        max_bytes = encode_jpeg(img, quality_max)
        if len(max_bytes) <= target_bytes:
            best_q = quality_max
            best_data = max_bytes
        else:
            low = quality_floor
            high = quality_max - 1
            best_q = quality_floor
            best_data = floor_bytes

            while low <= high:
                mid = (low + high) // 2
                mid_data = encode_jpeg(img, mid)
                if len(mid_data) <= target_bytes:
                    best_q = mid
                    best_data = mid_data
                    low = mid + 1
                else:
                    high = mid - 1

        best_scale = 1.0
        final_w = width
        final_h = height
    else:
        # Full-size quality floor exceeds target: enter downscaling loop
        orig_w, orig_h = width, height
        orig_short = min(orig_w, orig_h)
        min_dim_eff = min(orig_short, min_dim)

        current_scale = math.sqrt(target_bytes / len(floor_bytes)) * 0.98

        while True:
            target_short = orig_short * current_scale
            if target_short <= min_dim_eff or orig_short <= min_dim_eff:
                # Clamp to minimum short-side dimension floor
                effective_scale = min_dim_eff / orig_short
                if orig_w <= orig_h:
                    cur_w = min_dim_eff
                    cur_h = max(min_dim_eff, round(orig_h * effective_scale))
                else:
                    cur_h = min_dim_eff
                    cur_w = max(min_dim_eff, round(orig_w * effective_scale))
                is_floor = True
            else:
                cur_w = max(min_dim_eff, round(orig_w * current_scale))
                cur_h = max(min_dim_eff, round(orig_h * current_scale))
                effective_scale = cur_w / orig_w
                is_floor = (min(cur_w, cur_h) <= min_dim_eff)

            resized_img = img.resize((cur_w, cur_h), resampling)
            floor_data = encode_jpeg(resized_img, quality_floor)

            if len(floor_data) > target_bytes:
                if is_floor:
                    # Reached minimum dimension floor and still cannot fit
                    smallest_sz = format_size(len(floor_data))
                    return Result(
                        ok=False,
                        output_path=None,
                        original_bytes=original_bytes,
                        final_bytes=0,
                        width=cur_w,
                        height=cur_h,
                        scale=round(effective_scale, 4),
                        quality=None,
                        steps=steps,
                        error=(
                            f"Smallest I can make this is ~{smallest_sz} "
                            f"at {min_dim_eff} px; try a larger target."
                        ),
                    )
                # Step down scale with 0.9 steps
                current_scale *= 0.9
                continue

            # Fits at quality floor: search quality in 60-90
            downscale_q_max = min(quality_max, 90)
            max_data = encode_jpeg(resized_img, downscale_q_max)
            if len(max_data) <= target_bytes:
                best_q = downscale_q_max
                best_data = max_data
            else:
                low = quality_floor
                high = downscale_q_max - 1
                best_q = quality_floor
                best_data = floor_data

                while low <= high:
                    mid = (low + high) // 2
                    mid_data = encode_jpeg(resized_img, mid)
                    if len(mid_data) <= target_bytes:
                        best_q = mid
                        best_data = mid_data
                        low = mid + 1
                    else:
                        high = mid - 1

            best_scale = round(cur_w / orig_w, 4)
            final_w = cur_w
            final_h = cur_h
            break

    # Verify output by reopening
    try:
        with Image.open(io.BytesIO(best_data)) as check_im:
            check_im.verify()
        with Image.open(io.BytesIO(best_data)) as check_im:
            if check_im.size != (final_w, final_h) or check_im.format != "JPEG":
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
        width=final_w,
        height=final_h,
        scale=best_scale,
        quality=best_q,
        steps=steps,
    )
