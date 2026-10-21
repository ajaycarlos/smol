from pathlib import Path

import pytest

from smol.core.config import (
    add_custom_size,
    get_config_path,
    get_custom_sizes,
    load_config,
    save_config,
)


def test_get_config_path_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    path = get_config_path()
    assert path == fake_home / ".config" / "smol" / "config.toml"


def test_get_config_path_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    xdg_dir = tmp_path / "custom_xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_dir))

    path = get_config_path()
    assert path == xdg_dir / "smol" / "config.toml"


def test_load_config_nonexistent(tmp_path: Path) -> None:
    config_file = tmp_path / "smol" / "config.toml"
    cfg = load_config(config_file)
    assert cfg == {"custom_sizes": [], "reduce_motion": False}
    assert not config_file.exists()


def test_save_and_load_config(tmp_path: Path) -> None:
    config_file = tmp_path / "smol" / "config.toml"
    data = {"custom_sizes": [75_000, 150_000]}
    save_config(data, config_file)

    assert config_file.exists()
    loaded = load_config(config_file)
    assert loaded["custom_sizes"] == [75_000, 150_000]


def test_load_config_corrupted(tmp_path: Path) -> None:
    config_file = tmp_path / "smol" / "config.toml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("invalid [[ toml content ///", encoding="utf-8")

    with pytest.warns(UserWarning, match="Failed to read or parse config"):
        cfg = load_config(config_file)
    assert cfg == {"custom_sizes": [], "reduce_motion": False}


def test_add_custom_size_remember_last_three(tmp_path: Path) -> None:
    config_file = tmp_path / "smol" / "config.toml"

    # Add 1st
    res1 = add_custom_size(75_000, config_file)
    assert res1 == [75_000]
    assert get_custom_sizes(config_file) == [75_000]

    # Add 2nd
    res2 = add_custom_size(150_000, config_file)
    assert res2 == [75_000, 150_000]

    # Add 3rd
    res3 = add_custom_size(300_000, config_file)
    assert res3 == [75_000, 150_000, 300_000]

    # Add 4th: should push out the oldest, keeping exactly last 3
    res4 = add_custom_size(600_000, config_file)
    assert res4 == [150_000, 300_000, 600_000]
    assert get_custom_sizes(config_file) == [150_000, 300_000, 600_000]


def test_add_custom_size_deduplicates(tmp_path: Path) -> None:
    config_file = tmp_path / "smol" / "config.toml"

    add_custom_size(75_000, config_file)
    add_custom_size(150_000, config_file)
    # already present, should move to most recent end
    add_custom_size(75_000, config_file)

    assert get_custom_sizes(config_file) == [150_000, 75_000]


def test_reduce_motion_default(tmp_path: Path) -> None:
    config_file = tmp_path / "smol" / "config.toml"
    from smol.core.config import get_reduce_motion

    assert get_reduce_motion(config_file) is False


def test_reduce_motion_save_and_load(tmp_path: Path) -> None:
    config_file = tmp_path / "smol" / "config.toml"
    from smol.core.config import get_reduce_motion

    cfg = load_config(config_file)
    cfg["reduce_motion"] = True
    save_config(cfg, config_file)

    assert get_reduce_motion(config_file) is True
    loaded = load_config(config_file)
    assert loaded["reduce_motion"] is True
