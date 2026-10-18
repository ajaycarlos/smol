from __future__ import annotations

import random
from pathlib import Path

import pytest
from PIL import ExifTags, Image, ImageCms, ImageDraw

from smol.core.image import shrink_image
from smol.core.result import Result


def _create_compressible_jpeg(
    path: Path, width: int, height: int, seed: int = 42
) -> Path:
    """Create a compressible JPEG spanning ~84 KB at q=60 to ~500 KB at q=95."""
    random.seed(seed)
    base = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(base)
    for y in range(height):
        draw.line([(0, y), (width, y)], fill=(y % 256, (y * 2) % 256, 128))
    noise_data = random.randbytes(width * height * 3)
    noise = Image.frombytes("RGB", (width, height), noise_data)
    blended = Image.blend(base, noise, 0.15)
    blended.save(path, format="JPEG", quality=95)
    return path


@pytest.mark.parametrize(
    "orientation, dims",
    [("portrait", (800, 1200)), ("landscape", (1200, 800))],
)
@pytest.mark.parametrize("target_bytes", [100_000, 200_000])
def test_shrink_image_portrait_and_landscape_targets(
    tmp_path: Path, orientation: str, dims: tuple[int, int], target_bytes: int
) -> None:
    w, h = dims
    src_file = tmp_path / f"{orientation}.jpg"
    _create_compressible_jpeg(src_file, w, h, seed=123)

    initial_bytes = src_file.read_bytes()
    initial_stat_size = src_file.stat().st_size
    assert initial_stat_size > target_bytes

    result = shrink_image(src_file, target_bytes=target_bytes)

    # 1. Result structure and success
    assert isinstance(result, Result)
    assert result.ok is True
    assert result.output_path is not None
    assert result.output_path.exists()
    assert result.output_path != src_file

    # 2. Original file completely untouched
    assert src_file.read_bytes() == initial_bytes
    assert src_file.stat().st_size == initial_stat_size

    # 3. Output size promises: <= target AND >= 90% of target
    final_size = result.output_path.stat().st_size
    assert result.final_bytes == final_size
    assert final_size <= target_bytes, f"Expected {final_size} <= {target_bytes}"
    min_acceptable = int(0.90 * target_bytes)
    assert final_size >= min_acceptable, (
        f"Expected {final_size} >= {min_acceptable} (90% of {target_bytes})"
    )

    # 4. Result metadata populated
    assert result.original_bytes == initial_stat_size
    assert result.width == w
    assert result.height == h
    assert result.quality is not None
    assert 60 <= result.quality <= 95
    assert result.steps > 0

    # 5. Output file verification by reopening
    with Image.open(result.output_path) as out_img:
        assert out_img.format == "JPEG"
        assert out_img.size == (w, h)
        assert out_img.mode == "RGB"


def test_shrink_image_already_small(samples_dir: Path, tmp_path: Path) -> None:
    src_sample = samples_dir / "already_small.jpg"
    src_copy = tmp_path / "already_small.jpg"
    content = src_sample.read_bytes()
    src_copy.write_bytes(content)
    file_size = len(content)

    # Target is 100 KB (100,000 bytes), file is ~30 KB
    target_bytes = 100_000
    assert file_size < target_bytes

    result = shrink_image(src_copy, target_bytes=target_bytes)

    assert result.ok is True
    assert result.output_path is None
    assert result.warning is not None
    assert "already" in result.warning.lower()
    assert result.original_bytes == file_size
    assert result.final_bytes == file_size
    # Original untouched and no extra file created
    assert src_copy.read_bytes() == content
    assert len(list(tmp_path.iterdir())) == 1


