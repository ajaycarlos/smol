"""Abstract interface and protocols for the smol platform seam."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any


class KeyHoldAdapter(ABC):
    """Abstract adapter for system-wide key hold detection."""

    @abstractmethod
    def is_supported(self) -> bool:
        """Return True if global key hold detection is supported on this platform."""
        ...

    @abstractmethod
    def create_listener(
        self,
        trigger_key: str,
        on_hold_start: Callable[[], None] | None = None,
        on_hold_end: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Create a platform event listener for global key holding."""
        ...


class CursorPositionAdapter(ABC):
    """Abstract adapter for querying global screen cursor coordinates."""

    @abstractmethod
    def get_cursor_position(self) -> tuple[int, int] | None:
        """Return current global (x, y) cursor coordinates, or None if unavailable."""
        ...


class IntegrationAdapter(ABC):
    """Abstract adapter for desktop file manager context menu integrations."""

    @abstractmethod
    def get_user_config_dir(self) -> Path:
        """Return the base user configuration directory."""
        ...

    @abstractmethod
    def get_manager(
        self,
        config_dir: Path | str | None = None,
        config_path: Path | str | None = None,
    ) -> Any:
        """Return the file manager integration manager instance."""
        ...


class AutostartAdapter(ABC):
    """Abstract adapter for desktop login autostart configuration."""

    @abstractmethod
    def get_autostart_dir(self) -> Path:
        """Return the directory where autostart entries are stored."""
        ...

    @abstractmethod
    def get_integrator(self, autostart_dir: Path | str | None = None) -> Any:
        """Return the autostart integrator instance."""
        ...


class NotificationAdapter(ABC):
    """Abstract adapter for desktop notifications."""

    @abstractmethod
    def notify(self, title: str, message: str) -> bool:
        """Send a desktop notification and return True on success."""
        ...


class Platform(ABC):
    """Abstract platform interface defining directories and subsystem adapters."""

    @abstractmethod
    def config_dir(self, app_name: str = "smol") -> Path:
        """Return the platform user configuration directory."""
        ...

    @abstractmethod
    def state_dir(self, app_name: str = "smol") -> Path:
        """Return the platform user runtime state directory."""
        ...

    @abstractmethod
    def cache_dir(self, app_name: str = "smol") -> Path:
        """Return the platform user cache directory."""
        ...

    @property
    @abstractmethod
    def key_hold(self) -> KeyHoldAdapter:
        """Return the key hold detection adapter."""
        ...

    @property
    @abstractmethod
    def cursor_position(self) -> CursorPositionAdapter:
        """Return the global cursor position querying adapter."""
        ...

    @property
    @abstractmethod
    def integration(self) -> IntegrationAdapter:
        """Return the file manager context menu integration adapter."""
        ...

    @property
    @abstractmethod
    def autostart(self) -> AutostartAdapter:
        """Return the login autostart adapter."""
        ...

    @property
    @abstractmethod
    def notifications(self) -> NotificationAdapter:
        """Return the system notification adapter."""
        ...
