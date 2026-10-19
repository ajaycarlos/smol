"""Tests verifying that setting changes in smol/config.py apply across subcommands."""

from pathlib import Path

import pytest
from PIL import Image

from smol.config import SmolConfig, save_config
from smol.core.image import shrink_image
from smol.core.paths import output_path
from smol.integrations.manager import NemoIntegrator, get_integration_sizes
from smol.ui.donut_window import DonutWindow, build_segment_config


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Provide an isolated config path for testing."""
    config_file = tmp_path / "config.toml"
    monkeypatch.setenv("SMOL_CONFIG_PATH", str(config_file))
    return config_file


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    """Create a test image file (>50KB) that requires shrinking."""
    img_path = tmp_path / "photo.jpg"
    import random

    random.seed(42)
    im = Image.frombytes("RGB", (600, 600), random.randbytes(600 * 600 * 3))
    im.save(img_path, format="JPEG", quality=90)
    return img_path


def test_engine_reads_custom_naming_pattern_and_output_folder(
    isolated_config: Path, sample_image: Path, tmp_path: Path
):
    """Core engine and output_path use naming_pattern and output_folder from config."""
    custom_dest = tmp_path / "shrunk_files"
    custom_dest.mkdir()

    cfg = SmolConfig(
        output_mode="fixed folder",
        output_folder=str(custom_dest),
        naming_pattern="{name}-tiny-{size}{ext}",
    )
    save_config(cfg, config_path=isolated_config)

    # 1. output_path with no explicit pattern/out_dir should read from config
    out = output_path(sample_image, 50_000)
    assert out.parent == custom_dest
    assert out.name == "photo-tiny-50KB.jpg"

    # 2. shrink_image with empty options should write to custom_dest with custom pattern
    res = shrink_image(sample_image, 50_000)
    assert res.ok is True
    assert res.output_path is not None
    assert res.output_path.parent == custom_dest
    assert res.output_path.name == "photo-tiny-50KB.jpg"
    assert res.output_path.exists()


def test_donut_reads_custom_sizes_and_motion(isolated_config: Path, qapp):
    """DonutWindow and build_segment_config load sizes and reduce_motion from config."""
    cfg = SmolConfig(
        sizes=[35_000, 75_000, 150_000],
        reduce_motion=True,
    )
    save_config(cfg, config_path=isolated_config)

    segments = build_segment_config(config_path=isolated_config)
    assert segments == [
        ("35 KB", 35_000),
        ("75 KB", 75_000),
        ("150 KB", 150_000),
        ("Custom…", None),
    ]

    donut = DonutWindow(files=[], config_path=isolated_config)
    assert donut.reduce_motion is True
    labels = [s.label for s in donut.segments]
    assert labels == ["35 KB", "75 KB", "150 KB", "Custom…"]
    donut.close()


def test_integrations_read_custom_sizes(isolated_config: Path, tmp_path: Path):
    """Integrators generate action entries based on sizes in smol.config."""
    cfg = SmolConfig(sizes=[40_000, 80_000])
    save_config(cfg, config_path=isolated_config)

    sizes = get_integration_sizes(config_path=isolated_config)
    assert len(sizes) == 2
    assert sizes[0] == ("40KB", "40 KB", "40kb")
    assert sizes[1] == ("80KB", "80 KB", "80kb")

    # Nemo integrator creates only the configured sizes
    nemo_actions = tmp_path / "nemo/actions"
    nemo_config = tmp_path / "nemo/config"
    integrator = NemoIntegrator(
        actions_dir=nemo_actions, config_dir=nemo_config, config_path=isolated_config
    )
    res = integrator.install()
    assert res.ok is True
    assert len(res.installed_files) == 3  # actions-tree.json + 2 .nemo_action files
    assert (nemo_actions / "smol_shrink_40kb.nemo_action").exists()
    assert (nemo_actions / "smol_shrink_80kb.nemo_action").exists()
    assert not (nemo_actions / "smol_shrink_20kb.nemo_action").exists()
