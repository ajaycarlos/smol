"""XDG autostart desktop entry integration for smol daemon."""

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AutostartResult:
    ok: bool
    message: str
    installed_files: list[Path] = field(default_factory=list)
    removed_files: list[Path] = field(default_factory=list)


@dataclass
class AutostartStatus:
    installed: bool
    desktop_file: Path
    details: str


def get_autostart_dir() -> Path:
    """Return the user XDG autostart directory."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        base_dir = Path(xdg_config)
    else:
        base_dir = Path.home() / ".config"
    return base_dir / "autostart"


def find_smol_binary() -> str:
    """Return the absolute path to the smol binary or fallback to 'smol'."""
    which_smol = shutil.which("smol")
    if which_smol:
        return which_smol

    venv_bin = Path(sys.prefix) / "bin" / "smol"
    if venv_bin.exists():
        return str(venv_bin)

    return "smol"


class AutostartIntegrator:
    """Manages ~/.config/autostart/smol.desktop to start the smol daemon at login."""

    def __init__(
        self,
        autostart_dir: Path | None = None,
        smol_bin: str | None = None,
    ) -> None:
        self.autostart_dir = autostart_dir or get_autostart_dir()
        self.smol_bin = smol_bin or find_smol_binary()
        self.desktop_file = self.autostart_dir / "smol.desktop"

    def _generate_desktop_content(self) -> str:
        exec_cmd = f"{self.smol_bin} daemon start"
        return (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=smol daemon\n"
            "Comment=Background daemon for smol file shrinker\n"
            f"Exec={exec_cmd}\n"
            "Terminal=false\n"
            "Categories=Utility;\n"
            "StartupNotify=false\n"
            "X-GNOME-Autostart-enabled=true\n"
        )

    def install(self) -> AutostartResult:
        """Install or update the XDG autostart entry."""
        try:
            self.autostart_dir.mkdir(parents=True, exist_ok=True)
            content = self._generate_desktop_content()

            tmp_file = self.desktop_file.with_suffix(".tmp")
            tmp_file.write_text(content, encoding="utf-8")
            tmp_file.replace(self.desktop_file)

            return AutostartResult(
                ok=True,
                message=f"Installed autostart entry: {self.desktop_file}",
                installed_files=[self.desktop_file],
            )
        except OSError as exc:
            return AutostartResult(
                ok=False,
                message=f"Failed to install autostart entry: {exc}",
            )

    def uninstall(self) -> AutostartResult:
        """Remove the XDG autostart entry."""
        try:
            if not self.desktop_file.exists():
                return AutostartResult(
                    ok=True,
                    message="Autostart entry is not installed.",
                )

            self.desktop_file.unlink()
            return AutostartResult(
                ok=True,
                message=f"Uninstalled autostart entry: {self.desktop_file}",
                removed_files=[self.desktop_file],
            )
        except OSError as exc:
            return AutostartResult(
                ok=False,
                message=f"Failed to uninstall autostart entry: {exc}",
            )

    def status(self) -> AutostartStatus:
        """Check status of autostart entry."""
        if not self.desktop_file.exists():
            return AutostartStatus(
                installed=False,
                desktop_file=self.desktop_file,
                details=f"Not installed (file missing: {self.desktop_file})",
            )

        try:
            content = self.desktop_file.read_text(encoding="utf-8")
            has_entry = "[Desktop Entry]" in content
            exec_line = ""
            for line in content.splitlines():
                if line.startswith("Exec="):
                    exec_line = line.strip()
                    break

            if has_entry and exec_line:
                return AutostartStatus(
                    installed=True,
                    desktop_file=self.desktop_file,
                    details=f"Installed: {self.desktop_file} ({exec_line})",
                )
            else:
                return AutostartStatus(
                    installed=False,
                    desktop_file=self.desktop_file,
                    details=f"Invalid entry in {self.desktop_file}",
                )
        except OSError as exc:
            return AutostartStatus(
                installed=False,
                desktop_file=self.desktop_file,
                details=f"Error reading {self.desktop_file}: {exc}",
            )
