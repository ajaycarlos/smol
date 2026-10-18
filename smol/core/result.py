from dataclasses import dataclass
from pathlib import Path


@dataclass
class Result:
    """Core outcome object for file shrinking operations.

    Promise: ok, output_path, original_bytes, final_bytes, width, height,
    quality, steps, warning, error.
    """

    ok: bool
    output_path: Path | None = None
    original_bytes: int = 0
    final_bytes: int = 0
    width: int | None = None
    height: int | None = None
    scale: float | None = None
    quality: int | None = None
    steps: int = 0
    warning: str | None = None
    error: str | None = None
