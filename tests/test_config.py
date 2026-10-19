"""Tests for smol.config configuration loading, saving, defaults, and validation."""

from pathlib import Path

import pytest

from smol.config import (
    DEFAULT_CONFIG,
    SmolConfig,
    get_config_path,
    load_config,
    save_config,
)


def test_default_config_fields() -> None:
    """Verify that all required fields are defined with correct default types."""
    cfg = SmolConfig()
    required_fields = [
        "trigger_key",
        "sizes",
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
    ]
    for field in required_fields:
        assert hasattr(cfg, field), f"Missing required field: {field}"
        assert field in DEFAULT_CONFIG

    assert cfg.trigger_key == "Super"
    assert cfg.sizes == [
        20_000,
        50_000,
        100_000,
        200_000,
        500_000,
        1_000_000,
        2_000_000,
    ]
    assert cfg.output_mode in ("next to original", "next_to_original")
    assert isinstance(cfg.output_folder, str)
    assert cfg.naming_pattern == "{name}_{size}{ext}"
    assert cfg.keep_format is True
    assert cfg.allow_convert is False
    assert cfg.strip_metadata is True
    assert cfg.min_side == 200
    assert cfg.reduce_motion is False
    assert cfg.theme in ("dark", "system")
    assert cfg.autostart is False


def test_missing_file_returns_defaults(tmp_path: Path) -> None:
    """Missing config file should return default configuration without crashing."""
    cfg_path = tmp_path / "nonexistent" / "config.toml"
    cfg = load_config(cfg_path)

    assert isinstance(cfg, SmolConfig)
    assert cfg.trigger_key == "Super"
    assert cfg.sizes == [
        20_000,
        50_000,
        100_000,
        200_000,
        500_000,
        1_000_000,
        2_000_000,
    ]
    assert cfg.min_side == 200
    assert not cfg_path.exists()


def test_corrupted_file_falls_back_with_warning(tmp_path: Path) -> None:
    """A corrupted file must fall back to defaults and warn, never crashing."""
    cfg_path = tmp_path / "corrupted.toml"
    cfg_path.write_text(
        "invalid [toml content ::: syntax error\nkey == val", encoding="utf-8"
    )

    with pytest.warns(UserWarning, match="(?i)corrupt|invalid|error"):
        cfg = load_config(cfg_path)

    assert cfg.trigger_key == "Super"
    assert cfg.min_side == 200
    assert cfg.sizes == [
        20_000,
        50_000,
        100_000,
        200_000,
        500_000,
        1_000_000,
        2_000_000,
    ]


def test_partial_file_merges_with_defaults(tmp_path: Path) -> None:
    """A partial config file should load valid fields and fill defaults for rest."""
    cfg_path = tmp_path / "partial.toml"
    content = """
trigger_key = "Ctrl+Alt"
min_side = 350
reduce_motion = true
"""
    cfg_path.write_text(content, encoding="utf-8")

    cfg = load_config(cfg_path)

    assert cfg.trigger_key == "Ctrl+Alt"
    assert cfg.min_side == 350
    assert cfg.reduce_motion is True
    # Non-specified fields should retain defaults
    assert cfg.sizes == [
        20_000,
        50_000,
        100_000,
        200_000,
        500_000,
        1_000_000,
        2_000_000,
    ]
    assert cfg.output_mode in ("next to original", "next_to_original")
    assert cfg.naming_pattern == "{name}_{size}{ext}"
    assert cfg.keep_format is True
    assert cfg.allow_convert is False
    assert cfg.strip_metadata is True
    assert cfg.autostart is False


