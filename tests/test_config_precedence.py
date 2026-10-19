"""Tests for configuration precedence: CLI flag > config file > default."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from smol import cli
from smol.config import SmolConfig, save_config


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Provide an isolated config path for testing."""
    config_file = tmp_path / "config.toml"
    monkeypatch.setenv("SMOL_CONFIG_PATH", str(config_file))
    return config_file


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    """Create a test image file."""
    img_path = tmp_path / "test.jpg"
    im = Image.new("RGB", (400, 400), color="blue")
    im.save(img_path, format="JPEG")
    return img_path


def test_precedence_min_side(
    isolated_config: Path, sample_image: Path, monkeypatch: pytest.MonkeyPatch
):
    """Test min_side precedence: CLI flag > config file > default (200)."""
    # 1. Default: No config file, no CLI flag -> min_dim=200
    with patch("smol.cli.shrink_image") as mock_shrink:
        mock_shrink.return_value = MagicMock(
            ok=True,
            original_bytes=1000,
            final_bytes=800,
            width=200,
            height=200,
            scale=1.0,
            quality=80,
            steps=1,
            output_path=Path("out.jpg"),
            warning=None,
            error=None,
        )
        cli.shrink([str(sample_image), "--max", "50KB"])
        assert mock_shrink.call_args[1]["options"]["min_dim"] == 200

    # 2. Config file override: config specifies min_side = 320 -> min_dim=320
    save_config(SmolConfig(min_side=320), config_path=isolated_config)
    with patch("smol.cli.shrink_image") as mock_shrink:
        mock_shrink.return_value = MagicMock(
            ok=True,
            original_bytes=1000,
            final_bytes=800,
            width=320,
            height=320,
            scale=1.0,
            quality=80,
            steps=1,
            output_path=Path("out.jpg"),
            warning=None,
            error=None,
        )
        cli.shrink([str(sample_image), "--max", "50KB"])
        assert mock_shrink.call_args[1]["options"]["min_dim"] == 320

    # 3. CLI flag override: config has min_side = 320, CLI sets --min-side 150
    with patch("smol.cli.shrink_image") as mock_shrink:
        mock_shrink.return_value = MagicMock(
            ok=True,
            original_bytes=1000,
            final_bytes=800,
            width=150,
            height=150,
            scale=1.0,
            quality=80,
            steps=1,
            output_path=Path("out.jpg"),
            warning=None,
            error=None,
        )
        cli.shrink([str(sample_image), "--max", "50KB", "--min-side", "150"])
        assert mock_shrink.call_args[1]["options"]["min_dim"] == 150


def test_precedence_allow_convert(isolated_config: Path, sample_image: Path):
    """Test allow_convert precedence: CLI flag > config file > default (False)."""
    # 1. Default: allow_convert=False
    with patch("smol.cli.shrink_image") as mock_shrink:
        mock_shrink.return_value = MagicMock(
            ok=True,
            original_bytes=1000,
            final_bytes=800,
            width=200,
            height=200,
            scale=1.0,
            quality=80,
            steps=1,
            output_path=Path("out.jpg"),
            warning=None,
            error=None,
        )
        cli.shrink([str(sample_image), "--max", "50KB"])
        assert mock_shrink.call_args[1]["options"]["allow_convert"] is False

    # 2. Config file: allow_convert=True
    save_config(SmolConfig(allow_convert=True), config_path=isolated_config)
    with patch("smol.cli.shrink_image") as mock_shrink:
        mock_shrink.return_value = MagicMock(
            ok=True,
            original_bytes=1000,
            final_bytes=800,
            width=200,
            height=200,
            scale=1.0,
            quality=80,
            steps=1,
            output_path=Path("out.jpg"),
            warning=None,
            error=None,
        )
        cli.shrink([str(sample_image), "--max", "50KB"])
        assert mock_shrink.call_args[1]["options"]["allow_convert"] is True

    # 3. CLI flag: config has allow_convert=False, CLI specifies --allow-convert
    save_config(SmolConfig(allow_convert=False), config_path=isolated_config)
    with patch("smol.cli.shrink_image") as mock_shrink:
        mock_shrink.return_value = MagicMock(
            ok=True,
            original_bytes=1000,
            final_bytes=800,
            width=200,
            height=200,
            scale=1.0,
            quality=80,
            steps=1,
            output_path=Path("out.jpg"),
            warning=None,
            error=None,
        )
        cli.shrink([str(sample_image), "--max", "50KB", "--allow-convert"])
        assert mock_shrink.call_args[1]["options"]["allow_convert"] is True


