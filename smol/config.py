"""Configuration manager for smol.

Handles reading and writing user configuration to config.toml
in the platform configuration directory with atomic writes, schema validation,
schema versioning (v1), migrations, and safe defaults.
"""

from __future__ import annotations

import logging
import math
import os
import re
import shutil
import tempfile
import tomllib
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

logger = logging.getLogger(__name__)


def _is_valid_size_int(val: Any, max_val: int = 100_000_000_000) -> bool:
    """Check if value is a valid positive integer under max_val (default 100 GB)."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return False
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return False
    try:
        int_val = int(val)
        return 0 < int_val <= max_val
    except (ValueError, OverflowError):
        return False

DEFAULT_LADDER: list[int] = [
    20_000,
    50_000,
    100_000,
    200_000,
    500_000,
    1_000_000,
    2_000_000,
]

DEFAULT_POOL: list[int] = [
    20_000,
    50_000,
    100_000,
    200_000,
    500_000,
    1_000_000,
    2_000_000,
    5_000_000,
]

DEFAULT_CONFIG: dict[str, Any] = {
    "config_version": 1,
    "trigger_key": "Super",
    "sizes": {
        "ladder": list(DEFAULT_LADDER),
        "pinned": [],
        "recents": [],
    },
    "suggest": {
        "mode": "classic",
        "pool": list(DEFAULT_POOL),
        "max_segments": 6,
    },
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
}

VALID_OUTPUT_MODES = {
    "next to original": "next to original",
    "next_to_original": "next to original",
    "fixed folder": "fixed folder",
    "fixed_folder": "fixed folder",
}

VALID_THEMES = {"dark", "light", "system"}
VALID_SUGGEST_MODES = {"classic", "smart"}

KNOWN_CONFIG_KEYS = {
    "config_version",
    "trigger_key",
    "sizes",
    "suggest",
    "output_mode",
    "output_folder",
    "naming_pattern",
    "keep_format",
    "allow_convert",
    "strip_metadata",
    "min_side",
    "reduce_motion",
    "theme",
    "autostart",
}


@dataclass
class SizesConfig:
    """Configured target size collections: ladder, pinned favourites, and recents."""

    ladder: list[int] = field(default_factory=lambda: list(DEFAULT_LADDER))
    pinned: list[int] = field(default_factory=list)
    recents: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ladder": list(self.ladder),
            "pinned": list(self.pinned),
            "recents": list(self.recents),
        }

    def __iter__(self):
        return iter(self.ladder)

    def __len__(self) -> int:
        return len(self.ladder)

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, str):
            return getattr(self, item)
        return self.ladder[item]

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, list):
            return self.ladder == other
        if isinstance(other, SizesConfig):
            return (
                self.ladder == other.ladder
                and self.pinned == other.pinned
                and self.recents == other.recents
            )
        return False


@dataclass
class SuggestConfig:
    """Size suggestion configuration options."""

    mode: str = "classic"
    pool: list[int] = field(default_factory=lambda: list(DEFAULT_POOL))
    max_segments: int = 6

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "pool": list(self.pool),
            "max_segments": self.max_segments,
        }

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)


@dataclass
class SmolConfig:
    """Smol configuration dataclass with dictionary-like access and schema v1."""

    config_version: int = 1
    trigger_key: str = "Super"
    sizes: SizesConfig = field(default_factory=SizesConfig)
    suggest: SuggestConfig = field(default_factory=SuggestConfig)
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
    _extra_keys: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.sizes, list):
            self.sizes = SizesConfig(ladder=[int(x) for x in self.sizes[:7]])
        elif isinstance(self.sizes, dict):
            ladder = [int(x) for x in self.sizes.get("ladder", [])[:7]] or list(
                DEFAULT_LADDER
            )
            pinned = [int(x) for x in self.sizes.get("pinned", [])[:12]]
            recents = [int(x) for x in self.sizes.get("recents", [])[:5]]
            self.sizes = SizesConfig(ladder=ladder, pinned=pinned, recents=recents)
        elif not isinstance(self.sizes, SizesConfig):
            self.sizes = SizesConfig()

        if isinstance(self.suggest, dict):
            mode = self.suggest.get("mode", "classic")
            if mode not in VALID_SUGGEST_MODES:
                mode = "classic"
            pool = [int(x) for x in self.suggest.get("pool", [])] or list(DEFAULT_POOL)
            max_segments = int(self.suggest.get("max_segments", 6))
            self.suggest = SuggestConfig(
                mode=mode, pool=pool, max_segments=max_segments
            )
        elif not isinstance(self.suggest, SuggestConfig):
            self.suggest = SuggestConfig()

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "sizes":
            if isinstance(value, list):
                if hasattr(self, "sizes") and isinstance(self.sizes, SizesConfig):
                    self.sizes.ladder = [int(x) for x in value[:7]]
                    return
                else:
                    value = SizesConfig(ladder=[int(x) for x in value[:7]])
            elif isinstance(value, dict):
                ladder = [int(x) for x in value.get("ladder", [])[:7]] or list(
                    DEFAULT_LADDER
                )
                pinned = [int(x) for x in value.get("pinned", [])[:12]]
                recents = [int(x) for x in value.get("recents", [])[:5]]
                value = SizesConfig(ladder=ladder, pinned=pinned, recents=recents)
        super().__setattr__(name, value)

    @property
    def custom_sizes(self) -> list[int]:
        """Backward compatibility for custom_sizes pointing to recents."""
        return self.sizes.recents

    @custom_sizes.setter
    def custom_sizes(self, val: list[int]) -> None:
        self.sizes.recents = [int(x) for x in val[:5]]

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary preserving extra keys."""
        d: dict[str, Any] = {
            "config_version": self.config_version,
            "trigger_key": self.trigger_key,
            "sizes": self.sizes.to_dict(),
            "suggest": self.suggest.to_dict(),
            "output_mode": self.output_mode,
            "output_folder": self.output_folder,
            "naming_pattern": self.naming_pattern,
            "keep_format": self.keep_format,
            "allow_convert": self.allow_convert,
            "strip_metadata": self.strip_metadata,
            "min_side": self.min_side,
            "reduce_motion": self.reduce_motion,
            "theme": self.theme,
            "autostart": self.autostart,
        }
        for k, v in self._extra_keys.items():
            if k not in d:
                d[k] = v
        return d

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        if key in self._extra_keys:
            return self._extra_keys[key]
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if hasattr(self, key):
            setattr(self, key, value)
        else:
            self._extra_keys[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        return self._extra_keys.get(key, default)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or key in self._extra_keys


def get_config_path(override_path: Path | str | None = None) -> Path:
    """Return the absolute path to the smol configuration file."""
    if override_path is not None:
        return Path(override_path)

    env_config = os.environ.get("SMOL_CONFIG_PATH")
    if env_config:
        return Path(env_config)

    from smol.platform import config_dir

    return config_dir("smol") / "config.toml"


def _warn_and_fallback(key: str, value: Any, default: Any, reason: str = "") -> None:
    msg = (
        f"Invalid config value for '{key}': {value!r}. "
        f"{reason}Falling back to default: {default!r}."
    )
    logger.warning(msg)
    warnings.warn(msg, UserWarning, stacklevel=3)


def _validate_sizes_table(raw_sizes: Any) -> dict[str, list[int]]:
    """Validate [sizes] table with ladder, pinned, and recents."""
    valid_ladder = list(DEFAULT_LADDER)
    valid_pinned: list[int] = []
    valid_recents: list[int] = []

    if isinstance(raw_sizes, list):
        # Migrated or flat list representation
        if len(raw_sizes) > 0 and all(_is_valid_size_int(s) for s in raw_sizes):
            valid_ladder = [int(s) for s in raw_sizes[:7]]
        else:
            _warn_and_fallback(
                "sizes",
                raw_sizes,
                DEFAULT_LADDER,
                "Must be a list of positive integers. ",
            )
        return {
            "ladder": valid_ladder,
            "pinned": valid_pinned,
            "recents": valid_recents,
        }

    if not isinstance(raw_sizes, dict):
        _warn_and_fallback(
            "sizes",
            raw_sizes,
            DEFAULT_CONFIG["sizes"],
            "Must be a table with ladder, pinned, and recents. ",
        )
        return {
            "ladder": list(DEFAULT_LADDER),
            "pinned": [],
            "recents": [],
        }

    # 1. ladder (max 7)
    if "ladder" in raw_sizes:
        val = raw_sizes["ladder"]
        if (
            isinstance(val, list)
            and len(val) > 0
            and all(_is_valid_size_int(s) for s in val)
        ):
            valid_ladder = [int(s) for s in val[:7]]
        else:
            _warn_and_fallback(
                "sizes.ladder",
                val,
                DEFAULT_LADDER,
                "Must be a list of positive integers (max 7). ",
            )

    # 2. pinned (max 12)
    if "pinned" in raw_sizes:
        val = raw_sizes["pinned"]
        if isinstance(val, list) and all(_is_valid_size_int(s) for s in val):
            valid_pinned = [int(s) for s in val[:12]]
        else:
            _warn_and_fallback(
                "sizes.pinned",
                val,
                [],
                "Must be a list of positive integers (max 12). ",
            )

    # 3. recents (max 5)
    if "recents" in raw_sizes:
        val = raw_sizes["recents"]
        if isinstance(val, list) and all(_is_valid_size_int(s) for s in val):
            valid_recents = [int(s) for s in val[:5]]
        else:
            _warn_and_fallback(
                "sizes.recents",
                val,
                [],
                "Must be a list of positive integers (max 5). ",
            )

    return {
        "ladder": valid_ladder,
        "pinned": valid_pinned,
        "recents": valid_recents,
    }


def _validate_suggest_table(raw_suggest: Any) -> dict[str, Any]:
    """Validate [suggest] table with mode, pool, and max_segments."""
    valid_mode = "classic"
    valid_pool = list(DEFAULT_POOL)
    valid_max_segments = 6

    if not isinstance(raw_suggest, dict):
        _warn_and_fallback(
            "suggest",
            raw_suggest,
            DEFAULT_CONFIG["suggest"],
            "Must be a table with mode, pool, and max_segments. ",
        )
        return {
            "mode": valid_mode,
            "pool": valid_pool,
            "max_segments": valid_max_segments,
        }

    # mode
    if "mode" in raw_suggest:
        val = raw_suggest["mode"]
        if isinstance(val, str) and val.strip().lower() in VALID_SUGGEST_MODES:
            valid_mode = val.strip().lower()
        else:
            _warn_and_fallback(
                "suggest.mode",
                val,
                "classic",
                f"Must be one of {sorted(VALID_SUGGEST_MODES)}. ",
            )

    # pool
    if "pool" in raw_suggest:
        val = raw_suggest["pool"]
        if (
            isinstance(val, list)
            and len(val) > 0
            and all(_is_valid_size_int(s) for s in val)
        ):
            valid_pool = [int(s) for s in val]
        else:
            _warn_and_fallback(
                "suggest.pool",
                val,
                DEFAULT_POOL,
                "Must be a list of positive integers. ",
            )

    # max_segments
    if "max_segments" in raw_suggest:
        val = raw_suggest["max_segments"]
        if isinstance(val, int) and not isinstance(val, bool) and val >= 1:
            valid_max_segments = val
        else:
            _warn_and_fallback(
                "suggest.max_segments",
                val,
                6,
                "Must be an integer >= 1. ",
            )

    return {
        "mode": valid_mode,
        "pool": valid_pool,
        "max_segments": valid_max_segments,
    }


def validate_config_dict(raw_data: dict[str, Any]) -> dict[str, Any]:
    """Validate dictionary of config values and preserve unknown keys."""
    validated: dict[str, Any] = {
        "config_version": 1,
        "trigger_key": DEFAULT_CONFIG["trigger_key"],
        "sizes": {
            "ladder": list(DEFAULT_LADDER),
            "pinned": [],
            "recents": [],
        },
        "suggest": {
            "mode": "classic",
            "pool": list(DEFAULT_POOL),
            "max_segments": 6,
        },
        "output_mode": DEFAULT_CONFIG["output_mode"],
        "output_folder": DEFAULT_CONFIG["output_folder"],
        "naming_pattern": DEFAULT_CONFIG["naming_pattern"],
        "keep_format": DEFAULT_CONFIG["keep_format"],
        "allow_convert": DEFAULT_CONFIG["allow_convert"],
        "strip_metadata": DEFAULT_CONFIG["strip_metadata"],
        "min_side": DEFAULT_CONFIG["min_side"],
        "reduce_motion": DEFAULT_CONFIG["reduce_motion"],
        "theme": DEFAULT_CONFIG["theme"],
        "autostart": DEFAULT_CONFIG["autostart"],
    }

    # config_version
    if "config_version" in raw_data:
        val = raw_data["config_version"]
        if isinstance(val, int) and val >= 1:
            validated["config_version"] = val
        else:
            _warn_and_fallback("config_version", val, 1, "Must be an integer >= 1. ")

    # trigger_key
    if "trigger_key" in raw_data:
        val = raw_data["trigger_key"]
        if isinstance(val, str) and val.strip() and len(val.strip()) <= 100:
            validated["trigger_key"] = re.sub(r"[\r\n\x00-\x1f]", "", val.strip())
        else:
            _warn_and_fallback(
                "trigger_key",
                val,
                DEFAULT_CONFIG["trigger_key"],
                "Must be a non-empty string (max 100 chars). ",
            )

    # sizes
    if "sizes" in raw_data:
        validated["sizes"] = _validate_sizes_table(raw_data["sizes"])

    # suggest
    if "suggest" in raw_data:
        validated["suggest"] = _validate_suggest_table(raw_data["suggest"])

    # output_mode
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

    # output_folder
    if "output_folder" in raw_data:
        val = raw_data["output_folder"]
        if isinstance(val, str) and len(val) <= 1000:
            validated["output_folder"] = re.sub(r"[\r\n\x00-\x1f]", "", val)
        else:
            _warn_and_fallback(
                "output_folder",
                val,
                DEFAULT_CONFIG["output_folder"],
                "Must be a string (max 1000 chars). ",
            )

    # naming_pattern
    if "naming_pattern" in raw_data:
        val = raw_data["naming_pattern"]
        if isinstance(val, str) and val.strip() and len(val.strip()) <= 500:
            validated["naming_pattern"] = re.sub(r"[\r\n\x00-\x1f]", "", val.strip())
        else:
            _warn_and_fallback(
                "naming_pattern",
                val,
                DEFAULT_CONFIG["naming_pattern"],
                "Must be a non-empty pattern string (max 500 chars). ",
            )

    # keep_format
    if "keep_format" in raw_data:
        val = raw_data["keep_format"]
        if isinstance(val, bool):
            validated["keep_format"] = val
        else:
            _warn_and_fallback(
                "keep_format", val, DEFAULT_CONFIG["keep_format"], "Must be a boolean. "
            )

    # allow_convert
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

    # strip_metadata
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

    # min_side
    if "min_side" in raw_data:
        val = raw_data["min_side"]
        if (
            isinstance(val, (int, float))
            and not isinstance(val, bool)
            and not (isinstance(val, float) and (math.isnan(val) or math.isinf(val)))
            and 1 <= int(val) <= 100_000
        ):
            validated["min_side"] = int(val)
        else:
            _warn_and_fallback(
                "min_side",
                val,
                DEFAULT_CONFIG["min_side"],
                "Must be a positive integer between 1 and 100,000. ",
            )

    # reduce_motion
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

    # theme
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

    # autostart
    if "autostart" in raw_data:
        val = raw_data["autostart"]
        if isinstance(val, bool):
            validated["autostart"] = val
        else:
            _warn_and_fallback(
                "autostart", val, DEFAULT_CONFIG["autostart"], "Must be a boolean. "
            )

    # custom_sizes (backward compat migration)
    if "custom_sizes" in raw_data:
        val = raw_data["custom_sizes"]
        if isinstance(val, list) and not validated["sizes"]["recents"]:
            validated["sizes"]["recents"] = [
                int(s)
                for s in val
                if isinstance(s, (int, float))
                and int(s) > 0
                and not isinstance(s, bool)
            ][:5]

    # Preserve unknown keys!
    for k, v in raw_data.items():
        if k not in KNOWN_CONFIG_KEYS and k != "custom_sizes":
            validated[k] = v

    return validated


def _split_config_and_extras(data: dict[str, Any]) -> dict[str, Any]:
    """Split data into known SmolConfig fields and extra unknown keys."""
    args: dict[str, Any] = {}
    extras: dict[str, Any] = {}

    for k, v in data.items():
        if k in KNOWN_CONFIG_KEYS:
            args[k] = v
        else:
            extras[k] = v

    args["_extra_keys"] = extras
    return args


def load_config(config_path: Path | str | None = None) -> SmolConfig:
    """Load configuration from disk.

    Migrates schema version 0 to version 1 with config.toml.bak backup,
    preserves unknown keys, and returns SmolConfig.
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

    # Check if migration is needed
    needs_migration = (
        "config_version" not in data
        or data.get("config_version", 0) < 1
        or isinstance(data.get("sizes"), list)
        or "custom_sizes" in data
    )

    if needs_migration:
        bak_path = path.parent / (path.name + ".bak")
        if not bak_path.exists():
            try:
                shutil.copy2(path, bak_path)
            except OSError as exc:
                logger.warning(
                    f"Could not create backup config file at {bak_path}: {exc}"
                )

        # Migrate legacy sizes & custom_sizes
        if "sizes" in data and isinstance(data["sizes"], list):
            ladder = [int(s) for s in data["sizes"][:7]]
            recents = []
            if "custom_sizes" in data and isinstance(data["custom_sizes"], list):
                recents = [int(s) for s in data["custom_sizes"][:5]]
            data["sizes"] = {
                "ladder": ladder,
                "pinned": [],
                "recents": recents,
            }
            data.pop("custom_sizes", None)

        if "suggest" not in data:
            data["suggest"] = {
                "mode": "classic",
                "pool": list(DEFAULT_POOL),
                "max_segments": 6,
            }

        data["config_version"] = 1
        valid_dict = validate_config_dict(data)

        # Write migrated config to disk
        temp_path: Path | None = None
        try:
            content = tomli_w.dumps(valid_dict)
            with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as tf:
                tf.write(content.encode("utf-8"))
                temp_path = Path(tf.name)
            temp_path.replace(path)
            temp_path = None
        except OSError as exc:
            logger.warning(f"Could not write migrated config to {path}: {exc}")
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

        return SmolConfig(**_split_config_and_extras(valid_dict))

    valid_dict = validate_config_dict(data)
    return SmolConfig(**_split_config_and_extras(valid_dict))


def save_config(
    config: SmolConfig | dict[str, Any],
    config_path: Path | str | None = None,
) -> None:
    """Save configuration to disk atomically using tomli-w."""
    path = get_config_path(config_path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass

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
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as tf:
            tf.write(content.encode("utf-8"))
            temp_path = Path(tf.name)

        temp_path.replace(path)
        temp_path = None
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _is_within_5_percent(a: int, b: int) -> bool:
    """Check if two byte sizes are within 5% of each other."""
    if a == b:
        return True
    return abs(a - b) <= 0.05 * max(a, b) + 1e-9


def add_recent_size(
    target_bytes: int, config_path: Path | str | None = None
) -> list[int]:
    """Add a custom target size in bytes to sizes.recents.

    Deduplicates within 5% (newer value replaces and moves to front),
    ordered most recent first (LRU), capped at max 5 entries.
    """
    cfg = load_config(config_path)
    recents = list(cfg.sizes.recents)

    # Filter out near duplicates within 5%
    recents = [s for s in recents if not _is_within_5_percent(s, target_bytes)]

    # Prepend target_bytes at front (most recent first)
    recents.insert(0, int(target_bytes))

    # Cap at 5
    recents = recents[:5]

    cfg.sizes.recents = recents
    save_config(cfg, config_path)
    return recents


def add_pinned_size(
    target_bytes: int, config_path: Path | str | None = None
) -> list[int]:
    """Add a size in bytes to sizes.pinned (favourites), capped at max 12."""
    cfg = load_config(config_path)
    pinned = list(cfg.sizes.pinned)
    val = int(target_bytes)
    if val not in pinned:
        pinned.append(val)
    pinned = pinned[:12]
    cfg.sizes.pinned = pinned
    save_config(cfg, config_path)
    return pinned


def remove_pinned_size(
    target_bytes: int, config_path: Path | str | None = None
) -> list[int]:
    """Remove a size in bytes from sizes.pinned."""
    cfg = load_config(config_path)
    pinned = list(cfg.sizes.pinned)
    val = int(target_bytes)
    if val in pinned:
        pinned.remove(val)
    cfg.sizes.pinned = pinned
    save_config(cfg, config_path)
    return pinned