def test_bad_field_values_fallback_to_defaults(tmp_path: Path) -> None:
    """Invalid field values/types should warn and fall back to defaults."""
    cfg_path = tmp_path / "bad_values.toml"
    content = """
trigger_key = 12345
sizes = "not a list"
output_mode = "cloud_upload"
output_folder = 999
naming_pattern = ""
keep_format = "yes"
allow_convert = 1
strip_metadata = "true"
min_side = -50
reduce_motion = "no"
theme = "neon_rainbow"
autostart = "always"
"""
    cfg_path.write_text(content, encoding="utf-8")

    with pytest.warns(UserWarning) as records:
        cfg = load_config(cfg_path)

    # Check that warnings were emitted for the bad fields
    assert len(records) >= 8

    # Check that all fields safely fell back to defaults
    assert cfg.trigger_key == "Super"
    assert cfg.sizes == [
        20_000,
        50_000,
        100_000,
        200_000,
        500_000,
        1_000_000,
        2_000_000,
    ]
    assert cfg.output_mode in ("next to original", "next_to_original")
    assert cfg.output_folder == ""
    assert cfg.naming_pattern == "{name}_{size}{ext}"
    assert cfg.keep_format is True
    assert cfg.allow_convert is False
    assert cfg.strip_metadata is True
    assert cfg.min_side == 200
    assert cfg.reduce_motion is False
    assert cfg.theme in ("dark", "system")
    assert cfg.autostart is False


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    """Saving and re-loading custom configuration produces exact match."""
    cfg_path = tmp_path / "smol" / "config.toml"

    custom_cfg = SmolConfig(
        trigger_key="Right Alt",
        sizes=[50_000, 150_000, 300_000],
        output_mode="fixed folder",
        output_folder=str(tmp_path / "shrunk"),
        naming_pattern="{name}_shrunk.{ext}",
        keep_format=False,
        allow_convert=True,
        strip_metadata=False,
        min_side=150,
        reduce_motion=True,
        theme="light",
        autostart=True,
    )

    save_config(custom_cfg, cfg_path)
    assert cfg_path.exists()

    loaded = load_config(cfg_path)
    assert loaded.trigger_key == "Right Alt"
    assert loaded.sizes == [50_000, 150_000, 300_000]
    assert loaded.output_mode in ("fixed folder", "fixed_folder")
    assert loaded.output_folder == str(tmp_path / "shrunk")
    assert loaded.naming_pattern == "{name}_shrunk.{ext}"
    assert loaded.keep_format is False
    assert loaded.allow_convert is True
    assert loaded.strip_metadata is False
    assert loaded.min_side == 150
    assert loaded.reduce_motion is True
    assert loaded.theme == "light"
    assert loaded.autostart is True


def test_save_dict_and_dict_access(tmp_path: Path) -> None:
    """SmolConfig supports dict-like access and save_config accepts a dict."""
    cfg_path = tmp_path / "dict_test.toml"
    cfg = SmolConfig()

    assert cfg["trigger_key"] == "Super"
    assert cfg.get("min_side") == 200
    assert "reduce_motion" in cfg

    cfg["min_side"] = 400
    assert cfg.min_side == 400

    d = cfg.to_dict()
    assert isinstance(d, dict)
    assert d["min_side"] == 400

    save_config({"min_side": 500, "trigger_key": "Ctrl+Alt"}, cfg_path)
    loaded = load_config(cfg_path)
    assert loaded.min_side == 500
    assert loaded.trigger_key == "Ctrl+Alt"


def test_get_config_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test get_config_path honoring SMOL_CONFIG_PATH, XDG_CONFIG_HOME, and fallback."""
    custom = tmp_path / "my_custom.toml"
    monkeypatch.setenv("SMOL_CONFIG_PATH", str(custom))
    assert get_config_path() == custom

    monkeypatch.delenv("SMOL_CONFIG_PATH", raising=False)
    xdg = tmp_path / "xdg_config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    assert get_config_path() == xdg / "smol" / "config.toml"

    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    home = tmp_path / "fake_home"
    monkeypatch.setenv("HOME", str(home))
    assert get_config_path() == home / ".config" / "smol" / "config.toml"
