import re
from pathlib import Path

from smol.config import load_config
from smol.core.size import format_size, parse_size


def sanitize_filename_component(name: str) -> str:
    """Sanitize a filename component.

    Removes control chars, newlines, and path separators, and strips whole '..'
    or '.' path components while preserving legitimate dots in filenames
    (e.g., 'holiday..photo.jpg', 'photo.final.jpg').
    """
    # Replace newlines, control characters, null bytes
    sanitized = re.sub(r"[\r\n\x00-\x1f]", "_", name)

    # Split by path separators to inspect components
    parts = re.split(r"[/\\]+", sanitized)
    clean_parts: list[str] = []
    for part in parts:
        part = part.strip()
        # Drop whole traversal components
        if part in ("..", "."):
            continue
        # Strip leading dots if they would create hidden file / traversal
        while part.startswith("."):
            part = part[1:]
        part = part.strip()
        if part and part not in ("..", "."):
            clean_parts.append(part)

    sanitized = "_".join(clean_parts) if clean_parts else ""
    sanitized = sanitized.strip()
    return sanitized or "file"


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
    Guarantees no path traversal or directory escaping.
    Guarantees no following or overwriting of existing or dangling symlinks.
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

    # Sanitize stem
    stem = sanitize_filename_component(src_path.stem)

    if ext is not None:
        raw_ext = ext if ext.startswith(".") else f".{ext}"
        suffix = "." + sanitize_filename_component(raw_ext.lstrip("."))
    elif src_path.suffix:
        clean_ext = sanitize_filename_component(src_path.suffix.lstrip("."))
        suffix = f".{clean_ext}"
    else:
        suffix = ""

    effective_pattern = (
        pattern
        if pattern is not None
        else (cfg.naming_pattern if cfg is not None else "{name}_{size}{ext}")
    )

    try:
        raw_filename = effective_pattern.format(name=stem, size=size_label, ext=suffix)
    except (KeyError, ValueError):
        # Fallback to standard pattern if custom pattern contains invalid keys
        raw_filename = f"{stem}_{size_label}{suffix}"

    # Enforce strictly the final filename component (no slashes, no traversal)
    clean_name = Path(raw_filename).name
    # Strip any remaining control chars or path separators
    clean_name = re.sub(r"[\r\n\x00-\x1f/\\]", "_", clean_name).strip()
    while clean_name.startswith("."):
        clean_name = clean_name[1:].strip()
    if not clean_name or clean_name in (".", ".."):
        clean_name = f"{stem}_{size_label}{suffix}"

    candidate = parent / clean_name
    if not (candidate.exists() or candidate.is_symlink()):
        return candidate

    collision_idx = 1
    cand_stem = candidate.stem
    cand_suffix = candidate.suffix
    while True:
        candidate = parent / f"{cand_stem}-{collision_idx}{cand_suffix}"
        if not (candidate.exists() or candidate.is_symlink()):
            return candidate
        collision_idx += 1
