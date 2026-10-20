"""Linux platform adapter using platformdirs and X11 integrations."""

import logging
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import platformdirs

from smol.platform.base import (
    AutostartAdapter,
    CursorPositionAdapter,
    IntegrationAdapter,
    KeyHoldAdapter,
    NotificationAdapter,
    Platform,
)

logger = logging.getLogger(__name__)


def migrate_if_needed(old_path: Path | str, new_path: Path | str) -> bool:
    """Migrate legacy path to new path if old exists and new does not.

    Never deletes the old path. Logs any migration performed.
    Returns True if a migration occurred, False otherwise.
    """
    old = Path(old_path).expanduser()
    new = Path(new_path).expanduser()

    try:
        if old.resolve() == new.resolve():
            return False
    except OSError:
        if old == new:
            return False

    if not old.exists():
        return False

    if new.exists():
        return False

    try:
        new.parent.mkdir(parents=True, exist_ok=True)
        if old.is_dir():
            shutil.copytree(old, new)
        else:
            shutil.copy2(old, new)
        logger.info("Migrated legacy platform path from %s to %s", old, new)
        return True
    except OSError as err:
        logger.warning("Failed to migrate %s to %s: %s", old, new, err)
        return False


def _legacy_config_dir(app_name: str) -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / app_name


def _legacy_state_dir(app_name: str) -> Path:
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / app_name


def _legacy_cache_dir(app_name: str) -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / app_name


class LinuxKeyHoldAdapter(KeyHoldAdapter):
    """Linux key hold detection adapter delegating to X11 event listener."""

    def is_supported(self) -> bool:
        """Return True if X11 display session is available."""
        return bool(os.environ.get("DISPLAY"))

    def create_listener(
        self,
        trigger_key: str,
        on_hold_start: Callable[[], None] | None = None,
        on_hold_end: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Create an X11EventListener."""
        from smol.daemon.listener import X11EventListener

        return X11EventListener(
            trigger_key=trigger_key,
            on_hold_start=on_hold_start,
            on_hold_end=on_hold_end,
            **kwargs,
        )


class LinuxCursorPositionAdapter(CursorPositionAdapter):
    """Linux cursor position querying adapter using X11 root window pointer."""

    def get_cursor_position(self) -> tuple[int, int] | None:
        """Query X11 root window for pointer coordinates."""
        try:
            from Xlib import display

            d = display.Display()
            root = d.screen().root
            qp = root.query_pointer()
            d.close()
            return int(qp.root_x), int(qp.root_y)
        except Exception:  # noqa: BLE001
            return None


class LinuxIntegrationAdapter(IntegrationAdapter):
    """Linux file manager integration adapter."""

    def get_user_config_dir(self) -> Path:
        """Return base user configuration directory."""
        xdg = os.environ.get("XDG_CONFIG_HOME")
        return Path(xdg) if xdg else Path.home() / ".config"

    def get_manager(
        self,
        config_dir: Path | str | None = None,
        config_path: Path | str | None = None,
    ) -> Any:
        """Return IntegrationManager for Linux desktop file managers."""
        from smol.integrations.manager import IntegrationManager

        return IntegrationManager(config_dir=config_dir, config_path=config_path)


class LinuxAutostartAdapter(AutostartAdapter):
    """Linux desktop autostart adapter managing desktop entries in autostart dir."""

    def get_autostart_dir(self) -> Path:
        """Return the user autostart directory."""
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        base_dir = Path(xdg_config) if xdg_config else Path.home() / ".config"
        return base_dir / "autostart"

    def get_integrator(self, autostart_dir: Path | str | None = None) -> Any:
        """Return AutostartIntegrator."""
        from smol.integrations.autostart import AutostartIntegrator

        return AutostartIntegrator(autostart_dir=autostart_dir)


class LinuxNotificationAdapter(NotificationAdapter):
    """Linux desktop notification adapter using notify-send / notify_desktop."""

    def notify(self, title: str, message: str) -> bool:
        """Send notification via notify_desktop."""
        try:
            from smol.integrations.notifier import notify_desktop

            return notify_desktop(title=title, message=message)
        except Exception:  # noqa: BLE001
            return False


class LinuxPlatform(Platform):
    """Linux platform adapter backed by platformdirs and X11 integrations."""

    def __init__(self) -> None:
        self._key_hold = LinuxKeyHoldAdapter()
        self._cursor_position = LinuxCursorPositionAdapter()
        self._integration = LinuxIntegrationAdapter()
        self._autostart = LinuxAutostartAdapter()
        self._notifications = LinuxNotificationAdapter()

    def config_dir(self, app_name: str = "smol") -> Path:
        """Return user configuration directory via platformdirs."""
        p = platformdirs.user_config_path(app_name)
        legacy = _legacy_config_dir(app_name)
        if legacy != p and legacy.exists() and not p.exists():
            migrate_if_needed(legacy, p)
        return p

    def state_dir(self, app_name: str = "smol") -> Path:
        """Return user runtime state directory via platformdirs."""
        p = platformdirs.user_state_path(app_name)
        legacy = _legacy_state_dir(app_name)
        if legacy != p and legacy.exists() and not p.exists():
            migrate_if_needed(legacy, p)
        return p

    def cache_dir(self, app_name: str = "smol") -> Path:
        """Return user cache directory via platformdirs."""
        p = platformdirs.user_cache_path(app_name)
        legacy = _legacy_cache_dir(app_name)
        if legacy != p and legacy.exists() and not p.exists():
            migrate_if_needed(legacy, p)
        return p

    @property
    def key_hold(self) -> KeyHoldAdapter:
        return self._key_hold

    @property
    def cursor_position(self) -> CursorPositionAdapter:
        return self._cursor_position

    @property
    def integration(self) -> IntegrationAdapter:
        return self._integration

    @property
    def autostart(self) -> AutostartAdapter:
        return self._autostart

    @property
    def notifications(self) -> NotificationAdapter:
        return self._notifications
