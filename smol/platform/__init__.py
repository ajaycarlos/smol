"""Platform abstraction seam for smol."""

import sys
from pathlib import Path

from smol.platform.base import Platform
from smol.platform.linux import LinuxPlatform, migrate_if_needed

_CURRENT_PLATFORM: Platform | None = None


def get_platform() -> Platform:
    """Return the active platform adapter singleton."""
    global _CURRENT_PLATFORM
    if _CURRENT_PLATFORM is None:
        if sys.platform.startswith("linux"):
            _CURRENT_PLATFORM = LinuxPlatform()
        else:
            # Fall back to Linux adapter (no Windows/macOS code per v1.0 spec)
            _CURRENT_PLATFORM = LinuxPlatform()
    return _CURRENT_PLATFORM


def config_dir(app_name: str = "smol") -> Path:
    """Return the user configuration directory for app_name."""
    return get_platform().config_dir(app_name)


def state_dir(app_name: str = "smol") -> Path:
    """Return the user runtime state directory for app_name."""
    return get_platform().state_dir(app_name)


def cache_dir(app_name: str = "smol") -> Path:
    """Return the user cache directory for app_name."""
    return get_platform().cache_dir(app_name)


__all__ = [
    "LinuxPlatform",
    "Platform",
    "cache_dir",
    "config_dir",
    "get_platform",
    "migrate_if_needed",
    "state_dir",
]
