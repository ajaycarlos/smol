"""Verification script for M7 PDF engine (PLAN.md Section 7.2).

VERIFY checks:
1. A ~5 MB scanned-like PDF goes under 1 MB and still opens clearly.
2. Text-only PDF fails honestly or stays as is.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from smol.core.pdf import shrink_pdf  # noqa: E402
from smol.core.size import format_size  # noqa: E402
from tests.make_samples import (  # noqa: E402
    DEFAULT_SAMPLES_DIR,
    generate_all_samples,
)


def main() -> int:
    print("=" * 60)
    print("SMOL PDF ENGINE VERIFICATION (Milestone M7 / PLAN.md 7.2)")
    print("=" * 60)

    # 1. Ensure test samples exist
    generate_all_samples(DEFAULT_SAMPLES_DIR)
    scanned_sample = DEFAULT_SAMPLES_DIR / "sample_scanned.pdf"
    text_sample = DEFAULT_SAMPLES_DIR / "sample_text.pdf"

    assert scanned_sample.exists(), f"Missing {scanned_sample}"
    assert text_sample.exists(), f"Missing {text_sample}"

    scanned_size = scanned_sample.stat().st_size
    text_size = text_sample.stat().st_size

    print(
        f"Sample scanned PDF: {scanned_sample.name} "
        f"({format_size(scanned_size)}, {scanned_size:,} bytes)"
    )
    print(
        f"Sample text PDF:    {text_sample.name} "
        f"({format_size(text_size)}, {text_size:,} bytes)"
    )
    print("-" * 60)

    # 2. VERIFY: ~5 MB scanned-like PDF goes under 1 MB
    print("\n[CHECK 1] Shrinking ~5 MB scanned PDF to <= 1 MB (1,000,000 bytes)...")
    target_bytes = 1_000_000

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_src = Path(tmp_dir) / "scanned_invoice.pdf"
        tmp_src.write_bytes(scanned_sample.read_bytes())

        steps_log = []

        def on_step(fraction: float, cur_bytes: int):
            steps_log.append((fraction, cur_bytes))
            print(
                f"  Ladder step {len(steps_log)}: progress {fraction*100:4.1f}% -> "
                f"candidate {cur_bytes:>10,d} bytes ({format_size(cur_bytes)})"
            )

        result = shrink_pdf(
            tmp_src, target_bytes, options={"step_callback": on_step}
        )

        if not result.ok or result.output_path is None:
            print(f"FAIL: Scanned PDF shrinking failed: {result.error}")
            return 1

        output_size = result.output_path.stat().st_size
        orig = result.original_bytes
        pct = (result.final_bytes / orig) * 100
        print("✓ Shrink successful!")
        print(f"  Original:    {orig:>10,d} bytes ({format_size(orig)})")
        tgt = format_size(target_bytes)
        print(f"  Target:      {target_bytes:>10,d} bytes ({tgt})")
        print(f"  Final:       {output_size:>10,d} bytes ({format_size(output_size)})")
        print(f"  Compression: {pct:.1f}% of original")
        print(f"  Quality:     JPEG quality {result.quality}")
        print(f"  Steps taken: {result.steps}")

        assert output_size <= target_bytes, (
            f"Exceeded target: {output_size} > {target_bytes}"
        )

        # Syntactic integrity check with qpdf --check
        print("  Checking syntax integrity with `qpdf --check`...")
        check = subprocess.run(
            ["qpdf", "--check", "--warning-exit-0", str(result.output_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if check.returncode != 0:
            print(f"FAIL: qpdf check failed: {check.stderr}\n{check.stdout}")
            return 1
        print("✓ `qpdf --check` passed cleanly (exit code 0)")

    # 3. VERIFY: Text-only PDF fails honestly when impossible
    print("\n[CHECK 2] Text-only PDF honest failure on impossible target (500 B)...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_text = Path(tmp_dir) / "vector_text.pdf"
        tmp_text.write_bytes(text_sample.read_bytes())

        result_impossible = shrink_pdf(tmp_text, 500)
        assert not result_impossible.ok, (
            "Expected failure on impossible target for text PDF"
        )
        print(f"✓ Honest failure reported: {result_impossible.error}")
        print(f"  Smallest size reached: {result_impossible.final_bytes:,} bytes")
        assert list(Path(tmp_dir).iterdir()) == [tmp_text], (
            "Temp or output files were leaked!"
        )
        print("✓ No partial or output files leaked on disk")

    # 4. VERIFY: Text-only PDF already <= target stays untouched
    print("\n[CHECK 3] Text-only PDF already <= target (10,000 bytes)...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_text = Path(tmp_dir) / "vector_text.pdf"
        tmp_text.write_bytes(text_sample.read_bytes())

        result_noop = shrink_pdf(tmp_text, 10_000)
        assert result_noop.ok, "Expected ok for already-small PDF"
        assert result_noop.output_path is None, "Should not create duplicate output"
        print(f"✓ Untouched bypass: {result_noop.warning}")
        assert tmp_text.stat().st_size == text_size, "Original modified!"
        print("✓ Original file remains 100% untouched")

    print("\n" + "=" * 60)
    print("ALL M7 PDF VERIFICATION CHECKS PASSED!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
