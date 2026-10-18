from pathlib import Path

from PIL import Image

from tests.make_samples import GENERATORS, SAMPLE_FILES, generate_all_samples


def test_sample_generation_and_inventory(samples_dir: Path):
    """Test that all required sample files are generated and exist."""
    assert len(GENERATORS) == 14
    for filename in GENERATORS:
        sample_path = samples_dir / filename
        assert sample_path.exists(), f"Missing expected sample file: {filename}"
        assert sample_path.stat().st_size > 0, f"Sample file is empty: {filename}"


def test_generate_all_samples_custom_dir(tmp_path: Path):
    """Test generating samples into an arbitrary directory."""
    out_dir = generate_all_samples(tmp_path)
    assert out_dir == tmp_path
    for filename in GENERATORS:
        assert (tmp_path / filename).exists()


def test_portrait_jpeg(samples_dir: Path):
    path = samples_dir / "portrait.jpg"
    assert path.exists()
    size = path.stat().st_size
    # Must be ~1.2 MB (allow 1.0 MB - 1.4 MB)
    assert 1_000_000 <= size <= 1_400_000, f"Portrait size unexpected: {size} bytes"
    with Image.open(path) as img:
        assert img.format == "JPEG"
        w, h = img.size
        assert h > w, f"Expected portrait orientation (h > w), got {w}x{h}"


def test_landscape_jpeg(samples_dir: Path):
    path = samples_dir / "landscape.jpg"
    assert path.exists()
    with Image.open(path) as img:
        assert img.format == "JPEG"
        w, h = img.size
        assert w > h, f"Expected landscape orientation (w > h), got {w}x{h}"


def test_screenshot_png(samples_dir: Path):
    path = samples_dir / "screenshot.png"
    assert path.exists()
    with Image.open(path) as img:
        assert img.format == "PNG"
        assert img.mode in ("RGB", "RGBA", "P")


def test_tiny_jpeg(samples_dir: Path):
    path = samples_dir / "tiny.jpg"
    assert path.exists()
    assert path.stat().st_size < 3_000, (
        f"Expected tiny size < 3 KB, got {path.stat().st_size}"
    )
    with Image.open(path) as img:
        assert img.format == "JPEG"
        assert max(img.size) <= 64


def test_already_small_jpeg(samples_dir: Path):
    path = samples_dir / "already_small.jpg"
    assert path.exists()
    size = path.stat().st_size
    # Must be ~30 KB (allow 25 KB - 35 KB)
    assert 25_000 <= size <= 35_000, f"Expected ~30 KB, got {size} bytes"
    with Image.open(path) as img:
        assert img.format == "JPEG"


def test_grayscale_jpeg(samples_dir: Path):
    path = samples_dir / "grayscale.jpg"
    assert path.exists()
    with Image.open(path) as img:
        assert img.format == "JPEG"
        assert img.mode == "L"


def test_transparent_png(samples_dir: Path):
    path = samples_dir / "transparent.png"
    assert path.exists()
    with Image.open(path) as img:
        assert img.format == "PNG"
        assert img.mode == "RGBA"
        # Check that it actually contains transparent pixels
        extrema = img.getextrema()
        alpha_min = extrema[3][0]
        assert alpha_min < 255, "Image should contain transparent pixels"


def test_cmyk_jpeg(samples_dir: Path):
    path = samples_dir / "cmyk.jpg"
    assert path.exists()
    with Image.open(path) as img:
        assert img.format == "JPEG"
        assert img.mode == "CMYK"


def test_exif_rotated_jpeg(samples_dir: Path):
    path = samples_dir / "exif_rotated.jpg"
    assert path.exists()
    with Image.open(path) as img:
        assert img.format == "JPEG"
        exif = img.getexif()
        # Tag 0x0112 = 274 is Orientation
        orientation = exif.get(274) or exif.get(0x0112)
        assert orientation == 6, f"Orientation EXIF not 6: {exif}"


def test_webp_photo(samples_dir: Path):
    path = samples_dir / "photo.webp"
    assert path.exists()
    with Image.open(path) as img:
        assert img.format == "WEBP"


def test_incompressible_noise(samples_dir: Path):
    path = samples_dir / SAMPLE_FILES["noise_cannot_shrink"]
    assert path.exists()
    assert path.stat().st_size >= 5_000, (
        f"Noise image must be at least 5 KB, got {path.stat().st_size}"
    )
    with Image.open(path) as img:
        assert img.size[0] > 0 and img.size[1] > 0


def test_heic_photo(samples_dir: Path):
    import pillow_heif

    pillow_heif.register_heif_opener()
    path = samples_dir / "sample.heic"
    assert path.exists()
    assert path.stat().st_size > 0
    with Image.open(path) as img:
        assert img.format == "HEIF"
        assert img.size == (600, 400)


def test_avif_photo(samples_dir: Path):
    path = samples_dir / "sample.avif"
    assert path.exists()
    assert path.stat().st_size > 0
    with Image.open(path) as img:
        assert img.format == "AVIF"
        assert img.size == (600, 400)


def test_forty_mp_jpeg(samples_dir: Path):
    path = samples_dir / "forty_mp.jpg"
    assert path.exists()
    with Image.open(path) as img:
        assert img.format == "JPEG"
        assert img.size == (7300, 5500)
        assert img.size[0] * img.size[1] > 40_000_000

