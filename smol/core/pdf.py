"""PDF shrinking engine using Ghostscript downsampling ladder and qpdf optimization.

Implements PLAN.md section 7.2:
- Ghostscript downsampling ladder at decreasing DPI: 200 -> 150 -> 120 -> 96 -> 72 -> 60
  with JPEG quality ~80 -> 50.
- Stop at the first (highest quality) rung whose output fits <= target_bytes.
- qpdf object-stream optimisation (--object-streams=generate).
- Atomic write with destination directory same-filesystem rename.
- Syntactic integrity verification via `qpdf --check`.
- Honest failure when impossible, reporting the smallest size reached.
- Clean up all temporary files on success, failure, or error.
"""

from __future__ import annotations

import errno
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from smol.config import load_config
from smol.core.paths import output_path
from smol.core.result import Result
from smol.core.size import format_size

# Ghostscript downsampling ladder per PLAN.md section 7.2
# Ladder: DPI 200 -> 150 -> 120 -> 96 -> 72 -> 60
# JPEG quality ~80 -> 50
# In PostScript Distiller parameters: QFactor ~= (100 - quality) / 50.0
PDF_RUNGS: list[dict[str, Any]] = [
    {"dpi": 200, "quality": 80, "qfactor": 0.40},
    {"dpi": 150, "quality": 75, "qfactor": 0.50},
    {"dpi": 120, "quality": 70, "qfactor": 0.60},
    {"dpi": 96, "quality": 65, "qfactor": 0.70},
    {"dpi": 72, "quality": 55, "qfactor": 0.90},
    {"dpi": 60, "quality": 50, "qfactor": 1.00},
]

# Explicit safety limits to guard against resource exhaustion / DoS
MAX_PDF_SIZE_BYTES: int = 500_000_000  # 500 MB
MAX_PDF_PAGES: int = 2_000  # 2,000 pages