def test_shrink_image_downscale_success(
    samples_dir: Path, tmp_path: Path
) -> None:
    src_sample = samples_dir / "portrait.jpg"
    src_copy = tmp_path / "portrait_downscale.jpg"
    content = src_sample.read_bytes()
    src_copy.write_bytes(content)
    file_size = len(content)

    # portrait.jpg at q=60 is ~625 KB. Target 100 KB requires downscaling.
    target_bytes = 100_000
    result = shrink_image(src_copy, target_bytes=target_bytes)

    assert result.ok is True
    assert result.output_path is not None
    assert result.output_path.exists()
    assert result.output_path != src_copy

    # Original file untouched
    assert src_copy.read_bytes() == content

    # Size promises: <= target AND >= 90% of target
    final_size = result.output_path.stat().st_size
    assert result.final_bytes == final_size
    assert final_size <= target_bytes
    assert final_size >= int(0.90 * target_bytes)

    # Result metadata: scale recorded, dimensions shrunk, floor respected
    assert result.original_bytes == file_size
    assert result.scale is not None
    assert 0.0 < result.scale < 1.0
    assert result.width is not None and result.height is not None
    assert result.width < 1200
    assert result.height < 1600
    assert min(result.width, result.height) >= 200
    assert result.quality is not None
    assert 60 <= result.quality <= 90
    assert result.steps > 0

    # Verify output reopened
    with Image.open(result.output_path) as out_img:
        assert out_img.format == "JPEG"
        assert out_img.size == (result.width, result.height)
        assert out_img.mode == "RGB"


def test_shrink_image_noise_cannot_shrink_failure(
    samples_dir: Path, tmp_path: Path
) -> None:
    src_sample = samples_dir / "noise_cannot_shrink.jpg"
    src_copy = tmp_path / "noise_sample.jpg"
    content = src_sample.read_bytes()
    src_copy.write_bytes(content)
    file_size = len(content)

    # Noise image cannot fit 5 KB even at 200 px floor
    target_bytes = 5_000
    result = shrink_image(src_copy, target_bytes=target_bytes)

    assert result.ok is False
    assert result.output_path is None
    assert result.error is not None
    error_msg = result.error.lower()
    assert "smallest i can make this is ~" in error_msg
    assert "200 px" in error_msg
    assert "try a larger target" in error_msg
    assert result.original_bytes == file_size
    assert result.steps > 0
    # Original untouched and no extra file created
    assert src_copy.read_bytes() == content
    assert len(list(tmp_path.iterdir())) == 1


def test_shrink_image_respects_custom_min_dim(
    samples_dir: Path, tmp_path: Path
) -> None:
    src_sample = samples_dir / "portrait.jpg"
    src_copy = tmp_path / "custom_min_portrait.jpg"
    content = src_sample.read_bytes()
    src_copy.write_bytes(content)

    # At 400 px minimum short-side, portrait cannot fit in 10 KB
    target_bytes = 10_000
    result = shrink_image(src_copy, target_bytes=target_bytes, options={"min_dim": 400})

    assert result.ok is False
    assert result.output_path is None
    assert result.error is not None
    assert "400 px" in result.error
    assert "try a larger target" in result.error.lower()
    assert src_copy.read_bytes() == content


def test_shrink_image_atomic_write(tmp_path: Path) -> None:
    src_file = tmp_path / "test_atomic.jpg"
    _create_compressible_jpeg(src_file, 800, 1200, seed=55)

    result = shrink_image(src_file, target_bytes=100_000)
    assert result.ok is True
    assert result.output_path is not None
    assert result.output_path.exists()

    # Verify no stray temp files in folder
    all_files = list(tmp_path.iterdir())
    assert len(all_files) == 2  # src_file and output_path
    for f in all_files:
        assert not f.name.endswith(".tmp")


