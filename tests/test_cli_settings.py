"""Tests for smol settings CLI subcommand."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from smol.cli import main, settings


def test_cli_settings_help(capsys) -> None:
    """Verify `smol settings --help` displays usage."""
    code = main(["settings", "--help"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Open the smol graphical settings window" in captured.out
    assert "--config" in captured.out


def test_cli_settings_launches_window(tmp_path: Path) -> None:
    """Verify `smol settings` initializes SettingsWindow with config path."""
    cfg_file = tmp_path / "custom_config.toml"

    with patch("smol.ui.settings_window.SettingsWindow") as mock_window_cls:
        mock_win = MagicMock()
        mock_window_cls.return_value = mock_win

        with patch("PySide6.QtWidgets.QApplication.instance") as mock_app_inst:
            fake_app = MagicMock()
            fake_app.exec.return_value = 0
            mock_app_inst.return_value = fake_app

            code = settings(["--config", str(cfg_file)])
            assert code == 0
            mock_window_cls.assert_called_once_with(config_path=str(cfg_file))
            mock_win.show.assert_called_once()
            fake_app.exec.assert_called_once()
