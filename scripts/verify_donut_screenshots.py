"""Verification script for schema v1, config migration, and Donut ring screenshots.

Captures:
- Verification of legacy config.toml migration and config.toml.bak creation
- Screenshots of donut overlay for:
  1. 1.2 MB file in Classic mode and Smart mode
  2. 12 KB file in Classic mode and Smart mode
  3. 40 MB file in Classic mode and Smart mode
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

# Ensure Qt runs offscreen
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PIL import Image
from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from smol.config import SmolConfig, load_config, save_config
from smol.ui.donut_window import DonutWindow, _apply_blur


def test_legacy_migration() -> None:
    """Verify loading legacy unversioned config.toml creates .bak and preserves keys."""
    print("=" * 60)
    print("VERIFICATION: Legacy config.toml migration & backup")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        cfg_path = tmp_path / "config.toml"
        bak_path = tmp_path / "config.toml.bak"

        legacy_toml = (
            'trigger_key = "Ctrl+Alt"\n'
            "sizes = [50000, 100000, 200000]\n"
            "custom_sizes = [75000, 150000]\n"
            'custom_user_setting = "preserved_value_xyz"\n'
        )
        cfg_path.write_text(legacy_toml, encoding="utf-8")

        # Load legacy config (triggers automatic schema v1 migration and backup)
        cfg = load_config(cfg_path)

        assert bak_path.exists(), "config.toml.bak was not created!"
        bak_content = bak_path.read_text(encoding="utf-8")
        assert bak_content == legacy_toml, "Backup content does not match original!"

        assert cfg.config_version == 1
        assert cfg.trigger_key == "Ctrl+Alt"
        assert cfg.sizes.ladder == [50_000, 100_000, 200_000]
        assert cfg.sizes.recents == [75_000, 150_000]
        assert cfg._extra_keys.get("custom_user_setting") == "preserved_value_xyz"

        print(f"✓ Created backup file: {bak_path}")
        print(f"✓ Migrated schema: config_version={cfg.config_version}")
        extra = cfg._extra_keys.get("custom_user_setting")
        print(f"✓ Preserved unknown key: custom_user_setting={extra}")
        print("Migration check PASSED.\n")


def create_wallpaper(width: int = 1000, height: int = 750) -> QPixmap:
    """Generate sleek modern dark wallpaper canvas."""
    dark_pix = QPixmap(width, height)
    painter = QPainter(dark_pix)
    grad = QLinearGradient(0, 0, width, height)
    grad.setColorAt(0.0, QColor(15, 23, 42))
    grad.setColorAt(0.5, QColor(30, 41, 59))
    grad.setColorAt(1.0, QColor(15, 23, 42))
    painter.fillRect(0, 0, width, height, grad)
    painter.end()
    return dark_pix


def capture_donut(
    window: DonutWindow,
    wallpaper: QPixmap,
    canvas_w: int = 1000,
    canvas_h: int = 750,
) -> QPixmap:
    """Render DonutWindow over wallpaper with blurred backdrop."""
    dw = window.width()
    dh = window.height()
    donut_x = (canvas_w - dw) // 2
    donut_y = (canvas_h - dh) // 2

    sub_rect = wallpaper.copy(donut_x, donut_y, dw, dh)
    window._blurred_desktop = _apply_blur(sub_rect, radius=14)

    donut_pixmap = QPixmap(dw, dh)
    donut_pixmap.fill(Qt.GlobalColor.transparent)
    window.render(donut_pixmap)

    canvas = QPixmap(canvas_w, canvas_h)
    painter = QPainter(canvas)
    painter.drawPixmap(0, 0, wallpaper)
    painter.drawPixmap(donut_x, donut_y, donut_pixmap)
    painter.end()

    # Crop with 40px margin
    margin = 40
    cx = max(0, donut_x - margin)
    cy = max(0, donut_y - margin)
    cw = min(canvas_w - cx, dw + margin * 2)
    ch = min(canvas_h - cy, dh + margin * 2)
    return canvas.copy(cx, cy, cw, ch)


def wait_for_floor(window: DonutWindow, timeout_ms: int = 2000) -> None:
    """Wait for FloorWorker to complete in event loop."""
    if window.floor_worker is not None and window.floor_worker.isRunning():
        loop = QEventLoop()
        window.floor_worker.finished.connect(loop.quit)
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()


def generate_test_file(path: Path, target_bytes: int) -> None:
    """Create a valid JPEG file of approximately target_bytes."""
    if path.exists() and abs(path.stat().st_size - target_bytes) < 0.1 * target_bytes:
        return

    # Approximate dimension to generate target size
    # 1 byte ~ 1-2 pixels for JPEG q85
    dim = max(100, int((target_bytes / 2) ** 0.5))
    dim = min(dim, 5000)

    img = Image.new("RGB", (dim, dim), color=(70, 110, 160))
    img.save(path, format="JPEG", quality=85)

    # If larger file needed (e.g. 40 MB), append dummy bytes or increase dimension
    cur = path.stat().st_size
    if cur < target_bytes:
        with open(path, "ab") as f:
            f.write(b"\x00" * (target_bytes - cur))


def main() -> None:
    test_legacy_migration()

    app = QApplication.instance() or QApplication([])

    samples_dir = Path("tests/samples")
    out_dir = Path("screenshots/verification")
    out_dir.mkdir(parents=True, exist_ok=True)

    wallpaper = create_wallpaper()

    scratch_dir = Path("scratch_verify")
    scratch_dir.mkdir(exist_ok=True)

    # 1. 1.2 MB file (portrait.jpg, ~1.24 MB)
    file_1_2mb = samples_dir / "portrait.jpg"

    # 2. 12 KB file
    file_12kb = scratch_dir / "tiny_12kb.jpg"
    generate_test_file(file_12kb, 12_000)

    # 3. 40 MB file
    file_40mb = scratch_dir / "photo_40mb.jpg"
    generate_test_file(file_40mb, 40_000_000)

    test_cases = [
        ("1.2mb", file_1_2mb),
        ("12kb", file_12kb),
        ("40mb", file_40mb),
    ]

    print("=" * 60)
    print("VERIFICATION: Capturing Donut Overlay Screenshots")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        for name, file_path in test_cases:
            file_sz = file_path.stat().st_size
            print(f"\nProcessing {name.upper()} file: {file_path.name} ({file_sz:,} B)")

            for mode in ("classic", "smart"):
                cfg_file = tmp_path / f"config_{mode}.toml"
                cfg = SmolConfig()
                cfg.suggest.mode = mode
                save_config(cfg, cfg_file)

                win = DonutWindow(files=[file_path], config_path=cfg_file)
                win.show()
                wait_for_floor(win)

                shot = capture_donut(win, wallpaper)
                out_file = out_dir / f"donut_{name}_{mode}.png"
                shot.save(str(out_file))

                segs = [s.label for s in win.segments]
                dimmed = [s.label for s in win.segments if not s.enabled]
                print(
                    f"  [{mode.upper():7s}] Saved: {out_file.name} "
                    f"| Segments ({len(segs)}): {segs} "
                    f"| Dimmed: {dimmed}"
                )

                win.close()
                win.deleteLater()
                app.processEvents()

    # Cleanup temporary 40MB file
    if scratch_dir.exists():
        shutil.rmtree(scratch_dir)

    print("\n" + "=" * 60)
    print(f"All screenshots successfully saved to: {out_dir.resolve()}")
    print("=" * 60)


if __name__ == "__main__":
    main()
