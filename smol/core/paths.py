from pathlib import Path

from smol.core.size import format_size, parse_size


def output_path(
    src: str | Path,
    target_bytes: int | str,
    ext: str | None = None,
    out_dir: str | Path | None = None,
) -> Path:
    """Generate a destination output path next to the source file or in out_dir.

    Pattern: `<name>_<size>.<ext>`
    On collision: `<name>_<size>-1.<ext>`, `<name>_<size>-2.<ext>`, etc.
    Never overwrites the original or any existing file.
    """
    src_path = Path(src)
    if isinstance(target_bytes, (int, float)):
        size_bytes = int(target_bytes)
    else:
        size_bytes = parse_size(target_bytes)

    size_label = format_size(size_bytes)
    parent = Path(out_dir) if out_dir is not None else src_path.parent
    stem = src_path.stem
    if ext is not None:
        suffix = ext if ext.startswith(".") else f".{ext}"
    else:
        suffix = src_path.suffix

    candidate = parent / f"{stem}_{size_label}{suffix}"
    if not candidate.exists():
        return candidate

    collision_idx = 1
    while True:
        candidate = parent / f"{stem}_{size_label}-{collision_idx}{suffix}"
        if not candidate.exists():
            return candidate
        collision_idx += 1
