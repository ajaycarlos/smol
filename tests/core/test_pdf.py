import shutil
import subprocess
from pathlib import Path

from smol.core.pdf import shrink_pdf


def test_shrink_pdf_scanned_under_target(samples_dir: Path, tmp_path: Path):
    """VERIFY requirement: ~5 MB scanned-like PDF goes under 1 MB and opens cleanly."""
    src = tmp_path / "scanned_doc.pdf"
    shutil.copy(samples_dir / "sample_scanned.pdf", src)
    orig_bytes = src.stat().st_size
    assert orig_bytes > 4_000_000, f"Expected ~5 MB scanned PDF, got {orig_bytes}"

    target_bytes = 1_000_000  # 1 MB = 1,000,000 decimal bytes
    result = shrink_pdf(src, target_bytes)

    assert result.ok is True, f"shrink_pdf failed: {result.error}"
    assert result.output_path is not None
    assert result.output_path.exists()
    assert result.output_path != src

    final_bytes = result.output_path.stat().st_size
    assert final_bytes == result.final_bytes
    assert final_bytes <= target_bytes, (
        f"Output {final_bytes} exceeds target {target_bytes}"
    )

    # Verify original file is untouched
    assert src.stat().st_size == orig_bytes

    # Verify result opens syntactically valid with qpdf --check
    check = subprocess.run(
        ["qpdf", "--check", "--warning-exit-0", str(result.output_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, f"qpdf --check failed: {check.stderr}\n{check.stdout}"


def test_shrink_pdf_stops_at_first_rung_that_fits(samples_dir: Path, tmp_path: Path):
    """Test that ladder stops at the highest DPI/quality step that satisfies target."""
    src = tmp_path / "scanned_doc.pdf"
    shutil.copy(samples_dir / "sample_scanned.pdf", src)

    # A generous target (e.g. 2.5 MB) should satisfy rung 0 (200 DPI, quality 80)
    target_bytes = 2_500_000
    result = shrink_pdf(src, target_bytes)

    assert result.ok is True
    assert result.steps == 1
    assert result.quality == 80
    assert result.final_bytes <= target_bytes


def test_shrink_pdf_already_small(samples_dir: Path, tmp_path: Path):
    """Input <= target is untouched and returns ok with warning."""
    src = tmp_path / "sample_text.pdf"
    shutil.copy(samples_dir / "sample_text.pdf", src)
    orig_bytes = src.stat().st_size

    result = shrink_pdf(src, orig_bytes + 5000)

    assert result.ok is True
    assert result.output_path is None
    assert result.steps == 0
    assert result.final_bytes == orig_bytes
    assert result.warning is not None
    assert "already" in result.warning.lower()
    assert src.stat().st_size == orig_bytes


def test_shrink_pdf_impossible_target_honest_failure(samples_dir: Path, tmp_path: Path):
    """Impossible small target fails honestly reporting smallest achievable size."""
    src = tmp_path / "scanned_doc.pdf"
    shutil.copy(samples_dir / "sample_scanned.pdf", src)

    # 5 KB is impossible for this multi-page scanned PDF
    target_bytes = 5_000
    result = shrink_pdf(src, target_bytes)

    assert result.ok is False
    assert result.output_path is None
    assert result.final_bytes > target_bytes
    assert result.error is not None
    assert "smallest" in result.error.lower()
    # Confirm no output or temp files were written in tmp_path besides src
    remaining_files = list(tmp_path.iterdir())
    assert remaining_files == [src]


def test_shrink_pdf_text_only_honest_failure(samples_dir: Path, tmp_path: Path):
    """Text-only PDF that cannot be shrunk further fails honestly."""
    src = tmp_path / "text_doc.pdf"
    shutil.copy(samples_dir / "sample_text.pdf", src)

    # Target smaller than text stream structure
    target_bytes = 500
    result = shrink_pdf(src, target_bytes)

    assert result.ok is False
    assert result.error is not None
    assert any(term in result.error.lower() for term in ("text", "smallest", "cannot"))
    remaining_files = list(tmp_path.iterdir())
    assert remaining_files == [src]


def test_shrink_pdf_atomic_write_and_cleanup(samples_dir: Path, tmp_path: Path):
    """Verifies that temporary files are cleaned up and no .tmp files linger."""
    src = tmp_path / "scanned_doc.pdf"
    shutil.copy(samples_dir / "sample_scanned.pdf", src)

    out_dir = tmp_path / "output_folder"
    out_dir.mkdir()

    result = shrink_pdf(src, 1_000_000, options={"out_dir": out_dir})
    assert result.ok is True
    assert result.output_path is not None
    assert result.output_path.parent == out_dir

    # Check for any lingering temporary files
    lingering_temps = [
        f for f in out_dir.iterdir() if f.name.endswith(".tmp") or ".tmp" in f.name
    ]
    assert lingering_temps == []


def test_shrink_pdf_hostile_filename(samples_dir: Path, tmp_path: Path):
    """Hostile filenames with spaces, unicode, leading hyphens handled safely."""
    hostile_name = "-scanned report (測試) #1.pdf"
    src = tmp_path / hostile_name
    shutil.copy(samples_dir / "sample_scanned.pdf", src)

    result = shrink_pdf(src, 1_000_000)
    assert result.ok is True
    assert result.output_path is not None
    assert result.output_path.exists()
    assert result.final_bytes <= 1_000_000

    check = subprocess.run(
        ["qpdf", "--check", "--warning-exit-0", str(result.output_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0


def test_shrink_pdf_dry_run(samples_dir: Path, tmp_path: Path):
    """Dry run calculates compression result without writing to destination."""
    src = tmp_path / "scanned_doc.pdf"
    shutil.copy(samples_dir / "sample_scanned.pdf", src)

    result = shrink_pdf(src, 1_000_000, options={"dry_run": True})

    assert result.ok is True
    assert result.output_path is None
    assert result.final_bytes <= 1_000_000
    assert list(tmp_path.iterdir()) == [src]


def test_shrink_pdf_step_callback(samples_dir: Path, tmp_path: Path):
    """Step callback receives real progress notifications."""
    src = tmp_path / "scanned_doc.pdf"
    shutil.copy(samples_dir / "sample_scanned.pdf", src)

    steps_called = []

    def on_step(fraction: float, current_bytes: int):
        steps_called.append((fraction, current_bytes))

    result = shrink_pdf(src, 1_000_000, options={"step_callback": on_step})

    assert result.ok is True
    assert len(steps_called) >= 1
    assert steps_called[-1][1] == result.final_bytes
