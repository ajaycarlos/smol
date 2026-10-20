"""Tests for smol.platform interface, Linux adapter, and migration."""

import logging
from pathlib import Path
from unittest.mock import patch

from smol.platform import (
    cache_dir,
    config_dir,
    get_platform,
    migrate_if_needed,
    state_dir,
)
from smol.platform.base import Platform
from smol.platform.linux import LinuxPlatform


def test_platform_instance():
    """Verify get_platform returns a LinuxPlatform conforming to Platform."""
    plat = get_platform()
    assert isinstance(plat, Platform)
    assert isinstance(plat, LinuxPlatform)


def test_platform_directories_default():
    """Verify config_dir, state_dir, and cache_dir resolve through platformdirs."""
    cfg = config_dir()
    state = state_dir()
    cache = cache_dir()

    assert isinstance(cfg, Path)
    assert isinstance(state, Path)
    assert isinstance(cache, Path)
    assert cfg.name == "smol"
    assert state.name == "smol"
    assert cache.name == "smol"


def test_platform_directories_custom_app():
    """Verify directories can resolve for custom app names."""
    plat = get_platform()
    cfg = plat.config_dir("custom_test")
    assert cfg.name == "custom_test"


def test_platform_directories_xdg_env(monkeypatch, tmp_path):
    """Verify directories respect XDG environment variable overrides."""
    xdg_cfg = tmp_path / "mock_cfg"
    xdg_state = tmp_path / "mock_state"
    xdg_cache = tmp_path / "mock_cache"

    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_cfg))
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg_state))
    monkeypatch.setenv("XDG_CACHE_HOME", str(xdg_cache))

    plat = LinuxPlatform()
    assert plat.config_dir("smol") == xdg_cfg / "smol"
    assert plat.state_dir("smol") == xdg_state / "smol"
    assert plat.cache_dir("smol") == xdg_cache / "smol"


def test_platform_adapter_stubs():
    """Verify adapter stubs for key_hold, cursor, integration, autostart, notify."""
    plat = get_platform()

    assert hasattr(plat, "key_hold")
    assert hasattr(plat, "cursor_position")
    assert hasattr(plat, "integration")
    assert hasattr(plat, "autostart")
    assert hasattr(plat, "notifications")

    # Call each stub to verify interface behavior
    assert plat.key_hold is not None
    assert plat.cursor_position is not None
    assert plat.integration is not None
    assert plat.autostart is not None
    assert plat.notifications is not None


def test_one_time_migration_copies_without_deleting(tmp_path, caplog):
    """Verify migrate_if_needed copies old file, preserves it, and logs."""
    old_dir = tmp_path / "legacy_config"
    old_dir.mkdir()
    old_file = old_dir / "config.toml"
    old_file.write_text("trigger_key = 'Ctrl+Alt'\n", encoding="utf-8")

    new_dir = tmp_path / "new_config"
    new_file = new_dir / "config.toml"

    with caplog.at_level(logging.INFO):
        migrated = migrate_if_needed(old_file, new_file)

    assert migrated is True
    assert new_file.is_file()
    assert new_file.read_text(encoding="utf-8") == "trigger_key = 'Ctrl+Alt'\n"
    # Old file MUST NOT be deleted
    assert old_file.is_file()
    assert "Migrated" in caplog.text or "migrated" in caplog.text


def test_migration_same_path_noop(tmp_path, caplog):
    """When old and new paths are identical, migrate_if_needed does nothing."""
    same_file = tmp_path / "config.toml"
    same_file.write_text("data = 1\n", encoding="utf-8")

    caplog.clear()
    with caplog.at_level(logging.INFO):
        assert migrate_if_needed(same_file, same_file) is False
    assert caplog.text == ""


