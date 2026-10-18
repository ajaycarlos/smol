from __future__ import annotations

import random
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

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


def test_shrink_image_failure_when_quality_floor_exceeds_target(
    samples_dir: Path, tmp_path: Path
) -> None:
    src_sample = samples_dir / "portrait.jpg"
    src_copy = tmp_path / "large_portrait.jpg"
    content = src_sample.read_bytes()
    src_copy.write_bytes(content)
    file_size = len(content)

    # Target 100 KB, but quality 60 on portrait.jpg is ~625 KB
    target_bytes = 100_000
    result = shrink_image(src_copy, target_bytes=target_bytes)

    assert result.ok is False
    assert result.output_path is None
    assert result.error is not None
    error_msg = result.error.lower()
    assert (
        "quality floor" in error_msg
        or "cannot fit" in error_msg
        or "smallest" in error_msg
    )
    assert result.original_bytes == file_size
    # Original untouched and no extra file created
    assert src_copy.read_bytes() == content
    assert len(list(tmp_path.iterdir())) == 1


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