def test_shrink_image_strips_gps_and_camera_metadata_by_default(
    tmp_path: Path,
) -> None:
    src_file = tmp_path / "metadata_test.jpg"
    _create_compressible_jpeg(src_file, 600, 800, seed=77)

    # Inject EXIF camera info and GPS tags
    with Image.open(src_file) as im:
        exif = im.getexif()
        exif[ExifTags.Base.Make] = "CameraBrand"
        exif[ExifTags.Base.Model] = "ModelX"
        gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
        gps[ExifTags.GPS.GPSLatitudeRef] = "N"
        gps[ExifTags.GPS.GPSLatitude] = (37.0, 46.0, 0.0)
        im.save(src_file, format="JPEG", exif=exif)

    # 1. Default shrink: metadata MUST be stripped
    result_default = shrink_image(src_file, target_bytes=50_000)
    assert result_default.ok is True
    assert result_default.output_path is not None
    assert result_default.output_path.exists()

    with Image.open(result_default.output_path) as out_img:
        out_exif = out_img.getexif()
        # Assert no GPS tags and no camera metadata
        gps_tags = out_exif.get_ifd(ExifTags.IFD.GPSInfo)
        assert len(gps_tags) == 0, f"Expected no GPS tags, found: {gps_tags}"
        assert ExifTags.Base.Make not in out_exif
        assert ExifTags.Base.Model not in out_exif

    # 2. Option to keep metadata: strip_metadata = False
    result_keep = shrink_image(
        src_file, target_bytes=50_000, options={"strip_metadata": False}
    )
    assert result_keep.ok is True
    assert result_keep.output_path is not None

    with Image.open(result_keep.output_path) as out_img:
        out_exif = out_img.getexif()
        assert out_exif.get(ExifTags.Base.Make) == "CameraBrand"
        assert out_exif.get(ExifTags.Base.Model) == "ModelX"
        gps_tags = out_exif.get_ifd(ExifTags.IFD.GPSInfo)
        assert len(gps_tags) > 0


def test_shrink_image_exif_rotation_baked_into_pixels(
    samples_dir: Path, tmp_path: Path
) -> None:
    src_sample = samples_dir / "exif_rotated.jpg"
    src_copy = tmp_path / "rotated.jpg"
    src_copy.write_bytes(src_sample.read_bytes())

    # Raw sample is 640x480 (~11.7 KB) with orientation tag 6 (rotate 90 CW)
    with Image.open(src_copy) as raw_im:
        assert raw_im.size == (640, 480)
        assert raw_im.getexif().get(ExifTags.Base.Orientation) == 6

    # Target 10 KB (< 11.7 KB) to trigger compression
    result = shrink_image(src_copy, target_bytes=10_000)
    assert result.ok is True
    assert result.output_path is not None

    # Rotated 90 deg CW means width and height must be swapped: 480x640
    assert result.width == 480
    assert result.height == 640

    with Image.open(result.output_path) as out_img:
        assert out_img.size == (480, 640)
        # Orientation tag must not remain 6 (avoid double-rotation)
        out_exif = out_img.getexif()
        assert out_exif.get(ExifTags.Base.Orientation) != 6


def test_shrink_image_cmyk_converted_to_srgb(
    samples_dir: Path, tmp_path: Path
) -> None:
    src_sample = samples_dir / "cmyk.jpg"
    src_copy = tmp_path / "cmyk_test.jpg"
    src_copy.write_bytes(src_sample.read_bytes())

    # cmyk.jpg is ~32.5 KB; target 20 KB triggers compression
    result = shrink_image(src_copy, target_bytes=20_000)
    assert result.ok is True
    assert result.output_path is not None

    with Image.open(result.output_path) as out_img:
        assert out_img.format == "JPEG"
        assert out_img.mode == "RGB"


def test_shrink_image_grayscale_handled(
    samples_dir: Path, tmp_path: Path
) -> None:
    src_sample = samples_dir / "grayscale.jpg"
    src_copy = tmp_path / "gray_test.jpg"
    src_copy.write_bytes(src_sample.read_bytes())

    # grayscale.jpg is ~11.9 KB; target 10 KB triggers compression
    result = shrink_image(src_copy, target_bytes=10_000)
    assert result.ok is True
    assert result.output_path is not None

    with Image.open(result.output_path) as out_img:
        assert out_img.format == "JPEG"
        assert out_img.mode == "RGB"


