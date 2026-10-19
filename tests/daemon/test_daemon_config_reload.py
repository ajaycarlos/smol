"""Tests for daemon hot-reload and config change detection."""

import logging
from pathlib import Path

import pytest

from smol.config import SmolConfig, save_config
from smol.daemon.service import DaemonService


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Provide isolated state dir and config path."""
    state_dir = tmp_path / "state"
    config_file = tmp_path / "config.toml"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SMOL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("SMOL_CONFIG_PATH", str(config_file))
    return state_dir, config_file


def test_daemon_detects_config_modification_and_logs_message(
    isolated_env: tuple[Path, Path], caplog: pytest.LogCaptureFixture
):
    """Daemon service detects when config.toml is updated and logs reload."""
    state_dir, config_file = isolated_env
    save_config(
        SmolConfig(trigger_key="Super", sizes=[50_000, 100_000]),
        config_path=config_file,
    )

    service = DaemonService(state_dir=state_dir, config_path=config_file)
    logger = service.setup_logging(console=True)
    service._logger = logger

    # Record initial config state
    service._record_config_state()
    assert service.is_config_changed() is False

    # Modify config on disk
    save_config(
        SmolConfig(trigger_key="Ctrl+Alt", sizes=[20_000, 80_000]),
        config_path=config_file,
    )
    assert service.is_config_changed() is True

    with caplog.at_level(logging.INFO):
        service.check_and_reload_config()

    # Verify that a clear log message was recorded
    assert any(
        "Configuration changed on disk" in record.message
        or "Configuration reloaded" in record.message
        for record in caplog.records
    )


def test_daemon_status_reports_restart_needed(
    isolated_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
):
    """daemon status reports restart needed when config file is newer."""
    state_dir, config_file = isolated_env
    save_config(SmolConfig(trigger_key="Super"), config_path=config_file)

    service = DaemonService(state_dir=state_dir, config_path=config_file)
    service._record_config_state()

    # When config is unchanged, restart_needed is False
    assert service.needs_restart() is False

    # Modify config
    save_config(SmolConfig(trigger_key="Ctrl+Alt"), config_path=config_file)
    assert service.needs_restart() is True
