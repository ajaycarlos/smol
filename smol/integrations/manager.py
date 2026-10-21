"""File manager right-click integration management for smol."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from smol.config import DEFAULT_CONFIG, load_config
from smol.core.size import format_size


def _atomic_write_text(path: Path, content: str, mode: int | None = None) -> None:
    """Write text atomically to path using an unpredictable temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", dir=path.parent, encoding="utf-8", delete=False
        ) as tf:
            tf.write(content)
            temp_path = Path(tf.name)
        if mode is not None:
            os.chmod(temp_path, mode)
        temp_path.replace(path)
        temp_path = None
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _atomic_write_xml(path: Path, tree: ET.ElementTree) -> None:
    """Write XML atomically to path using an unpredictable temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as tf:
            tree.write(tf, encoding="utf-8", xml_declaration=True)
            temp_path = Path(tf.name)
        temp_path.replace(path)
        temp_path = None
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def get_integration_sizes(
    config_path: Path | str | None = None,
) -> list[tuple[str, str, str]]:
    """Return list of (size_arg, label, slug) generated from configured sizes."""
    cfg = load_config(config_path)
    sizes = cfg.sizes
    res: list[tuple[str, str, str]] = []
    for sz in sizes:
        arg = format_size(sz, spaced=False)
        label = format_size(sz, spaced=True)
        slug = arg.lower()
        res.append((arg, label, slug))
    return res


# Backward compatibility default reference based on canonical DEFAULT_CONFIG
INTEGRATION_SIZES: list[tuple[str, str, str]] = [
    (
        format_size(sz, spaced=False),
        format_size(sz, spaced=True),
        format_size(sz, spaced=False).lower(),
    )
    for sz in (
        DEFAULT_CONFIG["sizes"]["ladder"]
        if isinstance(DEFAULT_CONFIG["sizes"], dict)
        else DEFAULT_CONFIG["sizes"]
    )
]


@dataclass
class IntegrationResult:
    ok: bool
    message: str
    installed_files: list[Path] = field(default_factory=list)
    removed_files: list[Path] = field(default_factory=list)


@dataclass
class IntegrationStatus:
    file_manager: str
    installed: bool
    partial: bool
    installed_sizes: list[str]
    missing_sizes: list[str]
    details: str


def find_smol_binary() -> str:
    """Return the absolute path to the smol binary or fallback to 'smol'."""
    which_smol = shutil.which("smol")
    if which_smol:
        return which_smol

    # If invoked directly via python venv
    venv_bin = Path(sys.prefix) / "bin" / "smol"
    if venv_bin.exists():
        return str(venv_bin)

    return "smol"


class Integrator(Protocol):
    file_manager: str

    def install(self) -> IntegrationResult: ...
    def uninstall(self) -> IntegrationResult: ...
    def status(self) -> IntegrationStatus: ...


class NemoIntegrator:
    """Integrator for Nemo file manager using .nemo_action and actions-tree.json."""

    def __init__(
        self,
        actions_dir: Path | None = None,
        config_dir: Path | None = None,
        smol_bin: str | None = None,
        config_path: Path | str | None = None,
    ) -> None:
        self.file_manager = "nemo"
        user_data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        from smol.platform import config_dir as get_platform_config_dir

        self.actions_dir = actions_dir or (user_data / "nemo/actions")
        self.config_dir = config_dir or get_platform_config_dir("nemo")
        self.tree_file = self.config_dir / "actions-tree.json"
        self.smol_bin = smol_bin or find_smol_binary()
        self.config_path = config_path
        self.sizes = get_integration_sizes(self.config_path)

    def _action_filename(self, slug: str) -> str:
        return f"smol_shrink_{slug}.nemo_action"

    def install(self) -> IntegrationResult:
        """Install .nemo_action files and register 'Shrink to…' submenu."""
        self.actions_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)

        installed_files: list[Path] = []
        action_uuids: list[str] = []

        for size_arg, label, slug in self.sizes:
            filename = self._action_filename(slug)
            action_path = self.actions_dir / filename
            action_uuids.append(filename)

            # Generate nemo_action content
            bin_cmd = f'"{self.smol_bin}"' if " " in self.smol_bin else self.smol_bin
            content = (
                "[Nemo Action]\n"
                "Active=true\n"
                f"Name={label}\n"
                f"Comment=Shrink file to at most {label} with smol\n"
                f"Exec={bin_cmd} shrink --notify --max {size_arg} -- %F\n"
                "Icon-Name=image-x-generic\n"
                "Selection=notnone\n"
                "Extensions=jpg;jpeg;png;webp;heic;avif;pdf;\n"
                "Quote=double\n"
            )

            # Atomic write
            _atomic_write_text(action_path, content)
            installed_files.append(action_path)

        # Update or create actions-tree.json for the 'Shrink to…' submenu
        tree_data: dict = {"toplevel": []}
        if self.tree_file.exists():
            try:
                loaded = json.loads(self.tree_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and "toplevel" in loaded:
                    tree_data = loaded
                elif isinstance(loaded, list):
                    tree_data = {"toplevel": loaded}
            except (json.JSONDecodeError, OSError):
                tree_data = {"toplevel": []}

        children = [{"uuid": uuid, "type": "action"} for uuid in action_uuids]
        submenu_entry = {
            "uuid": "smol-shrink-submenu",
            "type": "submenu",
            "user-label": "Shrink to…",
            "user-icon": "image-x-generic",
            "children": children,
        }

        # Check if submenu already exists
        toplevel = tree_data.get("toplevel", [])
        found = False
        for i, item in enumerate(toplevel):
            if isinstance(item, dict) and item.get("uuid") == "smol-shrink-submenu":
                toplevel[i] = submenu_entry
                found = True
                break

        if not found:
            toplevel.append(submenu_entry)

        tree_data["toplevel"] = toplevel

        _atomic_write_text(self.tree_file, json.dumps(tree_data, indent=2))
        installed_files.append(self.tree_file)

        msg = (
            f"Installed Nemo right-click integration ({len(self.sizes)} "
            "sizes in 'Shrink to…' submenu)"
        )
        return IntegrationResult(
            ok=True,
            message=msg,
            installed_files=installed_files,
        )

    def uninstall(self) -> IntegrationResult:
        """Remove .nemo_action files and remove submenu from actions-tree.json."""
        removed_files: list[Path] = []

        # Remove action files
        for _, _, slug in self.sizes:
            filename = self._action_filename(slug)
            action_path = self.actions_dir / filename
            if action_path.exists():
                action_path.unlink()
                removed_files.append(action_path)

        # Remove from actions-tree.json
        if self.tree_file.exists():
            try:
                loaded = json.loads(self.tree_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and "toplevel" in loaded:
                    toplevel = [
                        item
                        for item in loaded["toplevel"]
                        if not (
                            isinstance(item, dict)
                            and item.get("uuid") == "smol-shrink-submenu"
                        )
                    ]
                    if not toplevel:
                        # Cleanly remove the file if only our submenu was inside
                        self.tree_file.unlink()
                        removed_files.append(self.tree_file)
                    else:
                        loaded["toplevel"] = toplevel
                        _atomic_write_text(self.tree_file, json.dumps(loaded, indent=2))
            except (json.JSONDecodeError, OSError):
                pass

        return IntegrationResult(
            ok=True,
            message="Uninstalled Nemo right-click integration cleanly",
            removed_files=removed_files,
        )

    def status(self) -> IntegrationStatus:
        """Check Nemo integration status."""
        installed_sizes: list[str] = []
        missing_sizes: list[str] = []

        for _, label, slug in self.sizes:
            action_path = self.actions_dir / self._action_filename(slug)
            if action_path.exists():
                installed_sizes.append(label)
            else:
                missing_sizes.append(label)

        tree_has_submenu = False
        if self.tree_file.exists():
            try:
                tree_data = json.loads(self.tree_file.read_text(encoding="utf-8"))
                toplevel = tree_data.get("toplevel", [])
                tree_has_submenu = any(
                    isinstance(item, dict) and item.get("uuid") == "smol-shrink-submenu"
                    for item in toplevel
                )
            except (json.JSONDecodeError, OSError):
                pass

        is_installed = len(installed_sizes) == len(self.sizes) and tree_has_submenu
        is_partial = bool(installed_sizes or tree_has_submenu) and not is_installed

        if is_installed:
            details = (
                f"Installed in {self.actions_dir} "
                "(Submenu 'Shrink to…' configured in actions-tree.json)"
            )
        elif is_partial:
            details = (
                f"Partially installed ({len(installed_sizes)}/"
                f"{len(self.sizes)} actions found)"
            )
        else:
            details = f"Not installed in {self.actions_dir}"

        return IntegrationStatus(
            file_manager=self.file_manager,
            installed=is_installed,
            partial=is_partial,
            installed_sizes=installed_sizes,
            missing_sizes=missing_sizes,
            details=details,
        )


class NautilusIntegrator:
    """Integrator for GNOME Nautilus using scripts in subfolders."""

    def __init__(
        self,
        scripts_dir: Path | None = None,
        smol_bin: str | None = None,
        config_path: Path | str | None = None,
    ) -> None:
        self.file_manager = "nautilus"
        user_data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        self.scripts_dir = scripts_dir or (user_data / "nautilus/scripts")
        self.submenu_dir = self.scripts_dir / "Shrink to…"
        self.smol_bin = smol_bin or find_smol_binary()
        self.config_path = config_path
        self.sizes = get_integration_sizes(self.config_path)

    def install(self) -> IntegrationResult:
        self.submenu_dir.mkdir(parents=True, exist_ok=True)
        installed_files: list[Path] = []

        for size_arg, label, _ in self.sizes:
            script_path = self.submenu_dir / label
            content = (
                "#!/bin/sh\n"
                f'exec "{self.smol_bin}" shrink --notify --max {size_arg} -- "$@"\n'
            )
            _atomic_write_text(script_path, content, mode=0o755)
            installed_files.append(script_path)

        return IntegrationResult(
            ok=True,
            message=f"Installed Nautilus scripts in {self.submenu_dir}",
            installed_files=installed_files,
        )

    def uninstall(self) -> IntegrationResult:
        removed_files: list[Path] = []
        if self.submenu_dir.exists():
            for script in self.submenu_dir.glob("*"):
                script.unlink()
                removed_files.append(script)
            self.submenu_dir.rmdir()
            removed_files.append(self.submenu_dir)

        return IntegrationResult(
            ok=True,
            message="Uninstalled Nautilus right-click scripts",
            removed_files=removed_files,
        )

    def status(self) -> IntegrationStatus:
        installed_sizes = []
        missing_sizes = []

        for _, label, _ in self.sizes:
            script_path = self.submenu_dir / label
            if script_path.exists() and os.access(script_path, os.X_OK):
                installed_sizes.append(label)
            else:
                missing_sizes.append(label)

        is_installed = len(installed_sizes) == len(self.sizes)
        is_partial = bool(installed_sizes) and not is_installed
        details = (
            f"Installed in {self.submenu_dir}"
            if is_installed
            else f"Not installed in {self.submenu_dir}"
        )

        return IntegrationStatus(
            file_manager=self.file_manager,
            installed=is_installed,
            partial=is_partial,
            installed_sizes=installed_sizes,
            missing_sizes=missing_sizes,
            details=details,
        )


class DolphinIntegrator:
    """Integrator for KDE Dolphin using service menus with submenu."""

    def __init__(
        self,
        service_menu_dir: Path | None = None,
        smol_bin: str | None = None,
        config_path: Path | str | None = None,
    ) -> None:
        self.file_manager = "dolphin"
        user_data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        # Check KDE 6 kio/servicemenus or KDE 5 kservices5/ServiceMenus
        kio_dir = user_data / "kio/servicemenus"
        kservices_dir = user_data / "kservices5/ServiceMenus"
        self.service_menu_dir = service_menu_dir or (
            kio_dir if kio_dir.parent.exists() else kservices_dir
        )
        self.desktop_file = self.service_menu_dir / "smol_shrink.desktop"
        self.smol_bin = smol_bin or find_smol_binary()
        self.config_path = config_path
        self.sizes = get_integration_sizes(self.config_path)

    def install(self) -> IntegrationResult:
        self.service_menu_dir.mkdir(parents=True, exist_ok=True)
        actions = [f"shrink_{slug}" for _, _, slug in self.sizes]

        lines = [
            "[Desktop Entry]",
            "Type=Service",
            "ServiceTypes=KonqPopupMenu/Plugin",
            "MimeType=image/jpeg;image/png;image/webp;image/heif;image/avif;application/pdf;",
            f"Actions={';'.join(actions)};",
            "X-KDE-Submenu=Shrink to…",
            "X-KDE-Priority=TopLevel",
            "",
        ]

        bin_cmd = f'"{self.smol_bin}"' if " " in self.smol_bin else self.smol_bin
        for size_arg, label, slug in self.sizes:
            lines.extend(
                [
                    f"[Desktop Action shrink_{slug}]",
                    f"Name={label}",
                    "Icon=image-x-generic",
                    f"Exec={bin_cmd} shrink --notify --max {size_arg} -- %F",
                    "",
                ]
            )

        content = "\n".join(lines)
        _atomic_write_text(self.desktop_file, content)

        return IntegrationResult(
            ok=True,
            message=f"Installed Dolphin service menu at {self.desktop_file}",
            installed_files=[self.desktop_file],
        )

    def uninstall(self) -> IntegrationResult:
        removed_files = []
        if self.desktop_file.exists():
            self.desktop_file.unlink()
            removed_files.append(self.desktop_file)

        return IntegrationResult(
            ok=True,
            message="Uninstalled Dolphin service menu",
            removed_files=removed_files,
        )

    def status(self) -> IntegrationStatus:
        is_installed = self.desktop_file.exists()
        installed_sizes = [label for _, label, _ in self.sizes] if is_installed else []
        missing_sizes = [] if is_installed else [label for _, label, _ in self.sizes]

        return IntegrationStatus(
            file_manager=self.file_manager,
            installed=is_installed,
            partial=False,
            installed_sizes=installed_sizes,
            missing_sizes=missing_sizes,
            details=f"Service menu at {self.desktop_file}"
            if is_installed
            else f"Missing {self.desktop_file}",
        )


class ThunarIntegrator:
    """Integrator for XFCE Thunar using custom actions in uca.xml."""

    def __init__(
        self,
        uca_file: Path | None = None,
        smol_bin: str | None = None,
        config_path: Path | str | None = None,
    ) -> None:
        self.file_manager = "thunar"
        from smol.platform import config_dir as get_platform_config_dir

        self.uca_file = uca_file or (get_platform_config_dir("Thunar") / "uca.xml")
        self.smol_bin = smol_bin or find_smol_binary()
        self.config_path = config_path
        self.sizes = get_integration_sizes(self.config_path)

    def install(self) -> IntegrationResult:
        self.uca_file.parent.mkdir(parents=True, exist_ok=True)
        if self.uca_file.exists():
            try:
                tree = ET.parse(self.uca_file)
                root = tree.getroot()
            except (ET.ParseError, OSError):
                bak = self.uca_file.with_suffix(".xml.bak")
                try:
                    shutil.copy2(self.uca_file, bak)
                except OSError:
                    pass
                root = ET.Element("actions")
                tree = ET.ElementTree(root)
        else:
            root = ET.Element("actions")
            tree = ET.ElementTree(root)

        # Remove existing smol actions first
        for action in list(root.findall("action")):
            unique_id = action.find("unique-id")
            if (
                unique_id is not None
                and unique_id.text
                and unique_id.text.startswith("smol-")
            ):
                root.remove(action)

        bin_cmd = f'"{self.smol_bin}"' if " " in self.smol_bin else self.smol_bin
        # Add actions for each size
        for size_arg, label, slug in self.sizes:
            action = ET.SubElement(root, "action")
            ET.SubElement(action, "icon").text = "image-x-generic"
            ET.SubElement(action, "name").text = label
            ET.SubElement(action, "submenu").text = "Shrink to…"
            ET.SubElement(action, "unique-id").text = f"smol-{slug}"
            ET.SubElement(
                action, "command"
            ).text = f"{bin_cmd} shrink --notify --max {size_arg} -- %F"
            ET.SubElement(
                action, "description"
            ).text = f"Shrink file to at most {label}"
            patterns = (
                "*.jpg;*.jpeg;*.png;*.webp;*.heic;*.avif;*.pdf;"
                "*.JPG;*.JPEG;*.PNG;*.WEBP;*.HEIC;*.AVIF;*.PDF"
            )
            ET.SubElement(action, "patterns").text = patterns
            ET.SubElement(action, "image-files")
            ET.SubElement(action, "other-files")

        _atomic_write_xml(self.uca_file, tree)

        return IntegrationResult(
            ok=True,
            message=f"Installed Thunar custom actions in {self.uca_file}",
            installed_files=[self.uca_file],
        )

    def uninstall(self) -> IntegrationResult:
        removed_files = []
        if self.uca_file.exists():
            try:
                tree = ET.parse(self.uca_file)
                root = tree.getroot()
                changed = False
                for action in list(root.findall("action")):
                    unique_id = action.find("unique-id")
                    if (
                        unique_id is not None
                        and unique_id.text
                        and unique_id.text.startswith("smol-")
                    ):
                        root.remove(action)
                        changed = True
                if changed:
                    _atomic_write_xml(self.uca_file, tree)
                    removed_files.append(self.uca_file)
            except (ET.ParseError, OSError):
                pass

        return IntegrationResult(
            ok=True,
            message="Uninstalled Thunar custom actions",
            removed_files=removed_files,
        )

    def status(self) -> IntegrationStatus:
        installed_sizes = []
        missing_sizes = []

        if self.uca_file.exists():
            try:
                tree = ET.parse(self.uca_file)
                root = tree.getroot()
                action_ids = {
                    action.find("unique-id").text
                    for action in root.findall("action")
                    if action.find("unique-id") is not None
                }
                for _, label, slug in self.sizes:
                    if f"smol-{slug}" in action_ids:
                        installed_sizes.append(label)
                    else:
                        missing_sizes.append(label)
            except (ET.ParseError, OSError):
                missing_sizes = [label for _, label, _ in self.sizes]
        else:
            missing_sizes = [label for _, label, _ in self.sizes]

        is_installed = len(installed_sizes) == len(self.sizes)
        is_partial = bool(installed_sizes) and not is_installed

        return IntegrationStatus(
            file_manager=self.file_manager,
            installed=is_installed,
            partial=is_partial,
            installed_sizes=installed_sizes,
            missing_sizes=missing_sizes,
            details=f"Config in {self.uca_file}"
            if is_installed
            else f"Not configured in {self.uca_file}",
        )


def get_integrator(
    file_manager: str | None = None,
    config_path: Path | str | None = None,
) -> Integrator:
    """Get the integrator instance for the requested or detected file manager."""
    fm = file_manager.lower() if file_manager else None

    if not fm:
        from smol.cli import _find_file_manager

        detected_fm, _ = _find_file_manager()
        fm = detected_fm or "nemo"

    if fm == "nemo":
        return NemoIntegrator(config_path=config_path)
    if fm == "nautilus":
        return NautilusIntegrator(config_path=config_path)
    if fm == "dolphin":
        return DolphinIntegrator(config_path=config_path)
    if fm == "thunar":
        return ThunarIntegrator(config_path=config_path)

    raise ValueError(
        f"Unsupported file manager: {fm}. Supported: nemo, nautilus, dolphin, thunar"
    )