def test_shrink_image_png_transparency_flattened_onto_white(
    samples_dir: Path, tmp_path: Path
) -> None:
    src_file = tmp_path / "trans_test.png"
    w, h = 600, 600
    random.seed(42)
    base = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(base)
    draw.ellipse([(50, 50), (550, 550)], fill=(200, 50, 100, 200))
    noise = Image.frombytes("RGBA", (w, h), random.randbytes(w * h * 4))
    mask = base.split()[3]
    blended = Image.composite(noise, base, mask)
    blended.save(src_file, format="PNG")

    with Image.open(src_file) as raw_im:
        assert raw_im.mode == "RGBA"
        # Pixel (0,0) is transparent (alpha = 0)
        assert raw_im.getpixel((0, 0))[3] == 0

    # Shrink compressible RGBA PNG to JPEG target (keep_format=False)
    result = shrink_image(src_file, target_bytes=80_000, options={"keep_format": False})
    assert result.ok is True
    assert result.output_path is not None

    with Image.open(result.output_path) as out_img:
        assert out_img.format == "JPEG"
        assert out_img.mode == "RGB"  # No alpha channel in JPEG
        # Transparent background flattened onto white
        pixel_0_0 = out_img.getpixel((0, 0))
        assert pixel_0_0[0] > 240 and pixel_0_0[1] > 240 and pixel_0_0[2] > 240

    # Also test force_reencode on samples_dir / transparent.png to JPEG
    # with keep_format=False
    sample_copy = tmp_path / "sample_transparent.png"
    sample_copy.write_bytes((samples_dir / "transparent.png").read_bytes())
    res_sample = shrink_image(
        sample_copy,
        target_bytes=10_000,
        options={"force_reencode": True, "keep_format": False},
    )
    assert res_sample.ok is True
    assert res_sample.output_path is not None
    with Image.open(res_sample.output_path) as out_sample:
        assert out_sample.format == "JPEG"
        assert out_sample.mode == "RGB"
        p = out_sample.getpixel((0, 0))
        assert p[0] > 240 and p[1] > 240 and p[2] > 240


def test_shrink_image_icc_profile_converted_to_srgb(tmp_path: Path) -> None:
    src_file = tmp_path / "icc_test.jpg"
    w, h = 400, 400
    # Create compressible base (~80 KB)
    _create_compressible_jpeg(src_file, w, h, seed=99)

    srgb_prof = ImageCms.createProfile("sRGB")
    icc_bytes = ImageCms.ImageCmsProfile(srgb_prof).tobytes()

    with Image.open(src_file) as base:
        base.save(src_file, format="JPEG", quality=90, icc_profile=icc_bytes)

    result = shrink_image(src_file, target_bytes=30_000)
    assert result.ok is True
    assert result.output_path is not None

    with Image.open(result.output_path) as out_img:
        assert out_img.format == "JPEG"
        assert out_img.mode == "RGB"


def test_shrink_image_decompression_bomb_guard(tmp_path: Path) -> None:
    src_file = tmp_path / "large_pixels.jpg"
    # Create 400x500 = 200,000 pixels image
    _create_compressible_jpeg(src_file, 400, 500, seed=88)

    # Set max_pixels limit below image total pixels (e.g. 50,000)
    result = shrink_image(
        src_file, target_bytes=20_000, options={"max_pixels": 50_000}
    )
    assert result.ok is False
    assert result.output_path is None
    assert result.error is not None
    assert "decompression bomb" in result.error.lower()


def test_shrink_image_webp_format_kept_and_searched(
    samples_dir: Path, tmp_path: Path
) -> None:
    src_sample = samples_dir / "photo.webp"
    src_copy = tmp_path / "test.webp"
    src_copy.write_bytes(src_sample.read_bytes())
    orig_bytes = src_copy.stat().st_size
    assert orig_bytes > 100_000

    target_bytes = 100_000
    result = shrink_image(src_copy, target_bytes=target_bytes)

    assert result.ok is True
    assert result.output_path is not None
    assert result.output_path.exists()
    assert result.output_path.suffix == ".webp"
    assert result.final_bytes <= target_bytes
    assert result.final_bytes >= int(0.90 * target_bytes)
    assert result.quality is not None
    assert 60 <= result.quality <= 95

    with Image.open(result.output_path) as out_img:
        assert out_img.format == "WEBP"
        assert out_img.size == (result.width, result.height)


