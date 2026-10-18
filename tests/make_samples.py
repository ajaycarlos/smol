#!/usr/bin/env python3
"""Generator script for test image samples used across smol engine tests.

Generates 11 sample images into tests/samples/ (git-ignored):
1. portrait.jpg (~1.2 MB, gradient+noise, height > width)
2. landscape.jpg (landscape JPEG, width > height)
3. screenshot.png (flat colours and UI text, PNG)
4. tiny.jpg (tiny JPEG, 32x32, < 2 KB)
5. already_small.jpg (~30 KB JPEG)
6. grayscale.jpg (grayscale JPEG, mode 'L')
7. transparent.png (PNG with transparency, mode 'RGBA')
8. cmyk.jpg (CMYK JPEG, mode 'CMYK')
9. exif_rotated.jpg (EXIF orientation tag 6)
10. photo.webp (WebP format photo)
11. noise_cannot_shrink.jpg (random noise image that cannot compress below 5 KB)
"""

from __future__ import annotations

import random
from pathlib import Path

import pillow_heif
from PIL import Image, ImageDraw

pillow_heif.register_heif_opener()

DEFAULT_SAMPLES_DIR = Path(__file__).resolve().parent / "samples"

SAMPLE_FILES = {
    "portrait": "portrait.jpg",
    "landscape": "landscape.jpg",
    "screenshot": "screenshot.png",
    "tiny": "tiny.jpg",
    "already_small": "already_small.jpg",
    "grayscale": "grayscale.jpg",
    "transparent": "transparent.png",
    "cmyk": "cmyk.jpg",
    "exif_rotated": "exif_rotated.jpg",
    "photo_webp": "photo.webp",
    "noise_cannot_shrink": "noise_cannot_shrink.jpg",
    "sample_heic": "sample.heic",
    "sample_avif": "sample.avif",
}


def make_portrait_jpeg(path: Path) -> None:
    """Portrait JPEG (~1.2 MB, gradient + noise, height > width)."""
    random.seed(101)
    w, h = 1200, 1600
    grad = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(grad)
    for y in range(0, h, 2):
        c = int(255 * (y / h))
        draw.line([(0, y), (w, y)], fill=(c, 255 - c, 128), width=2)
    noise = Image.frombytes("RGB", (w, h), random.randbytes(w * h * 3))
    blended = Image.blend(grad, noise, 0.70)
    blended.save(path, format="JPEG", quality=85)


def make_landscape_jpeg(path: Path) -> None:
    """Landscape JPEG (width > height)."""
    random.seed(102)
    w, h = 1600, 1000
    img = Image.new("RGB", (w, h), color=(135, 206, 235))
    draw = ImageDraw.Draw(img)
    # Draw simple landscape elements (mountains, sun, ground)
    draw.ellipse([(1200, 100), (1400, 300)], fill=(255, 220, 0))
    draw.polygon([(0, 600), (500, 300), (1000, 650)], fill=(100, 110, 120))
    draw.polygon([(400, 650), (1100, 250), (1600, 600)], fill=(70, 80, 90))
    draw.rectangle([(0, 550), (w, h)], fill=(34, 139, 34))
    img.save(path, format="JPEG", quality=85)