def test_precedence_metadata(isolated_config: Path, sample_image: Path):
    """Test strip_metadata / keep-metadata precedence: CLI > config > default."""
    # 1. Default: strip_metadata=True
    with patch("smol.cli.shrink_image") as mock_shrink:
        mock_shrink.return_value = MagicMock(
            ok=True,
            original_bytes=1000,
            final_bytes=800,
            width=200,
            height=200,
            scale=1.0,
            quality=80,
            steps=1,
            output_path=Path("out.jpg"),
            warning=None,
            error=None,
        )
        cli.shrink([str(sample_image), "--max", "50KB"])
        assert mock_shrink.call_args[1]["options"]["strip_metadata"] is True

    # 2. Config file: strip_metadata=False -> options["strip_metadata"] is False
    save_config(SmolConfig(strip_metadata=False), config_path=isolated_config)
    with patch("smol.cli.shrink_image") as mock_shrink:
        mock_shrink.return_value = MagicMock(
            ok=True,
            original_bytes=1000,
            final_bytes=800,
            width=200,
            height=200,
            scale=1.0,
            quality=80,
            steps=1,
            output_path=Path("out.jpg"),
            warning=None,
            error=None,
        )
        cli.shrink([str(sample_image), "--max", "50KB"])
        assert mock_shrink.call_args[1]["options"]["strip_metadata"] is False

    # 3. CLI flag: config has strip_metadata=True, CLI passes --keep-metadata
    save_config(SmolConfig(strip_metadata=True), config_path=isolated_config)
    with patch("smol.cli.shrink_image") as mock_shrink:
        mock_shrink.return_value = MagicMock(
            ok=True,
            original_bytes=1000,
            final_bytes=800,
            width=200,
            height=200,
            scale=1.0,
            quality=80,
            steps=1,
            output_path=Path("out.jpg"),
            warning=None,
            error=None,
        )
        cli.shrink([str(sample_image), "--max", "50KB", "--keep-metadata"])
        assert mock_shrink.call_args[1]["options"]["strip_metadata"] is False


def test_precedence_out_dir(isolated_config: Path, sample_image: Path, tmp_path: Path):
    """Test out_dir precedence: CLI flag > config file > default."""
    custom_dir = tmp_path / "config_dest"
    custom_dir.mkdir()
    cli_dir = tmp_path / "cli_dest"
    cli_dir.mkdir()

    # 1. Default: out_dir=None
    with patch("smol.cli.shrink_image") as mock_shrink:
        mock_shrink.return_value = MagicMock(
            ok=True,
            original_bytes=1000,
            final_bytes=800,
            width=200,
            height=200,
            scale=1.0,
            quality=80,
            steps=1,
            output_path=Path("out.jpg"),
            warning=None,
            error=None,
        )
        cli.shrink([str(sample_image), "--max", "50KB"])
        assert mock_shrink.call_args[1]["options"]["out_dir"] is None

    # 2. Config file: fixed folder
    save_config(
        SmolConfig(output_mode="fixed folder", output_folder=str(custom_dir)),
        config_path=isolated_config,
    )
    with patch("smol.cli.shrink_image") as mock_shrink:
        mock_shrink.return_value = MagicMock(
            ok=True,
            original_bytes=1000,
            final_bytes=800,
            width=200,
            height=200,
            scale=1.0,
            quality=80,
            steps=1,
            output_path=Path("out.jpg"),
            warning=None,
            error=None,
        )
        cli.shrink([str(sample_image), "--max", "50KB"])
        assert mock_shrink.call_args[1]["options"]["out_dir"] == str(custom_dir)

    # 3. CLI flag overrides config file
    with patch("smol.cli.shrink_image") as mock_shrink:
        mock_shrink.return_value = MagicMock(
            ok=True,
            original_bytes=1000,
            final_bytes=800,
            width=200,
            height=200,
            scale=1.0,
            quality=80,
            steps=1,
            output_path=Path("out.jpg"),
            warning=None,
            error=None,
        )
        cli.shrink([str(sample_image), "--max", "50KB", "--out-dir", str(cli_dir)])
        assert mock_shrink.call_args[1]["options"]["out_dir"] == str(cli_dir)
