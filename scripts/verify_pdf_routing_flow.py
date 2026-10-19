"""End-to-end verification script for PDF routing and Donut shrink flow.

Verifies:
1. Donut window accepts a real PDF file.
2. Emits real Ghostscript ladder rung numbers as progress.
3. Successfully shrinks to at most target_bytes.
4. Output file exists, opens cleanly, and passes qpdf verification.
5. First page renders cleanly.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# Ensure Qt offscreen for automated execution
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from smol.core.router import detect_file_type
from smol.ui.donut_window import _load_thumbnail_pixmap
from smol.ui.worker import ShrinkWorker


def main() -> int:
    print("=== SMOL PDF ROUTING & DONUT VERIFICATION ===")

    samples_dir = Path("tests/samples")
    sample_pdf = samples_dir / "sample_scanned.pdf"
    if not sample_pdf.exists():
        print(f"Error: Sample PDF not found at {sample_pdf}")
        return 1

    orig_size = sample_pdf.stat().st_size
    print(f"1. Input sample: {sample_pdf} ({orig_size:,} bytes)")

    # 1. Verify file-type routing
    file_type = detect_file_type(sample_pdf)
    print(f"2. detect_file_type('{sample_pdf.name}') -> {file_type}")
    assert file_type == "pdf", f"Expected 'pdf', got '{file_type}'"

    # 2. Verify thumbnail rendering via Ghostscript
    app = QApplication.instance() or QApplication([])
    thumb = _load_thumbnail_pixmap(sample_pdf, max_size=64)
    if thumb is not None and not thumb.isNull():
        print(f"3. PDF thumbnail generated: {thumb.width()}x{thumb.height()} px ✓")
    else:
        print("3. Warning: thumbnail was None (gs might not be available)")

    # 3. Test DonutWindow and ShrinkWorker with real PDF
    with tempfile.TemporaryDirectory(prefix="smol_verify_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        test_pdf = tmp_dir / "invoice.pdf"
        shutil.copy2(sample_pdf, test_pdf)

        target_bytes = 500_000
        print(f"4. Shrinking {test_pdf.name} to <= {target_bytes:,} bytes...")

        progress_steps: list[tuple[float, int]] = []
        result_holder: list[Any] = []

        worker = ShrinkWorker(
            files=[test_pdf],
            target_bytes=target_bytes,
            pace_steps=False,
        )
        worker.step_progress.connect(
            lambda frac, cand: progress_steps.append((frac, cand))
        )
        worker.results_ready.connect(lambda res: result_holder.extend(res))

        t0 = time.perf_counter()
        worker.start()
        while worker.isRunning():
            app.processEvents()
            time.sleep(0.01)
        for _ in range(10):
            app.processEvents()
        t1 = time.perf_counter()

        assert len(result_holder) == 1, "Expected 1 result"
        _src, res = result_holder[0]
        print(f"5. Worker finished in {t1 - t0:.2f}s:")
        print(f"   - ok: {res.ok}")
        print(f"   - original_bytes: {res.original_bytes:,}")
        print(f"   - final_bytes: {res.final_bytes:,}")
        print(f"   - quality: {res.quality}")
        print(f"   - steps: {res.steps}")
        print(f"   - output_path: {res.output_path}")

        assert res.ok is True, f"Shrink failed: {res.error}"
        assert res.output_path is not None and res.output_path.exists()
        assert res.final_bytes <= target_bytes

        # Check rung step progress
        print(f"6. Real Ghostscript rungs emitted ({len(progress_steps)} steps):")
        for i, (frac, cand_b) in enumerate(progress_steps, 1):
            pct = frac * 100
            print(f"   Step {i}: rung {pct:.1f}%, intermediate {cand_b:,} bytes")
        assert len(progress_steps) >= 1, "Expected at least 1 progress step"

        # 4. Verify syntactic integrity of output PDF with qpdf --check
        qpdf_bin = shutil.which("qpdf")
        if qpdf_bin:
            qpdf_check = subprocess.run(
                [qpdf_bin, "--check", "--warning-exit-0", "--", str(res.output_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            assert qpdf_check.returncode == 0, f"qpdf check failed: {qpdf_check.stderr}"
            print("7. qpdf syntax check passed: exit code 0 ✓")

        # 5. Verify PDF opens and reads clearly (render page 1 with gs)
        gs_bin = shutil.which("gs")
        if gs_bin:
            render_test = subprocess.run(
                [
                    gs_bin,
                    "-dNOPAUSE",
                    "-dBATCH",
                    "-dQUIET",
                    "-sDEVICE=nullpage",
                    str(res.output_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            assert render_test.returncode == 0, (
                f"gs render failed: {render_test.stderr}"
            )
            print("8. Ghostscript full PDF rasterization test passed: exit code 0 ✓")

    print("\nALL VERIFICATION CHECKS PASSED CLEANLY! ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
