"""Core engine router dispatching files to format-specific shrink engines.

Pipeline:
- Images (JPEG, PNG, WebP, HEIC, AVIF) -> shrink_image
- PDFs (.pdf) -> shrink_pdf
- Videos (.mp4, .mov, etc.) -> future milestone (M8) honest message
- Other formats -> honest unsupported format failure
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from smol.core.image import shrink_image
from smol.core.pdf import shrink_pdf
from smol.core.result import Result

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".heic",
    ".heif",
    ".avif",
}

PDF_EXTENSIONS = {
    ".pdf",
}

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".avi",
}


def detect_file_type(src: str | Path) -> str:
    """Detect whether a file is an image, pdf, video, or unsupported.

    Returns:
        'image', 'pdf', 'video', or 'unsupported'
    """
    path = Path(src)
    ext = path.suffix.lower()

    if ext in PDF_EXTENSIONS:
        return "pdf"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"

    # If extension is missing or unrecognized, inspect file header if file exists
    if path.is_file():
        try:
            with open(path, "rb") as fp:
                head = fp.read(1024)
            if head.startswith(b"%PDF-") or b"%PDF-" in head[:1024]:
                return "pdf"
        except OSError:
            pass

    return "unsupported"


def shrink_file(
    src: str | Path,
    target_bytes: int,
    options: dict[str, Any] | None = None,
) -> Result:
    """Route file shrinking to appropriate engine based on file type.

    Args:
        src: Path to the input file.
        target_bytes: Maximum allowed byte size of output.
        options: Engine options (e.g. step_callback, dry_run, out_dir, etc.).

    Returns:
        Result object with ok, output_path, sizes, steps, warning/error.
    """
    src_path = Path(src)
    if not src_path.exists():
        return Result(ok=False, error=f"File not found: {src_path}")

    orig_bytes = src_path.stat().st_size
    kind = detect_file_type(src_path)

    if kind == "image":
        return shrink_image(src_path, target_bytes, options=options)
    elif kind == "pdf":
        return shrink_pdf(src_path, target_bytes, options=options)
    elif kind == "video":
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            error="Video compression engine coming in future milestone (M8); skipped.",
        )
    else:
        ext_str = f"'{src_path.suffix}'" if src_path.suffix else f"'{src_path.name}'"
        return Result(
            ok=False,
            original_bytes=orig_bytes,
            error=(
                f"Unsupported file format {ext_str}; "
                "only images and PDFs are currently supported."
            ),
        )

