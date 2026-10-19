import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

import smol.cli


def test_shrink_help(capsys: pytest.CaptureFixture[str]) -> None:
    """`smol shrink --help` prints usage and exits 0."""
    code = smol.cli.main(["shrink", "--help"])
    assert code == 0
    captured = capsys.readouterr()
    assert "--max" in captured.out
    assert "--json" in captured.out
    assert "--dry-run" in captured.out


def test_shrink_bad_usage_no_max(
    samples_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Missing required `--max` exits with code 2."""
    portrait = samples_dir / "portrait.jpg"
    code = smol.cli.main(["shrink", str(portrait)])
    assert code == 2
    captured = capsys.readouterr()
    assert "error" in captured.err.lower() or "usage" in captured.err.lower()


def test_shrink_bad_usage_invalid_max(
    samples_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Invalid `--max` size string exits with code 2."""
    portrait = samples_dir / "portrait.jpg"
    code = smol.cli.main(["shrink", str(portrait), "--max", "not_a_size"])
    assert code == 2
    captured = capsys.readouterr()
    err = captured.err.lower()
    assert "cannot parse size" in err or "error" in err


def test_shrink_bad_usage_no_files(capsys: pytest.CaptureFixture[str]) -> None:
    """Running shrink with no files specified exits with code 2."""
    code = smol.cli.main(["shrink", "--max", "100KB"])
    assert code == 2
    captured = capsys.readouterr()
    assert "error" in captured.err.lower() or "usage" in captured.err.lower()


def test_shrink_bad_usage_invalid_min_side(
    samples_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Invalid `--min-side` value (<= 0) exits with code 2."""
    portrait = samples_dir / "portrait.jpg"
    code = smol.cli.main(["shrink", str(portrait), "--max", "100KB", "--min-side", "0"])
    assert code == 2
    captured = capsys.readouterr()
    assert "min-side" in captured.err.lower() or "error" in captured.err.lower()


def test_shrink_single_file_human_output(
    samples_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Standard shrink produces formatted human output."""
    src = tmp_path / "portrait.jpg"
    shutil.copy2(samples_dir / "portrait.jpg", src)

    code = smol.cli.main(["shrink", str(src), "--max", "100KB"])
    assert code == 0

    captured = capsys.readouterr()
    out = captured.out.strip()
    # Check human output structure: filename, sizes, arrow, dimensions, quality
    assert "portrait.jpg" in out
    assert "→" in out
    assert "MB" in out
    assert "KB" in out
    assert "×" in out
    assert "q" in out

    # Check that output file exists next to original and is <= 100 KB
    out_files = list(tmp_path.glob("portrait_100KB*.jpg"))
    assert len(out_files) == 1
    out_file = out_files[0]
    size = out_file.stat().st_size
    assert 90_000 <= size <= 100_000


def test_shrink_dry_run(
    samples_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--dry-run` prints prediction without creating any file."""
    src = tmp_path / "portrait.jpg"
    shutil.copy2(samples_dir / "portrait.jpg", src)

    code = smol.cli.main(["shrink", str(src), "--max", "100KB", "--dry-run"])
    assert code == 0

    captured = capsys.readouterr()
    out = captured.out.strip()
    assert "portrait.jpg" in out
    assert "→" in out
    assert "KB" in out

    # Ensure no new files were written
    files = list(tmp_path.iterdir())
    assert files == [src]


def test_shrink_json_shape(
    samples_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--json` outputs valid JSON with expected result shape."""
    src = tmp_path / "portrait.jpg"
    shutil.copy2(samples_dir / "portrait.jpg", src)

    code = smol.cli.main(["shrink", str(src), "--max", "100KB", "--json"])
    assert code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, list)
    assert len(data) == 1

    item = data[0]
    assert item["ok"] is True
    assert item["src"] == str(src)
    assert item["output_path"] is not None
    assert Path(item["output_path"]).exists()
    assert item["original_bytes"] > 500_000
    assert 90_000 <= item["final_bytes"] <= 100_000
    assert item["width"] is not None
    assert item["height"] is not None
    assert item["quality"] is not None
    assert item["error"] is None


def test_shrink_impossible_target(
    samples_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """When target size is unreachable, exit 1 and report honest failure."""
    src = tmp_path / "noise_cannot_shrink.jpg"
    shutil.copy2(samples_dir / "noise_cannot_shrink.jpg", src)

    code = smol.cli.main(["shrink", str(src), "--max", "5KB"])
    assert code == 1

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert (
        "Smallest I can make this is" in combined or "try a larger target" in combined
    )

    # Check JSON output on impossible target
    capsys.readouterr()  # clear buffer
    code_json = smol.cli.main(["shrink", str(src), "--max", "5KB", "--json"])
    assert code_json == 1

    captured_json = capsys.readouterr()
    data = json.loads(captured_json.out)
    assert len(data) == 1
    assert data[0]["ok"] is False
    assert "Smallest I can make this is" in data[0]["error"]


def test_shrink_out_dir(
    samples_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--out-dir` saves compressed file into the specified directory."""
    src = tmp_path / "portrait.jpg"
    shutil.copy2(samples_dir / "portrait.jpg", src)

    custom_out = tmp_path / "output_folder"
    code = smol.cli.main(
        ["shrink", str(src), "--max", "100KB", "--out-dir", str(custom_out)]
    )
    assert code == 0

    assert custom_out.exists()
    out_files = list(custom_out.glob("portrait_100KB*.jpg"))
    assert len(out_files) == 1
    assert out_files[0].stat().st_size <= 100_000


def test_shrink_keep_metadata(
    samples_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--keep-metadata` preserves EXIF tags in output."""
    src = tmp_path / "exif_rotated.jpg"
    shutil.copy2(samples_dir / "exif_rotated.jpg", src)

    code = smol.cli.main(["shrink", str(src), "--max", "8KB", "--keep-metadata"])
    assert code == 0

    out_files = list(tmp_path.glob("exif_rotated_8KB*.jpg"))
    assert len(out_files) == 1
    out_file = out_files[0]
    with Image.open(out_file) as im:
        exif = im.getexif()
        assert len(exif) > 0


def test_shrink_multiple_files(
    samples_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Multiple files are shrunk in sequence; exits 0 if all succeed."""
    src1 = tmp_path / "portrait.jpg"
    src2 = tmp_path / "photo.webp"
    shutil.copy2(samples_dir / "portrait.jpg", src1)
    shutil.copy2(samples_dir / "photo.webp", src2)

    code = smol.cli.main(["shrink", str(src1), str(src2), "--max", "100KB"])
    assert code == 0

    captured = capsys.readouterr()
    assert "portrait.jpg" in captured.out
    assert "photo.webp" in captured.out

    assert len(list(tmp_path.glob("portrait_100KB*.jpg"))) == 1
    assert len(list(tmp_path.glob("photo_100KB*.webp"))) == 1


def test_shrink_pdf_success(
    samples_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`smol shrink sample.pdf --max 500KB` successfully shrinks a PDF file."""
    src = tmp_path / "scanned_doc.pdf"
    shutil.copy2(samples_dir / "sample_scanned.pdf", src)

    code = smol.cli.main(["shrink", str(src), "--max", "500KB"])
    assert code == 0

    captured = capsys.readouterr()
    assert "scanned_doc.pdf" in captured.out
    assert "→" in captured.out

    out_files = list(tmp_path.glob("scanned_doc_500KB*.pdf"))
    assert len(out_files) == 1
    assert out_files[0].stat().st_size <= 500_000


def test_shrink_mixed_batch_images_and_pdf(
    samples_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Batch shrinking handles both images and PDFs in the same run."""
    img = tmp_path / "portrait.jpg"
    pdf = tmp_path / "scanned_doc.pdf"
    shutil.copy2(samples_dir / "portrait.jpg", img)
    shutil.copy2(samples_dir / "sample_scanned.pdf", pdf)

    code = smol.cli.main(["shrink", str(img), str(pdf), "--max", "500KB", "--json"])
    assert code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert len(data) == 2
    assert all(item["ok"] is True for item in data)