def test_shrink_image_png_quantization_and_downscale(
    samples_dir: Path, tmp_path: Path
) -> None:
    src_sample = samples_dir / "screenshot.png"
    src_copy = tmp_path / "screen_test.png"
    src_copy.write_bytes(src_sample.read_bytes())

    target_bytes = 100_000
    result = shrink_image(src_copy, target_bytes=target_bytes)

    assert result.ok is True
    assert result.output_path is not None
    assert result.output_path.exists()
    assert result.output_path.suffix == ".png"
    assert result.final_bytes <= target_bytes

    with Image.open(result.output_path) as out_img:
        assert out_img.format == "PNG"
        assert out_img.size == (result.width, result.height)


def test_shrink_image_png_impossible_fails_when_allow_convert_false(
    tmp_path: Path,
) -> None:
    # High-entropy 250x250 random noise PNG cannot compress below 10 KB at 200px floor
    random.seed(111)
    w, h = 250, 250
    noise_data = random.randbytes(w * h * 3)
    noise_img = Image.frombytes("RGB", (w, h), noise_data)
    src_file = tmp_path / "incompressible.png"
    noise_img.save(src_file, format="PNG")

    target_bytes = 3_000
    result = shrink_image(
        src_file,
        target_bytes=target_bytes,
        options={"allow_convert": False, "min_dim": 200},
    )

    assert result.ok is False
    assert result.output_path is None
    assert result.error is not None
    error_msg = result.error.lower()
    assert "allow_convert" in error_msg
    assert "smallest" in error_msg


def test_shrink_image_png_impossible_converts_to_jpeg_when_allow_convert_true(
    tmp_path: Path,
) -> None:
    # High-entropy noise PNG that cannot fit in PNG at 20 KB, but JPEG can compress it
    random.seed(112)
    w, h = 250, 250
    noise_data = random.randbytes(w * h * 3)
    noise_img = Image.frombytes("RGB", (w, h), noise_data)
    src_file = tmp_path / "incompressible_convert.png"
    noise_img.save(src_file, format="PNG")

    target_bytes = 20_000
    result = shrink_image(
        src_file,
        target_bytes=target_bytes,
        options={"allow_convert": True, "min_dim": 200},
    )

    assert result.ok is True
    assert result.output_path is not None
    assert result.output_path.suffix in (".jpg", ".jpeg")
    assert result.final_bytes <= target_bytes
    assert result.warning is not None
    warning_msg = result.warning.lower()
    assert "converted" in warning_msg or "jpeg" in warning_msg

    with Image.open(result.output_path) as out_img:
        assert out_img.format == "JPEG"


def test_shrink_image_heic_to_jpeg(samples_dir: Path, tmp_path: Path) -> None:
    src_sample = samples_dir / "sample.heic"
    src_copy = tmp_path / "input.heic"
    src_copy.write_bytes(src_sample.read_bytes())

    target_bytes = 40_000
    result = shrink_image(src_copy, target_bytes=target_bytes)

    assert result.ok is True
    assert result.output_path is not None
    assert result.output_path.suffix in (".jpg", ".jpeg")
    assert result.final_bytes <= target_bytes

    with Image.open(result.output_path) as out_img:
        assert out_img.format == "JPEG"


def test_shrink_image_avif_to_jpeg(samples_dir: Path, tmp_path: Path) -> None:
    src_sample = samples_dir / "sample.avif"
    src_copy = tmp_path / "input.avif"
    src_copy.write_bytes(src_sample.read_bytes())

    target_bytes = 40_000
    result = shrink_image(src_copy, target_bytes=target_bytes)

    assert result.ok is True
    assert result.output_path is not None
    assert result.output_path.suffix in (".jpg", ".jpeg")
    assert result.final_bytes <= target_bytes

    with Image.open(result.output_path) as out_img:
        assert out_img.format == "JPEG"


def test_shrink_image_screenshot_png_reaches_100kb(
    samples_dir: Path, tmp_path: Path
) -> None:
    src_sample = samples_dir / "screenshot.png"
    src_copy = tmp_path / "screenshot.png"
    src_copy.write_bytes(src_sample.read_bytes())
    assert src_copy.stat().st_size > 100_000

    target_bytes = 100_000
    result = shrink_image(src_copy, target_bytes=target_bytes)

    assert result.ok is True
    assert result.output_path is not None
    assert result.output_path.suffix == ".png"
    assert result.final_bytes <= target_bytes
    min_acceptable = int(0.90 * target_bytes)
    assert result.final_bytes >= min_acceptable, (
        f"Expected {result.final_bytes} >= {min_acceptable} bytes"
    )

    with Image.open(result.output_path) as out_img:
        assert out_img.format == "PNG"


