
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from smol.config import SmolConfig, save_config
from smol.ui.donut_window import DonutWindow


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_donut_classic_mode_suggest_options_max_8(app, samples_dir, tmp_path):
    """Donut in classic mode has at most 8 segments with Custom... last."""
    cfg_file = tmp_path / "config.toml"
    cfg = SmolConfig()
    cfg.suggest.mode = "classic"
    # Even if ladder had many entries, it's capped and max segments is 8
    cfg.sizes.ladder = [20_000, 50_000, 100_000, 200_000, 500_000, 1_000_000, 2_000_000]
    save_config(cfg, cfg_file)

    portrait = samples_dir / "portrait.jpg"
    window = DonutWindow(files=[portrait], config_path=cfg_file)

    assert len(window.segments) <= 8
    assert window.segments[-1].label == "Custom…"
    assert window.segments[-1].target_bytes is None
    window.close()


def test_donut_smart_mode_suggest_options_max_8(app, samples_dir, tmp_path):
    """Donut in smart mode has at most 8 segments with Custom... last."""
    cfg_file = tmp_path / "config.toml"
    cfg = SmolConfig()
    cfg.suggest.mode = "smart"
    cfg.suggest.max_segments = 6
    save_config(cfg, cfg_file)

    portrait = samples_dir / "portrait.jpg"
    window = DonutWindow(files=[portrait], config_path=cfg_file)

    assert len(window.segments) <= 8
    assert window.segments[-1].label == "Custom…"
    assert window.segments[-1].target_bytes is None
    window.close()


def test_donut_ineligible_dimmed_with_reason(app, samples_dir, tmp_path):
    """Ineligible entries larger than the file or below floor are dimmed with reason."""
    cfg_file = tmp_path / "config.toml"
    cfg = SmolConfig()
    save_config(cfg, cfg_file)

    tiny_file = samples_dir / "tiny.jpg"

    window = DonutWindow(files=[tiny_file], config_path=cfg_file)

    # In tiny file (<3 KB), 20 KB segment is larger than file -> ineligible
    seg_20k = next(s for s in window.segments if s.target_bytes == 20_000)
    assert not seg_20k.enabled
    assert seg_20k.reason is not None
    assert "larger than the file" in seg_20k.reason
    window.close()


def test_donut_async_floor_worker_updates_dimming(app, samples_dir, tmp_path):
    """FloorWorker estimates floor asynchronously and updates segment dimming."""
    cfg_file = tmp_path / "config.toml"
    cfg = SmolConfig()
    save_config(cfg, cfg_file)

    portrait = samples_dir / "portrait.jpg"
    window = DonutWindow(files=[portrait], config_path=cfg_file)
    window.show()

    assert hasattr(window, "floor_worker")
    if window.floor_worker is not None and window.floor_worker.isRunning():
        # Wait for floor worker to finish
        loop = QEventLoop()
        window.floor_worker.finished.connect(loop.quit)
        QTimer.singleShot(2000, loop.quit)
        loop.exec()

    assert window._floor_bytes is not None
    assert window._floor_bytes > 0
    window.close()
