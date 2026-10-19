"""Unit tests for core engine file-type routing.

Verifies:
- Routing images (JPEG, PNG, WebP, HEIC, etc.) to image engine (shrink_image).
- Routing PDFs (.pdf) to PDF engine (shrink_pdf).
- Ghostscript rung step_callback propagation for PDFs.
- Rejecting unsupported formats honestly.
- Case-insensitivity and hostile filenames.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from smol.core.router import detect_file_type, shrink_file


def test_detect_file_type() -> None:
    """detect_file_type classifies image extensions, PDFs, and unsupported files."""
    assert detect_file_type("photo.jpg") == "image"
    assert detect_file_type("photo.JPEG") == "image"
    assert detect_file_type("graphic.png") == "image"
    assert detect_file_type("banner.webp") == "image"
    assert detect_file_type("raw.heic") == "image"
    assert detect_file_type("raw.avif") == "image"

    assert detect_file_type("document.pdf") == "pdf"
    assert detect_file_type("DOCUMENT.PDF") == "pdf"

    assert detect_file_type("notes.txt") == "unsupported"
    assert detect_file_type("movie.mp4") == "video"
    assert detect_file_type("archive.zip") == "unsupported"


def test_shrink_file_routes_image_to_shrink_image(
    samples_dir: Path, tmp_path: Path
) -> None:
    """shrink_file invokes shrink_image for image files."""
    src = tmp_path / "test_portrait.jpg"
    shutil.copy(samples_dir / "portrait.jpg", src)

    res = shrink_file(src, target_bytes=100_000)
    assert res.ok is True
    assert res.output_path is not None
    assert res.output_path.exists()
    assert res.final_bytes <= 100_000
    assert res.width is not None
    assert res.height is not None


def test_shrink_file_routes_pdf_to_shrink_pdf(
    samples_dir: Path, tmp_path: Path
) -> None:
    """shrink_file invokes shrink_pdf for PDF files."""
    src = tmp_path / "scanned_doc.pdf"
    shutil.copy(samples_dir / "sample_scanned.pdf", src)

    res = shrink_file(src, target_bytes=500_000)
    assert res.ok is True
    assert res.output_path is not None
    assert res.output_path.exists()
    assert res.final_bytes <= 500_000
    assert res.output_path.suffix == ".pdf"


def test_shrink_file_pdf_step_callback(
    samples_dir: Path, tmp_path: Path
) -> None:
    """shrink_file forwards step_callback which receives Ghostscript rung numbers."""
    src = tmp_path / "scanned_doc.pdf"
    shutil.copy(samples_dir / "sample_scanned.pdf", src)

    steps: list[tuple[float, int]] = []

    def on_step(fraction: float, cur_bytes: int) -> None:
        steps.append((fraction, cur_bytes))

    res = shrink_file(src, target_bytes=500_000, options={"step_callback": on_step})
    assert res.ok is True
    assert len(steps) >= 1
    # Check that progress fraction is in (0, 1]
    for frac, b in steps:
        assert 0.0 < frac <= 1.0
        assert b > 0


def test_shrink_file_hostile_filename_pdf(
    samples_dir: Path, tmp_path: Path
) -> None:
    """Hostile PDF names (spaces, unicode, leading dash) route and shrink cleanly."""
    hostile_name = "-invoice (測試) #1.pdf"
    src = tmp_path / hostile_name
    shutil.copy(samples_dir / "sample_scanned.pdf", src)

    res = shrink_file(src, target_bytes=500_000)
    assert res.ok is True
    assert res.output_path is not None
    assert res.output_path.exists()


def test_shrink_file_unsupported_format(tmp_path: Path) -> None:
    """Unsupported file formats return honest failure without crashing."""
    src = tmp_path / "notes.txt"
    src.write_text("Hello world", encoding="utf-8")

    res = shrink_file(src, target_bytes=100)
    assert res.ok is False
    assert (
        "Unsupported file format" in res.error
        or "not supported" in res.error.lower()
    )



def test_shrink_file_video_format_honest_failure(tmp_path: Path) -> None:
    """Video files return honest failure noting coming in future milestone."""
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"\x00" * 1024)

    res = shrink_file(src, target_bytes=500)
    assert res.ok is False
    assert "video" in res.error.lower()
