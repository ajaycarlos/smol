from __future__ import annotations

import io
import math
import os
import tempfile
from pathlib import Path
from typing import Any

import pillow_heif
from PIL import ExifTags, Image, ImageCms, ImageOps, UnidentifiedImageError

from smol.core.paths import output_path
from smol.core.result import Result
from smol.core.size import format_size

# Register HEIF opener with Pillow for HEIC/AVIF handling
pillow_heif.register_heif_opener()


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


def _encode_webp(
    img: Image.Image,
    quality: int,
    exif: bytes | Image.Exif | None = None,
) -> bytes:
    """Encode Pillow image as WebP with specified quality."""
    buf = io.BytesIO()
    kwargs: dict[str, Any] = {
        "format": "WEBP",
        "quality": quality,
        "method": 4,
    }
    if exif:
        kwargs["exif"] = exif
    img.save(buf, **kwargs)
    return buf.getvalue()


def _encode_png(
    img: Image.Image,
    colors: int | None = None,
) -> bytes:
    """Encode Pillow image as PNG, optionally quantized to a palette of `colors`."""
    buf = io.BytesIO()
    if colors is not None:
        target_img = img.quantize(colors=colors)
    else:
        target_img = img
    target_img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    """Flatten alpha/transparency onto a solid white RGB background."""
    has_alpha = image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    )
    if has_alpha:
        rgba = image.convert("RGBA")
        white_bg = Image.new("RGB", rgba.size, (255, 255, 255))
        white_bg.paste(rgba, mask=rgba.split()[3])
        return white_bg
    elif image.mode != "RGB":
        return image.convert("RGB")
    return image.copy()


def _lossy_quality_search_and_downscale(
    img: Image.Image,
    target_bytes: int,
    target_format: str,
    output_exif: bytes | Image.Exif | None,
    quality_floor: int,
    quality_max: int,
    min_dim: int,
    resampling: Any,
) -> tuple[bool, bytes | None, int, int, float, int | None, int, str | None]:
    """Execute quality binary search and Lanczos downscale ladder for JPEG or WebP."""
    steps = 0

    def encode(im: Image.Image, q: int) -> bytes:
        nonlocal steps
        steps += 1
        if target_format == "JPEG":
            return _encode_jpeg(im, q, exif=output_exif)
        elif target_format == "WEBP":
            return _encode_webp(im, q, exif=output_exif)
        raise ValueError(f"Unsupported lossy format: {target_format}")

    width, height = img.size
    floor_bytes = encode(img, quality_floor)

    if len(floor_bytes) <= target_bytes:
        # Full resolution fits within target; search quality in [floor, max]
        max_bytes = encode(img, quality_max)
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
                mid_data = encode(img, mid)
                if len(mid_data) <= target_bytes:
                    best_q = mid
                    best_data = mid_data
                    low = mid + 1
                else:
                    high = mid - 1

        return True, best_data, width, height, 1.0, best_q, steps, None

    # Full-size quality floor exceeds target: enter downscaling loop
    orig_w, orig_h = width, height
    orig_short = min(orig_w, orig_h)
    min_dim_eff = min(orig_short, min_dim)

    current_scale = math.sqrt(target_bytes / len(floor_bytes)) * 0.98

    while True:
        target_short = orig_short * current_scale
        if target_short <= min_dim_eff or orig_short <= min_dim_eff:
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
        floor_data = encode(resized_img, quality_floor)

        if len(floor_data) > target_bytes:
            if is_floor:
                smallest_sz = format_size(len(floor_data))
                err = (
                    f"Smallest I can make this is ~{smallest_sz} "
                    f"at {min_dim_eff} px; try a larger target."
                )
                return (
                    False,
                    None,
                    cur_w,
                    cur_h,
                    round(effective_scale, 4),
                    None,
                    steps,
                    err,
                )
            current_scale *= 0.9
            continue

        # Fits at quality floor: search quality in [quality_floor, min(quality_max, 90)]
        downscale_q_max = min(quality_max, 90)
        max_data = encode(resized_img, downscale_q_max)
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
                mid_data = encode(resized_img, mid)
                if len(mid_data) <= target_bytes:
                    best_q = mid
                    best_data = mid_data
                    low = mid + 1
                else:
                    high = mid - 1

        return (
            True,
            best_data,
            cur_w,
            cur_h,
            round(cur_w / orig_w, 4),
            best_q,
            steps,
            None,
        )