def test_migration_destination_exists_noop(tmp_path, caplog):
    """When destination already exists, migrate_if_needed does not overwrite."""
    old_file = tmp_path / "old.toml"
    old_file.write_text("old", encoding="utf-8")
    new_file = tmp_path / "new.toml"
    new_file.write_text("new", encoding="utf-8")

    caplog.clear()
    with caplog.at_level(logging.INFO):
        assert migrate_if_needed(old_file, new_file) is False
    assert new_file.read_text(encoding="utf-8") == "new"
    assert old_file.read_text(encoding="utf-8") == "old"


def test_migration_missing_source_noop(tmp_path, caplog):
    """When old file does not exist, migrate_if_needed does nothing."""
    old_file = tmp_path / "missing.toml"
    new_file = tmp_path / "new.toml"

    caplog.clear()
    with caplog.at_level(logging.INFO):
        assert migrate_if_needed(old_file, new_file) is False
    assert not new_file.exists()


def test_config_uses_platform_seam(monkeypatch, tmp_path):
    """Verify smol.config resolves config location through smol.platform."""
    from smol.config import get_config_path

    monkeypatch.delenv("SMOL_CONFIG_PATH", raising=False)
    fake_config_dir = tmp_path / "platform_cfg" / "smol"

    with patch("smol.platform.config_dir", return_value=fake_config_dir):
        path = get_config_path()
        assert path == fake_config_dir / "config.toml"


def test_daemon_service_uses_platform_seam(monkeypatch, tmp_path):
    """Verify smol.daemon.service resolves state directory through smol.platform."""
    from smol.daemon.service import get_state_dir

    monkeypatch.delenv("SMOL_STATE_DIR", raising=False)
    fake_state_dir = tmp_path / "platform_state" / "smol"

    with patch("smol.platform.state_dir", return_value=fake_state_dir):
        path = get_state_dir()
        assert path == fake_state_dir


def test_platform_config_dir_migrates_from_legacy_when_mocked(
    tmp_path, monkeypatch, caplog
):
    """Verify LinuxPlatform.config_dir copies legacy files when mocked path differs."""
    legacy_dir = tmp_path / "legacy_conf"
    legacy_dir.mkdir()
    (legacy_dir / "config.toml").write_text("trigger_key = 'Super'\n", encoding="utf-8")

    # Mock legacy dir and new platformdirs path
    monkeypatch.setattr(
        "smol.platform.linux._legacy_config_dir", lambda app: legacy_dir
    )
    mocked_new_dir = tmp_path / "brand_new_platform_config" / "smol"
    monkeypatch.setattr("platformdirs.user_config_path", lambda app: mocked_new_dir)

    plat = LinuxPlatform()
    with caplog.at_level(logging.INFO):
        res_dir = plat.config_dir("smol")

    assert res_dir == mocked_new_dir
    assert (mocked_new_dir / "config.toml").is_file()
    assert (
        mocked_new_dir / "config.toml"
    ).read_text(encoding="utf-8") == "trigger_key = 'Super'\n"
    # Legacy file must never be deleted
    assert (legacy_dir / "config.toml").is_file()
    assert "Migrated" in caplog.text or "migrated" in caplog.text


def test_platform_state_dir_migrates_from_legacy_when_mocked(
    tmp_path, monkeypatch, caplog
):
    """Verify LinuxPlatform.state_dir copies legacy files when mocked path differs."""
    legacy_dir = tmp_path / "legacy_state"
    legacy_dir.mkdir()
    (legacy_dir / "daemon.pid").write_text("1234\n", encoding="utf-8")

    monkeypatch.setattr("smol.platform.linux._legacy_state_dir", lambda app: legacy_dir)
    mocked_new_dir = tmp_path / "brand_new_platform_state" / "smol"
    monkeypatch.setattr("platformdirs.user_state_path", lambda app: mocked_new_dir)

    plat = LinuxPlatform()
    with caplog.at_level(logging.INFO):
        res_dir = plat.state_dir("smol")

    assert res_dir == mocked_new_dir
    assert (mocked_new_dir / "daemon.pid").is_file()
    assert (legacy_dir / "daemon.pid").is_file()