def test_shrink_image_forty_mp_reaches_100kb(
    samples_dir: Path, tmp_path: Path
) -> None:
    src_sample = samples_dir / "forty_mp.jpg"
    src_copy = tmp_path / "forty_mp.jpg"
    src_copy.write_bytes(src_sample.read_bytes())
    assert src_copy.stat().st_size > 500_000

    target_bytes = 100_000
    result = shrink_image(src_copy, target_bytes=target_bytes)

    assert result.ok is True
    assert result.output_path is not None
    assert result.output_path.exists()
    assert result.output_path.suffix in (".jpg", ".jpeg")
    assert result.final_bytes <= target_bytes
    assert result.final_bytes >= int(0.90 * target_bytes), (
        f"Expected {result.final_bytes} >= {int(0.90 * target_bytes)}"
    )

    with Image.open(result.output_path) as out_img:
        assert out_img.format == "JPEG"
        assert out_img.size == (result.width, result.height)


def test_shrink_image_lossy_scale_refinement_lands_above_90pct(
    samples_dir: Path, tmp_path: Path
) -> None:
    src_sample = samples_dir / "portrait.jpg"
    src_copy = tmp_path / "portrait.jpg"
    src_copy.write_bytes(src_sample.read_bytes())

    target_bytes = 20_000
    result = shrink_image(src_copy, target_bytes=target_bytes)

    assert result.ok is True
    assert result.output_path is not None
    assert result.output_path.exists()
    assert result.final_bytes <= target_bytes
    # Must land >= 90% (Promise 1: aim 92-99%)
    assert result.final_bytes >= int(0.90 * target_bytes), (
        f"Expected {result.final_bytes} >= 18000, got {result.final_bytes}"
    )
    # Refinement must preserve higher dimensions than unrefined 210x280
    assert result.width is not None and result.width > 210

    with Image.open(result.output_path) as out_img:
        assert out_img.format == "JPEG"


def test_shrink_image_min_dim_guard_prevents_zero_dim(
    samples_dir: Path, tmp_path: Path
) -> None:
    src_sample = samples_dir / "tiny.jpg"
    src_copy = tmp_path / "tiny.jpg"
    src_copy.write_bytes(src_sample.read_bytes())

    # Passing min_dim <= 0 should be guarded to max(1, min_dim)
    result = shrink_image(
        src_copy,
        target_bytes=500,
        options={"min_dim": 0, "force_reencode": True},
    )
    assert result.width is not None and result.width >= 1
    assert result.height is not None and result.height >= 1
    if result.ok and result.output_path:
        assert result.output_path.exists()
        with Image.open(result.output_path) as im:
            assert im.size[0] >= 1 and im.size[1] >= 1


def test_shrink_image_post_write_size_verification_guard(
    samples_dir: Path, tmp_path: Path, monkeypatch
) -> None:
    src_sample = samples_dir / "landscape.jpg"
    src_copy = tmp_path / "landscape.jpg"
    src_copy.write_bytes(src_sample.read_bytes())

    import tempfile

    orig_named_temp = tempfile.NamedTemporaryFile

    def fake_named_temp(*args, **kwargs):
        temp_obj = orig_named_temp(*args, **kwargs)
        orig_write = temp_obj.write

        def expanding_write(data: bytes):
            # Inject extra bytes to violate target_bytes on disk
            return orig_write(data + b"\x00" * 50_000)

        temp_obj.write = expanding_write
        return temp_obj

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", fake_named_temp)

    target_bytes = 20_000
    result = shrink_image(src_copy, target_bytes=target_bytes)
    # Should detect final_bytes > target_bytes, delete the file, and return ok=False
    assert result.ok is False
    assert result.error is not None
    assert "exceeds target" in result.error.lower()
    if result.output_path is not None:
        assert not result.output_path.exists()


