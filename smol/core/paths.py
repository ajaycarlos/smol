import re
from pathlib import Path

from smol.config import load_config
from smol.core.size import format_size, parse_size


def sanitize_filename_component(name: str) -> str:
    """Sanitize a filename component.

    Removes control chars, newlines, and path separators.
    """
    # Replace newlines, control characters, null bytes, and path separators
    sanitized = re.sub(r"[\r\n\x00-\x1f/\\]", "_", name)
    # Remove leading dots to prevent hidden files or traversal artifacts
    while sanitized.startswith("."):
        sanitized = sanitized[1:]
    # Remove any traversal sequences like '..'
    sanitized = re.sub(r"\.\.+", "_", sanitized)
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
    # Strip any remaining control chars, path separators, or traversal artifacts
    clean_name = re.sub(r"[\r\n\x00-\x1f/\\]", "_", clean_name)
    clean_name = re.sub(r"\.\.+", "_", clean_name).strip()
    if not clean_name or clean_name in (".", ".."):
        clean_name = f"{stem}_{size_label}{suffix}"

    candidate = parent / clean_name
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