def shrink_image(
    src: str | Path,
    target_bytes: int,
    options: dict[str, Any] | None = None,
) -> Result:
    """Shrink an image to at most target_bytes.

    Format rules:
    - WebP: same quality search and downscale as JPEG.
    - PNG: palette quantisation 256→128→64 colours, then downscale;
      if still too big and allow_convert=True → produce JPEG with a warning;
      if allow_convert=False → fail with a message suggesting allow_convert.
    - HEIC/AVIF: always output JPEG.
    - Format kept by default for JPEG, PNG, and WebP (options.keep_format=True).
    """
    src_path = Path(src)
    if not src_path.exists():
        return Result(ok=False, error=f"File not found: {src_path}")

    opts = options or {}
    quality_floor = int(opts.get("quality_floor", 60))
    quality_max = int(opts.get("quality_max", 95))
    min_dim = int(opts.get("min_dim", 200))
    strip_metadata = bool(opts.get("strip_metadata", True))
    keep_format = bool(opts.get("keep_format", True))
    allow_convert = bool(opts.get("allow_convert", False))
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
    raw_format = ""
    suffix = src_path.suffix.lower()

    try:
        Image.MAX_IMAGE_PIXELS = max_pixels
        with Image.open(src_path) as raw_img:
            raw_format = (raw_img.format or "").upper()

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

    # Determine initial target format
    if raw_format in ("HEIF", "HEIC", "AVIF") or suffix in (
        ".heic",
        ".heif",
        ".avif",
    ):
        target_format = "JPEG"
    elif keep_format:
        if raw_format == "WEBP" or suffix == ".webp":
            target_format = "WEBP"
        elif raw_format == "PNG" or suffix == ".png":
            target_format = "PNG"
        else:
            target_format = "JPEG"
    else:
        target_format = "JPEG"

    # Color space and alpha handling according to target format
    has_alpha = img.mode in ("RGBA", "LA") or (
        img.mode == "P" and "transparency" in img.info
    )
    if target_format == "JPEG":
        img = _flatten_to_rgb(img)
    elif has_alpha:
        img = img.convert("RGBA")
    elif img.mode != "RGB":
        img = img.convert("RGB")
    else:
        img = img.copy()

    resampling = getattr(Image, "Resampling", Image).LANCZOS
    conversion_warning: str | None = None
    steps = 0
    best_data: bytes | None = None
    final_w = img.width
    final_h = img.height
    best_scale = 1.0
    best_q: int | None = None

    if target_format == "PNG":
        png_steps = 0

        def encode_png_counted(im: Image.Image, colors: int | None = None) -> bytes:
            nonlocal png_steps
            png_steps += 1
            return _encode_png(im, colors)

        orig_w, orig_h = img.size
        orig_short = min(orig_w, orig_h)
        min_dim_eff = min(orig_short, min_dim)

        # 1. Try full resolution unquantized
        unquantized = encode_png_counted(img, None)
        if len(unquantized) <= target_bytes:
            best_data = unquantized
            best_scale = 1.0
            final_w, final_h = orig_w, orig_h
        else:
            # 2. Try palette quantisation: 256 -> 128 -> 64
            last_c_data: bytes = unquantized
            for c in (256, 128, 64):
                data_c = encode_png_counted(img, c)
                last_c_data = data_c
                if len(data_c) <= target_bytes:
                    best_data = data_c
                    best_scale = 1.0
                    best_q = c
                    final_w, final_h = orig_w, orig_h
                    break

            # 3. If full size with 64 colors exceeds target: downscale
            if best_data is None:
                current_scale = math.sqrt(target_bytes / len(last_c_data)) * 0.98

                while True:
                    target_short = orig_short * current_scale
                    if target_short <= min_dim_eff or orig_short <= min_dim_eff:
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

                    resized = img.resize((cur_w, cur_h), resampling)
                    d64 = encode_png_counted(resized, 64)

                    if len(d64) > target_bytes:
                        if is_floor:
                            break
                        current_scale *= 0.9
                        continue

                    # Fits with 64 colors!
                    # Refine scale upward to maximize size <= target
                    low_scale = current_scale
                    high_scale = min(
                        1.0, current_scale * math.sqrt(target_bytes / len(d64))
                    )
                    best_scaled_res = resized
                    best_scaled_w = cur_w
                    best_scaled_h = cur_h

                    for _ in range(3):
                        mid_scale = (low_scale + high_scale) / 2
                        mw = max(min_dim_eff, round(orig_w * mid_scale))
                        mh = max(min_dim_eff, round(orig_h * mid_scale))
                        mres = img.resize((mw, mh), resampling)
                        md64 = encode_png_counted(mres, 64)
                        if len(md64) <= target_bytes:
                            low_scale = mid_scale
                            best_scaled_res = mres
                            best_scaled_w = mw
                            best_scaled_h = mh
                        else:
                            high_scale = mid_scale

                    # Pick highest color palette (256 -> 128 -> 64) that fits
                    for c in (256, 128, 64):
                        dc = encode_png_counted(best_scaled_res, c)
                        if len(dc) <= target_bytes:
                            best_data = dc
                            best_q = c
                            best_scale = round(best_scaled_w / orig_w, 4)
                            final_w = best_scaled_w
                            final_h = best_scaled_h
                            break
                    break

        if best_data is None:
            # PNG could not reach target size at min dimension floor
            if allow_convert:
                target_format = "JPEG"
                conversion_warning = (
                    "PNG could not reach target size without conversion; "
                    "converted to JPEG."
                )
                img = _flatten_to_rgb(img)
                (
                    ok,
                    best_data,
                    final_w,
                    final_h,
                    best_scale,
                    best_q,
                    lossy_steps,
                    err_msg,
                ) = _lossy_quality_search_and_downscale(
                    img,
                    target_bytes,
                    "JPEG",
                    output_exif,
                    quality_floor,
                    quality_max,
                    min_dim,
                    resampling,
                )
                steps = png_steps + lossy_steps
                if not ok:
                    return Result(
                        ok=False,
                        original_bytes=original_bytes,
                        width=final_w,
                        height=final_h,
                        scale=best_scale,
                        steps=steps,
                        error=err_msg,
                    )
            else:
                smallest_sz = format_size(len(d64))
                return Result(
                    ok=False,
                    output_path=None,
                    original_bytes=original_bytes,
                    final_bytes=0,
                    width=cur_w,
                    height=cur_h,
                    scale=round(effective_scale, 4),
                    quality=None,
                    steps=png_steps,
                    error=(
                        f"Smallest PNG achievable is ~{smallest_sz} "
                        f"at {min_dim_eff} px; "
                        "try a larger target or enable allow_convert."
                    ),
                )
        else:
            steps = png_steps

    if target_format in ("JPEG", "WEBP") and best_data is None:
        (
            ok,
            best_data,
            final_w,
            final_h,
            best_scale,
            best_q,
            steps,
            err_msg,
        ) = _lossy_quality_search_and_downscale(
            img,
            target_bytes,
            target_format,
            output_exif,
            quality_floor,
            quality_max,
            min_dim,
            resampling,
        )
        if not ok or best_data is None:
            return Result(
                ok=False,
                original_bytes=original_bytes,
                width=final_w,
                height=final_h,
                scale=best_scale,
                steps=steps,
                error=err_msg,
            )

    assert best_data is not None

    # Verify output by reopening
    try:
        with Image.open(io.BytesIO(best_data)) as check_im:
            check_im.verify()
        with Image.open(io.BytesIO(best_data)) as check_im:
            if (
                check_im.size != (final_w, final_h)
                or check_im.format != target_format
            ):
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

    # Determine destination path with correct extension and write atomically
    output_ext: str | None = None
    if target_format == "JPEG" and suffix not in (".jpg", ".jpeg"):
        output_ext = ".jpg"
    elif target_format == "WEBP" and suffix not in (".webp",):
        output_ext = ".webp"
    elif target_format == "PNG" and suffix not in (".png",):
        output_ext = ".png"

    dest_path = output_path(src_path, target_bytes, ext=output_ext)
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
        warning=conversion_warning,
    )
