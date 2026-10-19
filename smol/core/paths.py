from __future__ import annotations

from pathlib import Path

from smol.config import load_config
from smol.core.size import format_size, parse_size


def output_path(
    src: str | Path,
    target_bytes: int | str,
    ext: str | None = None,
    out_dir: str | Path | None = None,
    pattern: str | None = None,
    config_path: Path | str | None = None,
) -> Path:
    """Generate a destination output path next to the source file or in out_dir.

    Uses `naming_pattern` and `output_folder` from smol.config if not explicitly
    provided. Default pattern: `{name}_{size}{ext}`
    On collision: `<formatted_name>-1.<ext>`, `<formatted_name>-2.<ext>`, etc.
    Never overwrites the original or any existing file.
    """
    src_path = Path(src)
    if isinstance(target_bytes, (int, float)):
        size_bytes = int(target_bytes)
    else:
        size_bytes = parse_size(target_bytes)

    size_label = format_size(size_bytes)
    cfg = None
    if out_dir is None or pattern is None:
        cfg = load_config(config_path)

    if out_dir is not None:
        parent = Path(out_dir)
    elif cfg is not None and cfg.output_mode == "fixed folder" and cfg.output_folder:
        parent = Path(cfg.output_folder)
    else:
        parent = src_path.parent

    stem = src_path.stem
    if ext is not None:
        suffix = ext if ext.startswith(".") else f".{ext}"
    else:
        suffix = src_path.suffix

    effective_pattern = (
        pattern
        if pattern is not None
        else (cfg.naming_pattern if cfg is not None else "{name}_{size}{ext}")
    )

    try:
        filename = effective_pattern.format(name=stem, size=size_label, ext=suffix)
    except KeyError:
        # Fallback to standard pattern if custom pattern contains invalid keys
        filename = f"{stem}_{size_label}{suffix}"

    candidate = parent / filename
    if not candidate.exists():
        return candidate

    collision_idx = 1
    cand_stem = candidate.stem
    cand_suffix = candidate.suffix
    while True:
        candidate = parent / f"{cand_stem}-{collision_idx}{cand_suffix}"
        if not candidate.exists():
            return candidate
        collision_idx += 1
