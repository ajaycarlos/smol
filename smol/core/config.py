"""Configuration manager for smol.

Handles reading and writing user configuration to ~/.config/smol/config.toml
(or $XDG_CONFIG_HOME/smol/config.toml) with atomic writes and safe defaults.
"""

from __future__ import annotations

import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "custom_sizes": [],
}

DEFAULT_DAEMON_CONFIG: dict[str, Any] = {
    "trigger_key": "Super",
    "sizes": [20_000, 50_000, 100_000, 200_000, 500_000, 1_000_000, 2_000_000],
    "custom_sizes": [],
}


def get_config_path(override_path: Path | str | None = None) -> Path:
    """Return the absolute path to the smol configuration file."""
    if override_path is not None:
        return Path(override_path)

    env_config = os.environ.get("SMOL_CONFIG_PATH")
    if env_config:
        return Path(env_config)

    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        base = Path(xdg_config)
    else:
        base = Path.home() / ".config"

    return base / "smol" / "config.toml"


def get_daemon_config(config_path: Path | str | None = None) -> dict[str, Any]:
    """Load daemon configuration with defaults for trigger_key and sizes."""
    cfg = load_config(config_path)
    result = dict(DEFAULT_DAEMON_CONFIG)
    if "trigger_key" in cfg and isinstance(cfg["trigger_key"], str):
        result["trigger_key"] = cfg["trigger_key"]
    if "sizes" in cfg and isinstance(cfg["sizes"], list):
        parsed_sizes = [int(s) for s in cfg["sizes"] if isinstance(s, (int, float))]
        if parsed_sizes:
            result["sizes"] = parsed_sizes
    if "custom_sizes" in cfg and isinstance(cfg["custom_sizes"], list):
        result["custom_sizes"] = cfg["custom_sizes"]
    return result


def load_config(config_path: Path | str | None = None) -> dict[str, Any]:
    """Load configuration from disk.

    Returns default configuration if the file does not exist or contains invalid TOML.
    """
    path = get_config_path(config_path)
    if not path.is_file():
        return dict(DEFAULT_CONFIG)

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
            if not isinstance(data, dict):
                return dict(DEFAULT_CONFIG)
            if "custom_sizes" not in data or not isinstance(data["custom_sizes"], list):
                data["custom_sizes"] = []
            return data
    except (tomllib.TOMLDecodeError, OSError):
        return dict(DEFAULT_CONFIG)


def _serialize_toml(config: dict[str, Any]) -> str:
    """Serialize a simple smol configuration dictionary to TOML format."""
    lines: list[str] = ["# smol configuration", ""]
    for key, value in config.items():
        if isinstance(value, list):
            items_str = ", ".join(repr(v) for v in value)
            lines.append(f"{key} = [{items_str}]")
        elif isinstance(value, (str, int, float, bool)):
            lines.append(f"{key} = {value!r}")
    lines.append("")
    return "\n".join(lines)


def save_config(config: dict[str, Any], config_path: Path | str | None = None) -> None:
    """Save configuration to disk atomically."""
    path = get_config_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    content = _serialize_toml(config)

    # Atomic write via temporary file in the same directory
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, encoding="utf-8"
    ) as tf:
        tf.write(content)
        temp_path = Path(tf.name)

    temp_path.replace(path)


def add_custom_size(
    target_bytes: int, config_path: Path | str | None = None
) -> list[int]:
    """Add a custom target size in bytes, keeping up to the last 3 unique values."""
    config = load_config(config_path)
    raw_sizes = config.get("custom_sizes", [])
    sizes = [int(s) for s in raw_sizes if isinstance(s, (int, float))]

    if target_bytes in sizes:
        sizes.remove(target_bytes)
    sizes.append(target_bytes)

    # Keep only the last 3 sizes
    sizes = sizes[-3:]
    config["custom_sizes"] = sizes
    save_config(config, config_path)
    return sizes


def get_custom_sizes(config_path: Path | str | None = None) -> list[int]:
    """Retrieve up to the last 3 remembered custom sizes in bytes."""
    config = load_config(config_path)
    raw_sizes = config.get("custom_sizes", [])
    sizes = [int(s) for s in raw_sizes if isinstance(s, (int, float))]
    return sizes[-3:]
