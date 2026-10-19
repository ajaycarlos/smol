"""Configuration manager for smol.

Handles reading and writing user configuration to ~/.config/smol/config.toml
(or $XDG_CONFIG_HOME/smol/config.toml) with atomic writes, schema validation,
and safe defaults.
"""

from __future__ import annotations

import logging
import os
import tempfile
import tomllib
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, Any] = {
    "trigger_key": "Super",
    "sizes": [20_000, 50_000, 100_000, 200_000, 500_000, 1_000_000, 2_000_000],
    "output_mode": "next to original",
    "output_folder": "",
    "naming_pattern": "{name}_{size}{ext}",
    "keep_format": True,
    "allow_convert": False,
    "strip_metadata": True,
    "min_side": 200,
    "reduce_motion": False,
    "theme": "dark",
    "autostart": False,
    "custom_sizes": [],
}

VALID_OUTPUT_MODES = {
    "next to original": "next to original",
    "next_to_original": "next to original",
    "fixed folder": "fixed folder",
    "fixed_folder": "fixed folder",
}

VALID_THEMES = {"dark", "light", "system"}


@dataclass
class SmolConfig:
    """Smol configuration dataclass with dictionary-like access."""

    trigger_key: str = "Super"
    sizes: list[int] = field(
        default_factory=lambda: [
            20_000,
            50_000,
            100_000,
            200_000,
            500_000,
            1_000_000,
            2_000_000,
        ]
    )
    output_mode: str = "next to original"
    output_folder: str = ""
    naming_pattern: str = "{name}_{size}{ext}"
    keep_format: bool = True
    allow_convert: bool = False
    strip_metadata: bool = True
    min_side: int = 200
    reduce_motion: bool = False
    theme: str = "dark"
    autostart: bool = False
    custom_sizes: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary."""
        return asdict(self)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)


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


def _warn_and_fallback(key: str, value: Any, default: Any, reason: str = "") -> None:
    msg = (
        f"Invalid config value for '{key}': {value!r}. "
        f"{reason}Falling back to default: {default!r}."
    )
    logger.warning(msg)
    warnings.warn(msg, UserWarning, stacklevel=3)


def validate_config_dict(raw_data: dict[str, Any]) -> dict[str, Any]:
    """Validate dictionary of configuration values and fall back on bad values."""
    validated: dict[str, Any] = dict(DEFAULT_CONFIG)

    # 1. trigger_key
    if "trigger_key" in raw_data:
        val = raw_data["trigger_key"]
        if isinstance(val, str) and val.strip():
            validated["trigger_key"] = val.strip()
        else:
            _warn_and_fallback(
                "trigger_key",
                val,
                DEFAULT_CONFIG["trigger_key"],
                "Must be a non-empty string. ",
            )

    # 2. sizes
    if "sizes" in raw_data:
        val = raw_data["sizes"]
        if (
            isinstance(val, list)
            and len(val) > 0
            and all(
                isinstance(s, (int, float)) and int(s) > 0 and not isinstance(s, bool)
                for s in val
            )
        ):
            validated["sizes"] = [int(s) for s in val]
        else:
            _warn_and_fallback(
                "sizes",
                val,
                DEFAULT_CONFIG["sizes"],
                "Must be a list of positive integers. ",
            )

    # 3. output_mode
    if "output_mode" in raw_data:
        val = raw_data["output_mode"]
        if isinstance(val, str) and val.strip().lower() in VALID_OUTPUT_MODES:
            validated["output_mode"] = VALID_OUTPUT_MODES[val.strip().lower()]
        else:
            _warn_and_fallback(
                "output_mode",
                val,
                DEFAULT_CONFIG["output_mode"],
                f"Must be one of {list(VALID_OUTPUT_MODES.keys())}. ",
            )

    # 4. output_folder
    if "output_folder" in raw_data:
        val = raw_data["output_folder"]
        if isinstance(val, str):
            validated["output_folder"] = val
        else:
            _warn_and_fallback(
                "output_folder",
                val,
                DEFAULT_CONFIG["output_folder"],
                "Must be a string. ",
            )

    # 5. naming_pattern
    if "naming_pattern" in raw_data:
        val = raw_data["naming_pattern"]
        if isinstance(val, str) and val.strip():
            validated["naming_pattern"] = val
        else:
            _warn_and_fallback(
                "naming_pattern",
                val,
                DEFAULT_CONFIG["naming_pattern"],
                "Must be a non-empty pattern string. ",
            )

    # 6. keep_format
    if "keep_format" in raw_data:
        val = raw_data["keep_format"]
        if isinstance(val, bool):
            validated["keep_format"] = val
        else:
            _warn_and_fallback(
                "keep_format", val, DEFAULT_CONFIG["keep_format"], "Must be a boolean. "
            )

    # 7. allow_convert
    if "allow_convert" in raw_data:
        val = raw_data["allow_convert"]
        if isinstance(val, bool):
            validated["allow_convert"] = val
        else:
            _warn_and_fallback(
                "allow_convert",
                val,
                DEFAULT_CONFIG["allow_convert"],
                "Must be a boolean. ",
            )

    # 8. strip_metadata
    if "strip_metadata" in raw_data:
        val = raw_data["strip_metadata"]
        if isinstance(val, bool):
            validated["strip_metadata"] = val
        else:
            _warn_and_fallback(
                "strip_metadata",
                val,
                DEFAULT_CONFIG["strip_metadata"],
                "Must be a boolean. ",
            )

    # 9. min_side
    if "min_side" in raw_data:
        val = raw_data["min_side"]
        if isinstance(val, int) and not isinstance(val, bool) and val >= 1:
            validated["min_side"] = val
        else:
            _warn_and_fallback(
                "min_side",
                val,
                DEFAULT_CONFIG["min_side"],
                "Must be a positive integer greater than or equal to 1. ",
            )

    # 10. reduce_motion
    if "reduce_motion" in raw_data:
        val = raw_data["reduce_motion"]
        if isinstance(val, bool):
            validated["reduce_motion"] = val
        else:
            _warn_and_fallback(
                "reduce_motion",
                val,
                DEFAULT_CONFIG["reduce_motion"],
                "Must be a boolean. ",
            )

    # 11. theme
    if "theme" in raw_data:
        val = raw_data["theme"]
        if isinstance(val, str) and val.strip().lower() in VALID_THEMES:
            validated["theme"] = val.strip().lower()
        else:
            _warn_and_fallback(
                "theme",
                val,
                DEFAULT_CONFIG["theme"],
                f"Must be one of {sorted(VALID_THEMES)}. ",
            )

    # 12. autostart
    if "autostart" in raw_data:
        val = raw_data["autostart"]
        if isinstance(val, bool):
            validated["autostart"] = val
        else:
            _warn_and_fallback(
                "autostart", val, DEFAULT_CONFIG["autostart"], "Must be a boolean. "
            )

    # 13. custom_sizes
    if "custom_sizes" in raw_data:
        val = raw_data["custom_sizes"]
        if isinstance(val, list):
            validated["custom_sizes"] = [
                int(s)
                for s in val
                if isinstance(s, (int, float))
                and int(s) > 0
                and not isinstance(s, bool)
            ][-3:]
        else:
            _warn_and_fallback(
                "custom_sizes", val, [], "Must be a list of integer byte sizes. "
            )

    return validated


def load_config(config_path: Path | str | None = None) -> SmolConfig:
    """Load configuration from disk.

    Returns default configuration if the file does not exist, or falls back to
    defaults with warnings if corrupted or containing invalid fields. Never crashes.
    """
    path = get_config_path(config_path)
    if not path.is_file():
        return SmolConfig()

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as err:
        msg = (
            f"Failed to read or parse config at {path}: {err}. "
            "Falling back to default configuration."
        )
        logger.warning(msg)
        warnings.warn(msg, UserWarning, stacklevel=2)
        return SmolConfig()

    if not isinstance(data, dict):
        msg = (
            f"Config file at {path} must contain a TOML table/key-value mapping. "
            "Falling back to default configuration."
        )
        logger.warning(msg)
        warnings.warn(msg, UserWarning, stacklevel=2)
        return SmolConfig()

    valid_dict = validate_config_dict(data)
    return SmolConfig(**valid_dict)


def save_config(
    config: SmolConfig | dict[str, Any],
    config_path: Path | str | None = None,
) -> None:
    """Save configuration to disk atomically using tomli-w."""
    path = get_config_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(config, SmolConfig):
        raw_dict = config.to_dict()
    elif isinstance(config, dict):
        raw_dict = dict(config)
    else:
        raise TypeError(f"Expected SmolConfig or dict, got {type(config).__name__}")

    # Validate and clean before writing
    clean_dict = validate_config_dict(raw_dict)

    # Format using tomli_w
    content = tomli_w.dumps(clean_dict)

    # Atomic write via temporary file in the same directory
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as tf:
        tf.write(content.encode("utf-8"))
        temp_path = Path(tf.name)

    temp_path.replace(path)