def make_screenshot_png(path: Path) -> None:
    """Screenshot-like PNG (window, controls, and realistic preview content)."""
    random.seed(106)
    w, h = 1000, 750
    img = Image.new("RGB", (w, h), color=(245, 245, 247))
    draw = ImageDraw.Draw(img)

    # Window titlebar
    draw.rectangle([(0, 0), (w, 40)], fill=(40, 44, 52))
    draw.ellipse([(12, 14), (24, 26)], fill=(255, 95, 86))
    draw.ellipse([(32, 14), (44, 26)], fill=(255, 189, 46))
    draw.ellipse([(52, 14), (64, 26)], fill=(39, 201, 63))
    draw.text((80, 13), "smol - Desktop File Compressor", fill=(220, 220, 220))

    # Sidebar
    draw.rectangle([(0, 40), (220, h)], fill=(230, 233, 238))
    draw.text((20, 60), "Navigation", fill=(80, 80, 80))
    draw.text((20, 90), "• Dashboard", fill=(30, 30, 30))
    draw.text((20, 120), "• Settings", fill=(100, 100, 100))
    draw.text((20, 150), "• History", fill=(100, 100, 100))

    # Main content panels
    draw.rectangle(
        [(240, 50), (980, 140)],
        fill=(255, 255, 255),
        outline=(210, 215, 220),
        width=1,
    )
    draw.text((260, 65), "Drop files here to compress", fill=(50, 50, 50))
    draw.text(
        (260, 95),
        "Target: <= 100 KB  |  Format: Keep original",
        fill=(120, 120, 120),
    )

    # Preview card with gradient + noise texture (realistic ~500-700 KB)
    card_w, card_h = 700, 520
    card = Image.new("RGB", (card_w, card_h))
    cdraw = ImageDraw.Draw(card)
    for y in range(card_h):
        cdraw.line(
            [(0, y), (card_w, y)],
            fill=(int(200 * y / card_h), 120, 255 - int(200 * y / card_h)),
        )
    noise_bytes = random.randbytes(card_w * card_h * 3)
    noise = Image.frombytes("RGB", (card_w, card_h), noise_bytes)
    card_blended = Image.blend(card, noise, 0.16)
    img.paste(card_blended, (250, 160))

    img.save(path, format="PNG")


def make_tiny_jpeg(path: Path) -> None:
    """Tiny JPEG (< 3 KB, 32x32)."""
    w, h = 32, 32
    img = Image.new("RGB", (w, h), color=(100, 150, 200))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(8, 8), (24, 24)], fill=(220, 50, 50))
    img.save(path, format="JPEG", quality=75)


def make_already_small_jpeg(path: Path) -> None:
    """Already-small JPEG (~30 KB)."""
    random.seed(103)
    w, h = 380, 280
    grad = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(grad)
    for y in range(0, h, 2):
        draw.line([(0, y), (w, y)], fill=(y % 256, (y * 2) % 256, 100), width=2)
    noise = Image.frombytes("RGB", (w, h), random.randbytes(w * h * 3))
    small = Image.blend(grad, noise, 0.22)
    small.save(path, format="JPEG", quality=80)


def make_grayscale_jpeg(path: Path) -> None:
    """Grayscale JPEG (mode 'L')."""
    w, h = 640, 480
    img = Image.new("L", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        shade = int(255 * (y / h))
        draw.line([(0, y), (w, y)], fill=shade)
    draw.ellipse([(220, 140), (420, 340)], fill=255, outline=0, width=4)
    img.save(path, format="JPEG", quality=85)


def make_transparent_png(path: Path) -> None:
    """PNG with transparency (mode 'RGBA')."""
    w, h = 400, 400
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Semi-transparent circles and opaque rectangle
    draw.ellipse([(40, 40), (280, 280)], fill=(255, 0, 0, 160))
    draw.ellipse([(120, 120), (360, 360)], fill=(0, 0, 255, 160))
    draw.rectangle([(160, 160), (240, 240)], fill=(0, 255, 0, 255))
    img.save(path, format="PNG")


def make_cmyk_jpeg(path: Path) -> None:
    """CMYK JPEG (mode 'CMYK')."""
    w, h = 640, 480
    # CMYK channels: Cyan, Magenta, Yellow, blacK (0..255)
    img = Image.new("CMYK", (w, h), color=(100, 50, 0, 20))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(50, 50), (300, 400)], fill=(0, 200, 100, 10))
    draw.ellipse([(320, 100), (580, 360)], fill=(180, 0, 220, 0))
    img.save(path, format="JPEG", quality=85)


