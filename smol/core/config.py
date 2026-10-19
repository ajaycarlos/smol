"""Core configuration facade for smol.

Re-exports and forwards configuration management to smol.config to ensure
a single canonical source of truth for all smol settings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from smol.config import (
    SmolConfig,
    get_config_path,
)
from smol.config import (
    load_config as _load_config_canonical,
)
from smol.config import (
    save_config as _save_config_canonical,
)

DEFAULT_CONFIG: dict[str, Any] = {
    "custom_sizes": [],
    "reduce_motion": False,
}


def load_config(config_path: Path | str | None = None) -> dict[str, Any]:
    """Load configuration from disk as a dictionary for core utilities."""
    path = get_config_path(config_path)
    if not path.is_file():
        return dict(DEFAULT_CONFIG)

    try:
        cfg = _load_config_canonical(config_path)
        return {
            "custom_sizes": list(cfg.custom_sizes),
            "reduce_motion": bool(cfg.reduce_motion),
        }
    except (OSError, ValueError, TypeError):
        return dict(DEFAULT_CONFIG)


def save_config(
    config: SmolConfig | dict[str, Any], config_path: Path | str | None = None
) -> None:
    """Save configuration to disk atomically."""
    _save_config_canonical(config, config_path)


def get_daemon_config(config_path: Path | str | None = None) -> dict[str, Any]:
    """Load daemon configuration with all active settings."""
    cfg = _load_config_canonical(config_path)
    return cfg.to_dict()


def add_custom_size(
    target_bytes: int, config_path: Path | str | None = None
) -> list[int]:
    """Add a custom target size in bytes, keeping up to the last 3 unique values."""
    cfg = _load_config_canonical(config_path)
    sizes = list(cfg.custom_sizes)

    if target_bytes in sizes:
        sizes.remove(target_bytes)
    sizes.append(target_bytes)

    sizes = sizes[-3:]
    cfg.custom_sizes = sizes
    _save_config_canonical(cfg, config_path)
    return sizes


def get_custom_sizes(config_path: Path | str | None = None) -> list[int]:
    """Retrieve up to the last 3 remembered custom sizes in bytes."""
    cfg = _load_config_canonical(config_path)
    return list(cfg.custom_sizes)


def get_reduce_motion(config_path: Path | str | None = None) -> bool:
    """Retrieve reduce_motion setting from config."""
    cfg = _load_config_canonical(config_path)
    return bool(cfg.reduce_motion)


def set_reduce_motion(enabled: bool, config_path: Path | str | None = None) -> None:
    """Update reduce_motion setting in config."""
    cfg = _load_config_canonical(config_path)
    cfg.reduce_motion = bool(enabled)
    _save_config_canonical(cfg, config_path)
