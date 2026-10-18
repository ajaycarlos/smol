"""Script to capture DonutWindow in 5 states on light and dark wallpapers.

States:
1. idle: standard portrait image, default segments.
2. hover: hovering over 100 KB segment with active prediction.
3. long filename: very long hostile filename.
4. tiny screen (800x600): centered on an 800x600 desktop canvas.
5. many segments dimmed: small image (~30 KB) where 50 KB..2 MB are dimmed.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# Ensure Qt runs offscreen
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import QApplication

from smol.ui.donut_window import DonutWindow, _apply_blur
from smol.ui.prediction import Prediction


def create_wallpapers(width: int = 1000, height: int = 750) -> tuple[QPixmap, QPixmap]:
    """Generate realistic light and dark desktop wallpapers."""
    # Light wallpaper: modern bright desktop with soft cool-gray gradients
    light_pix = QPixmap(width, height)
    light_painter = QPainter(light_pix)
    grad_light = QLinearGradient(0, 0, width, height)
    grad_light.setColorAt(0.0, QColor(245, 247, 250))  # Off-white / light slate
    grad_light.setColorAt(0.4, QColor(230, 235, 245))  # Soft sky silver
    grad_light.setColorAt(1.0, QColor(215, 222, 232))  # Cool mist
    light_painter.fillRect(0, 0, width, height, grad_light)

    # Add subtle desktop window / dock shapes on light wallpaper
    light_painter.setPen(Qt.PenStyle.NoPen)
    light_painter.setBrush(QColor(255, 255, 255, 160))
    light_painter.drawRoundedRect(40, 40, 280, 200, 8, 8)
    light_painter.setBrush(QColor(200, 210, 225, 120))
    light_painter.drawRoundedRect(width - 320, 100, 280, 350, 8, 8)
    # Bottom dock/panel
    light_painter.setBrush(QColor(255, 255, 255, 220))
    light_painter.drawRect(0, height - 40, width, 40)
    light_painter.end()

    # Dark wallpaper: sleek midnight blue / obsidian gradient
    dark_pix = QPixmap(width, height)
    dark_painter = QPainter(dark_pix)
    grad_dark = QLinearGradient(0, 0, width, height)
    grad_dark.setColorAt(0.0, QColor(15, 23, 42))  # Midnight slate (#0f172a)
    grad_dark.setColorAt(0.5, QColor(30, 41, 59))  # Slate (#1e293b)
    grad_dark.setColorAt(1.0, QColor(10, 15, 28))  # Deep abyss
    dark_painter.fillRect(0, 0, width, height, grad_dark)

    # Add subtle shapes on dark wallpaper
    dark_painter.setPen(Qt.PenStyle.NoPen)
    dark_painter.setBrush(QColor(51, 65, 85, 90))
    dark_painter.drawRoundedRect(50, 50, 300, 220, 8, 8)
    dark_painter.setBrush(QColor(71, 85, 105, 70))
    dark_painter.drawRoundedRect(width - 340, 120, 300, 360, 8, 8)
    # Bottom panel
    dark_painter.setBrush(QColor(15, 23, 42, 230))
    dark_painter.drawRect(0, height - 40, width, 40)
    dark_painter.end()

    return light_pix, dark_pix


def capture_donut_composite(
    window: DonutWindow,
    wallpaper: QPixmap,
    canvas_w: int,
    canvas_h: int,
    crop_centered: bool = True,
) -> QPixmap:
    """Render DonutWindow on top of wallpaper with proper desktop blur snapshot."""
    dw = window.width()
    dh = window.height()

    # Center donut on the canvas
    donut_x = (canvas_w - dw) // 2
    donut_y = (canvas_h - dh) // 2

    # Extract exact wallpaper region under the donut
    sub_rect = wallpaper.copy(donut_x, donut_y, dw, dh)
    # Blur the crop exactly like real desktop capture
    window._blurred_desktop = _apply_blur(sub_rect, radius=14)

    # Render donut widget onto transparent pixmap
    donut_pixmap = QPixmap(dw, dh)
    donut_pixmap.fill(Qt.GlobalColor.transparent)
    window.render(donut_pixmap)

    # Composite onto wallpaper canvas
    canvas = QPixmap(canvas_w, canvas_h)
    painter = QPainter(canvas)
    painter.drawPixmap(0, 0, wallpaper)
    painter.drawPixmap(donut_x, donut_y, donut_pixmap)
    painter.end()

    if crop_centered:
        # Crop with 40px margin around donut for crisp detail view
        margin = 40
        cx = max(0, donut_x - margin)
        cy = max(0, donut_y - margin)
        cw = min(canvas_w - cx, dw + margin * 2)
        ch = min(canvas_h - cy, dh + margin * 2)
        return canvas.copy(cx, cy, cw, ch)

    return canvas


def main(output_dir: Path) -> None:
    _app = QApplication.instance() or QApplication([])

    samples_dir = Path("tests/samples")
    portrait_jpg = samples_dir / "portrait.jpg"
    small_jpg = samples_dir / "already_small.jpg"

    # Create temporary long filename image
    long_name = (
        "IMG_2026_scenic_mountain_vacation_panorama_"
        "with_friends_and_family_very_long_name_final_version.jpg"
    )
    long_filename_path = samples_dir / long_name
    if not long_filename_path.exists():
        shutil.copy(portrait_jpg, long_filename_path)

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Generate Wallpapers
    light_wp, dark_wp = create_wallpapers(1000, 750)
    light_wp_tiny, dark_wp_tiny = create_wallpapers(800, 600)

    pred_100k = Prediction(
        target_bytes=100_000,
        ok=True,
        text="~99.5 KB, 470×627",
        final_bytes=99512,
        width=470,
        height=627,
    )

    states = [
        ("idle", [portrait_jpg], None, None),
        ("hover", [portrait_jpg], 2, pred_100k),
        ("long_filename", [long_filename_path], None, None),
        ("many_dimmed", [small_jpg], None, None),
    ]

    for state_name, files, hover_idx, prediction in states:
        for theme, wp in [("light", light_wp), ("dark", dark_wp)]:
            win = DonutWindow(files)
            win._hovered_idx = hover_idx
            win._current_prediction = prediction

            # Crop view around donut
            shot = capture_donut_composite(win, wp, 1000, 750, crop_centered=True)
            out_file = output_dir / f"{state_name}_{theme}.png"
            shot.save(str(out_file))
            print(f"Saved: {out_file}")
            win.close()

    # State 4: Tiny screen (800x600) - capture FULL screen with compact scaling
    for theme, wp in [("light", light_wp_tiny), ("dark", dark_wp_tiny)]:
        win = DonutWindow([portrait_jpg])
        win.adapt_compact_size(340, 68.0, 156.0)
        shot_full = capture_donut_composite(win, wp, 800, 600, crop_centered=False)
        out_file = output_dir / f"tiny_screen_800x600_{theme}.png"
        shot_full.save(str(out_file))
        print(f"Saved: {out_file}")
        win.close()

    # Clean up temporary file
    if long_filename_path.exists():
        long_filename_path.unlink()

    print("All screenshots generated successfully.")


if __name__ == "__main__":
    import sys

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("screenshots/after")
    main(out)