def shrink_pdf(
    src: str | Path,
    target_bytes: int,
    options: dict[str, Any] | None = None,
) -> Result:
    """Shrink a PDF file to at most target_bytes.

    Pipeline:
    1. Check tools (gs, qpdf) and source validity.
    2. Check if already <= target_bytes (no-op unless force_reencode).
    3. Step down the Ghostscript downsampling ladder:
       DPI 200 -> 150 -> 120 -> 96 -> 72 -> 60, JPEG quality 80 -> 50.
    4. Apply qpdf object-stream optimisation.
    5. Stop at the first rung that fits <= target_bytes.
    6. Verify with `qpdf --check`.
    7. Atomically write to destination and clean up all temporary files.
    """
    src_path = Path(src)
    if not src_path.exists():
        return Result(ok=False, error=f"File not found: {src_path}")

    orig_bytes = src_path.stat().st_size
    if orig_bytes == 0:
        return Result(ok=False, original_bytes=0, error="File is empty (0 bytes).")

    if orig_bytes > MAX_PDF_SIZE_BYTES:
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            error=(
                f"PDF file size ({format_size(orig_bytes)}) exceeds safety limit "
                f"({format_size(MAX_PDF_SIZE_BYTES)})."
            ),
        )

    # Verify basic PDF header
    try:
        with open(src_path, "rb") as fp:
            header = fp.read(1024)
        if b"%PDF-" not in header:
            return Result(
                ok=False,
                original_bytes=orig_bytes,
                error=f"Not a valid PDF file: {src_path.name}",
            )
    except OSError as exc:
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            error=f"Failed to read source file: {exc}",
        )

    # Check external tools
    gs_bin = shutil.which("gs")
    if not gs_bin:
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            error=(
                "Ghostscript (gs) is required to shrink PDF files. "
                "Install it with: sudo apt install ghostscript"
            ),
        )

    qpdf_bin = shutil.which("qpdf")
    if not qpdf_bin:
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            error=(
                "qpdf is required to optimize and verify PDF files. "
                "Install it with: sudo apt install qpdf"
            ),
        )

    # Enforce maximum page count limit
    try:
        res_pages = subprocess.run(
            [qpdf_bin, "--show-npages", "--", str(src_path.resolve())],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if res_pages.returncode == 0 and res_pages.stdout.strip().isdigit():
            page_count = int(res_pages.stdout.strip())
            if page_count > MAX_PDF_PAGES:
                return Result(
                    ok=False,
                    original_bytes=orig_bytes,
                    error=(
                        f"PDF page count ({page_count:,}) exceeds safety limit of "
                        f"{MAX_PDF_PAGES:,} pages."
                    ),
                )
    except (subprocess.SubprocessError, OSError):
        pass

    opts = options or {}
    cfg = load_config(opts.get("config_path"))
    force_reencode = bool(opts.get("force_reencode", False) or opts.get("force", False))
    dry_run = bool(opts.get("dry_run", False))
    out_dir = opts.get("out_dir")
    if out_dir is None and cfg.output_mode == "fixed folder" and cfg.output_folder:
        out_dir = cfg.output_folder
    pattern = opts.get("pattern")
    config_path = opts.get("config_path")

    step_callback: Callable[[float, int], None] | None = opts.get(
        "step_callback"
    ) or opts.get("progress_callback")

    # If file is already small enough, leave untouched unless force_reencode
    if not force_reencode and orig_bytes <= target_bytes:
        return Result(
            ok=True,
            output_path=None,
            original_bytes=orig_bytes,
            final_bytes=orig_bytes,
            steps=0,
            warning=(
                f"File is already {orig_bytes:,} bytes, which is <= target of "
                f"{target_bytes:,} bytes. Untouched."
            ),
        )

    best_candidate_path: Path | None = None
    best_candidate_size: int = orig_bytes
    best_rung: dict[str, Any] | None = None
    smallest_bytes_seen: int = orig_bytes
    step_count = 0
    total_rungs = len(PDF_RUNGS)

    # Use a temporary directory for all scratch and intermediate conversions
    with tempfile.TemporaryDirectory(prefix="smol_pdf_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)

        for rung in PDF_RUNGS:
            step_count += 1
            dpi = rung["dpi"]
            qfactor = rung["qfactor"]

            gs_out = tmp_dir / f"step_{step_count}_gs.pdf"
            qpdf_out = tmp_dir / f"step_{step_count}_qpdf.pdf"

            # 1. Ghostscript downsampling and recompression
            # ALWAYS pass list arguments, NEVER a shell string
            gs_cmd = [
                gs_bin,
                "-dSAFER",
                "-dNOPAUSE",
                "-dBATCH",
                "-dQUIET",
                "-sDEVICE=pdfwrite",
                "-dCompatibilityLevel=1.4",
                f"-sOutputFile={gs_out}",
                "-dAutoFilterColorImages=false",
                "-dColorImageFilter=/DCTEncode",
                "-dDownsampleColorImages=true",
                f"-dColorImageResolution={dpi}",
                "-dColorImageDownsampleType=/Bicubic",
                "-dColorImageDownsampleThreshold=1.0",
                "-dAutoFilterGrayImages=false",
                "-dGrayImageFilter=/DCTEncode",
                "-dDownsampleGrayImages=true",
                f"-dGrayImageResolution={dpi}",
                "-dGrayImageDownsampleType=/Bicubic",
                "-dGrayImageDownsampleThreshold=1.0",
                "-dDownsampleMonoImages=true",
                f"-dMonoImageResolution={dpi}",
                "-dMonoImageDownsampleThreshold=1.0",
                "-c",
                (
                    f"<< /ColorImageDict << /QFactor {qfactor:.2f} >> "
                    f"/GrayImageDict << /QFactor {qfactor:.2f} >> >> setdistillerparams"
                ),
                "-f",
                str(src_path.resolve()),
            ]

            try:
                res_gs = subprocess.run(
                    gs_cmd, check=False, capture_output=True, text=True
                )
            except OSError as exc:
                return Result(
                    ok=False,
                    original_bytes=orig_bytes,
                    steps=step_count,
                    error=f"Failed to execute Ghostscript: {exc}",
                )

            if res_gs.returncode != 0 or not gs_out.exists():
                # GS step failed to produce output; skip rung
                continue

            current_candidate = gs_out

            # 2. qpdf object-stream optimisation
            qpdf_cmd = [
                qpdf_bin,
                "--object-streams=generate",
                "--",
                str(gs_out),
                str(qpdf_out),
            ]
            try:
                res_qpdf = subprocess.run(
                    qpdf_cmd, check=False, capture_output=True, text=True
                )
                if res_qpdf.returncode == 0 and qpdf_out.exists():
                    current_candidate = qpdf_out
            except OSError:
                # If qpdf optimization fails, fallback to gs output
                pass

            cand_size = current_candidate.stat().st_size
            if cand_size < smallest_bytes_seen or smallest_bytes_seen == orig_bytes:
                smallest_bytes_seen = cand_size

            if step_callback is not None:
                fraction = step_count / total_rungs
                step_callback(fraction, cand_size)

            # Check if this rung satisfies target_bytes
            if cand_size <= target_bytes:
                # 3. Verify syntactic integrity with qpdf --check
                check_cmd = [
                    qpdf_bin,
                    "--check",
                    "--warning-exit-0",
                    "--",
                    str(current_candidate),
                ]
                res_check = subprocess.run(
                    check_cmd, check=False, capture_output=True, text=True
                )
                if res_check.returncode == 0:
                    best_candidate_path = current_candidate
                    best_candidate_size = cand_size
                    best_rung = rung
                    # Stop at the first rung whose output fits!
                    break

        if best_candidate_path is None or best_rung is None:
            # Ladder exhausted without reaching target
            if smallest_bytes_seen >= orig_bytes:
                err_msg = (
                    f"PDF cannot be shrunk further (smallest achievable is "
                    f"~{format_size(smallest_bytes_seen)}); "
                    "text-only or already compressed."
                )
            else:
                min_dpi = PDF_RUNGS[-1]["dpi"]
                err_msg = (
                    f"Smallest I can make this is ~{format_size(smallest_bytes_seen)} "
                    f"at {min_dpi} DPI; try a larger target."
                )

            return Result(
                ok=False,
                original_bytes=orig_bytes,
                final_bytes=smallest_bytes_seen,
                steps=step_count,
                error=err_msg,
            )

        # Successful shrink fitting target_bytes
        if dry_run:
            return Result(
                ok=True,
                output_path=None,
                original_bytes=orig_bytes,
                final_bytes=best_candidate_size,
                quality=best_rung["quality"],
                steps=step_count,
                size_source="estimate",
            )

        # Compute output destination path
        dest_path = output_path(
            src_path,
            target_bytes,
            ext=".pdf",
            out_dir=out_dir,
            pattern=pattern,
            config_path=config_path,
        )

        dest_dir = dest_path.parent
        if not dest_dir.exists():
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return Result(
                    ok=False,
                    original_bytes=orig_bytes,
                    error=f"Cannot create destination directory '{dest_dir}': {exc}",
                )

        if not os.access(dest_dir, os.W_OK):
            return Result(
                ok=False,
                original_bytes=orig_bytes,
                error=f"Destination directory is not writable: {dest_dir}",
            )

        # Atomic write in the destination directory
        temp_dest: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=dest_dir,
                prefix=f".smol_{dest_path.stem}_",
                suffix=".tmp",
                delete=False,
            ) as tf:
                temp_dest = Path(tf.name)
                # Ensure final file has normal permissions respecting current umask
                current_umask = os.umask(0)
                os.umask(current_umask)
                try:
                    os.fchmod(tf.fileno(), 0o666 & ~current_umask)
                except (AttributeError, OSError):
                    pass
                shutil.copyfile(best_candidate_path, temp_dest)

            os.replace(temp_dest, dest_path)
            temp_dest = None
        except OSError as exc:
            if temp_dest is not None and temp_dest.exists():
                try:
                    temp_dest.unlink(missing_ok=True)
                except OSError:
                    pass
            if getattr(exc, "errno", None) == errno.ENOSPC:
                err_msg = (
                    "Disk is full (no space left on device); cannot write output file."
                )
            else:
                err_msg = f"Failed to write output file: {exc}"
            return Result(
                ok=False,
                original_bytes=orig_bytes,
                error=err_msg,
            )
        except BaseException:
            if temp_dest is not None and temp_dest.exists():
                try:
                    temp_dest.unlink(missing_ok=True)
                except OSError:
                    pass
            raise

        # Post-write disk verification: size must be <= target_bytes
        actual_size = dest_path.stat().st_size
        if actual_size > target_bytes:
            try:
                dest_path.unlink()
            except OSError:
                pass
            return Result(
                ok=False,
                original_bytes=orig_bytes,
                error=(
                    f"Post-write verification failed: output ({actual_size:,} bytes) "
                    f"exceeds target ({target_bytes:,} bytes)."
                ),
            )

        return Result(
            ok=True,
            output_path=dest_path,
            original_bytes=orig_bytes,
            final_bytes=actual_size,
            quality=best_rung["quality"],
            steps=step_count,
        )
