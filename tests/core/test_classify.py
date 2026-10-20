"""Unit tests for smol.core.classify.

Verifies:
- Header sniffing (max 32 bytes) on real image and PDF samples.
- Extension mismatch handling: trusting header over extension and setting mismatch_note.
- Refusing FIFOs, sockets, device files WITHOUT opening them (os.stat/os.lstat).
- Broken symlinks and symlinks to non-regular files.
- Folders classified as kind="folder" with reason="folder, not supported".
- Remote / non-file URIs classified as kind="remote" with reason="remote".
- 60 files batch classification capping at 50, with remainder as "+N more".
- Never decoding images during classification.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from smol.core.classify import classify, classify_files


def test_header_sniffing_samples(samples_dir: Path) -> None:
    """Header sniffing detects jpeg, png, webp, heic, and pdf from file contents."""
    c_jpg = classify(samples_dir / "portrait.jpg")
    assert c_jpg.kind == "jpeg"
    assert c_jpg.mismatch_note is None

    c_png = classify(samples_dir / "transparent.png")
    assert c_png.kind == "png"
    assert c_png.mismatch_note is None

    c_webp = classify(samples_dir / "photo.webp")
    assert c_webp.kind == "webp"
    assert c_webp.mismatch_note is None

    c_heic = classify(samples_dir / "sample.heic")
    assert c_heic.kind == "heic"
    assert c_heic.mismatch_note is None

    c_pdf = classify(samples_dir / "sample_scanned.pdf")
    assert c_pdf.kind == "pdf"
    assert c_pdf.mismatch_note is None


def test_mismatched_extension(samples_dir: Path, tmp_path: Path) -> None:
    """If extension and header disagree, trust the header and set mismatch_note."""
    # PDF renamed to .jpg
    fake_jpg = tmp_path / "sneaky_pdf.jpg"
    fake_jpg.write_bytes((samples_dir / "sample_scanned.pdf").read_bytes()[:2048])
    c1 = classify(fake_jpg)
    assert c1.kind == "pdf"
    assert c1.mismatch_note is not None
    assert "jpg" in c1.mismatch_note.lower()

    # JPEG renamed to .pdf
    fake_pdf = tmp_path / "sneaky_img.pdf"
    fake_pdf.write_bytes((samples_dir / "portrait.jpg").read_bytes()[:2048])
    c2 = classify(fake_pdf)
    assert c2.kind == "jpeg"
    assert c2.mismatch_note is not None
    assert "pdf" in c2.mismatch_note.lower()


def test_refuse_fifo(tmp_path: Path) -> None:
    """Refuse FIFOs without opening them."""
    fifo_path = tmp_path / "test_pipe.fifo"
    try:
        os.mkfifo(fifo_path)
    except (AttributeError, OSError) as e:
        pytest.skip(f"mkfifo not supported on this platform/filesystem: {e}")

    # If classify tried to open(fifo_path, "rb") without O_NONBLOCK, it would hang.
    c = classify(fifo_path)
    assert c.kind in ("unsupported", "unreadable")
    assert c.reason is not None
    assert "fifo" in c.reason.lower() or "not a regular file" in c.reason.lower()


def test_broken_symlink_and_symlink_to_fifo(tmp_path: Path) -> None:
    """Do not follow symlinks to non-regular files and handle broken symlinks."""
    # Broken symlink
    broken = tmp_path / "broken_link.jpg"
    broken.symlink_to(tmp_path / "non_existent_file.jpg")
    c_broken = classify(broken)
    assert c_broken.kind in ("unreadable", "unsupported")

    # Symlink to a FIFO
    fifo_target = tmp_path / "target_fifo"
    try:
        os.mkfifo(fifo_target)
    except (AttributeError, OSError) as e:
        pytest.skip(f"mkfifo not supported: {e}")

    sym_fifo = tmp_path / "sym_to_fifo.jpg"
    sym_fifo.symlink_to(fifo_target)

    c_sym = classify(sym_fifo)
    assert c_sym.kind in ("unsupported", "unreadable")


def test_folder_classification(tmp_path: Path) -> None:
    """Folders are classified as kind='folder' with reason='folder, not supported'."""
    subfolder = tmp_path / "my_photos"
    subfolder.mkdir()
    c = classify(subfolder)
    assert c.kind == "folder"
    assert c.reason == "folder, not supported"


def test_remote_uri() -> None:
    """Non-file:// URIs are classified with kind='remote' and reason='remote'."""
    assert classify("http://example.com/photo.jpg").kind == "remote"
    assert classify("http://example.com/photo.jpg").reason == "remote"
    assert classify("https://example.com/photo.png").kind == "remote"
    assert classify("ftp://server/doc.pdf").kind == "remote"
    assert classify("data:image/jpeg;base64,12345").kind == "remote"
    assert classify("data:image/jpeg;base64,12345").reason == "remote"


def test_batch_classification_cap_50(tmp_path: Path) -> None:
    """Classify at most 50 files; the rest count as '+N more' (unknown)."""
    # Create 60 small valid text/dummy files
    paths: list[Path] = []
    for i in range(60):
        p = tmp_path / f"file_{i:02d}.jpg"
        # Write valid JPEG header
        p.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 28)
        paths.append(p)

    batch = classify_files([str(p) for p in paths])
    assert batch.total_count == 60
    assert batch.classified_count == 50
    assert batch.more_count == 10
    assert batch.more_label == "+10 more"
    assert len(batch.items) == 50
    assert batch.has_unknown is True


def test_never_decode_images(
    samples_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure image decoding (e.g. PIL.Image.open) is never called."""

    def bomb_open(*args, **kwargs):
        raise AssertionError("Image.open must NEVER be called during classification!")

    import PIL.Image

    monkeypatch.setattr(PIL.Image, "open", bomb_open)

    # Classify should succeed purely via header sniffing
    c = classify(samples_dir / "portrait.jpg")
    assert c.kind == "jpeg"