def make_exif_rotated_jpeg(path: Path) -> None:
    """EXIF-rotated JPEG (orientation tag 6)."""
    w, h = 640, 480
    img = Image.new("RGB", (w, h), color=(200, 180, 120))
    draw = ImageDraw.Draw(img)
    draw.polygon([(100, 400), (320, 100), (540, 400)], fill=(40, 100, 180))
    draw.text((220, 420), "Orientation Tag 6", fill=(0, 0, 0))

    exif = img.getexif()
    # 0x0112 = 274: Orientation tag. 6 = Rotate 90 CW
    exif[274] = 6
    img.save(path, format="JPEG", quality=85, exif=exif)


def make_webp_photo(path: Path) -> None:
    """WebP format photo (~250-400 KB with gradients and texture)."""
    random.seed(104)
    w, h = 1000, 800
    base = Image.new("RGB", (w, h), color=(100, 140, 180))
    draw = ImageDraw.Draw(base)
    for y in range(h):
        draw.line(
            [(0, y), (w, y)],
            fill=(int(180 * y / h), int(120 * (1 - y / h)), 150),
        )
    noise = Image.frombytes("RGB", (w, h), random.randbytes(w * h * 3))
    blended = Image.blend(base, noise, 0.25)
    blended.save(path, format="WEBP", quality=90)


def make_heic_photo(path: Path) -> None:
    """HEIC format photo (~60-100 KB)."""
    random.seed(107)
    w, h = 600, 400
    im = Image.new("RGB", (w, h), (120, 180, 240))
    d = ImageDraw.Draw(im)
    d.rectangle([(50, 50), (550, 350)], fill=(200, 100, 50))
    noise = Image.frombytes("RGB", (w, h), random.randbytes(w * h * 3))
    blended = Image.blend(im, noise, 0.15)
    blended.save(path, format="HEIF")


def make_avif_photo(path: Path) -> None:
    """AVIF format photo (~60-100 KB)."""
    random.seed(108)
    w, h = 600, 400
    im = Image.new("RGB", (w, h), (120, 180, 240))
    d = ImageDraw.Draw(im)
    d.rectangle([(50, 50), (550, 350)], fill=(200, 100, 50))
    noise = Image.frombytes("RGB", (w, h), random.randbytes(w * h * 3))
    blended = Image.blend(im, noise, 0.15)
    blended.save(path, format="AVIF")


def make_noise_cannot_shrink(path: Path) -> None:
    """High-entropy noise image that cannot compress below 5 KB."""
    random.seed(105)
    w, h = 250, 250
    noise_bytes = random.randbytes(w * h * 3)
    img = Image.frombytes("RGB", (w, h), noise_bytes)
    # Pure noise JPEG at quality 85 is ~48 KB.
    # At quality 60 (engine quality floor) and minimum dimension (200px),
    # it remains > 19 KB.
    img.save(path, format="JPEG", quality=85)


GENERATORS = {
    "portrait.jpg": make_portrait_jpeg,
    "landscape.jpg": make_landscape_jpeg,
    "screenshot.png": make_screenshot_png,
    "tiny.jpg": make_tiny_jpeg,
    "already_small.jpg": make_already_small_jpeg,
    "grayscale.jpg": make_grayscale_jpeg,
    "transparent.png": make_transparent_png,
    "cmyk.jpg": make_cmyk_jpeg,
    "exif_rotated.jpg": make_exif_rotated_jpeg,
    "photo.webp": make_webp_photo,
    "noise_cannot_shrink.jpg": make_noise_cannot_shrink,
    "sample.heic": make_heic_photo,
    "sample.avif": make_avif_photo,
}


def generate_all_samples(dest_dir: Path | None = None) -> Path:
    """Generate all sample images into dest_dir (defaults to tests/samples/)."""
    target_dir = Path(dest_dir) if dest_dir is not None else DEFAULT_SAMPLES_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    for filename, generator in GENERATORS.items():
        file_path = target_dir / filename
        generator(file_path)

    return target_dir


if __name__ == "__main__":
    out_dir = generate_all_samples()
    print(f"Generated {len(GENERATORS)} sample files in: {out_dir}")
    for p in sorted(out_dir.iterdir()):
        print(f"  {p.name:25s} {p.stat().st_size:>10,d} bytes")
