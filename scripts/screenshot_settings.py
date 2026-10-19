"""Take native PySide6 screenshots of SettingsWindow on active display."""

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QScrollArea

from smol.ui.settings_window import SettingsWindow


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv[:1])

    win1 = SettingsWindow()
    win1.show()

    out1 = Path("settings_window.png").resolve()
    out2 = Path("settings_window_conflict.png").resolve()
    out3 = Path("settings_window_scrolled.png").resolve()

    def do_grab_step3() -> None:
        pix3 = win1.grab()
        pix3.save(str(out3), "PNG")
        print(f"Scrolled screenshot saved to {out3} ({pix3.width()}x{pix3.height()})")
        win1.close()
        app.quit()

    def capture_step3() -> None:
        scroll = win1.findChild(QScrollArea)
        if scroll:
            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        QTimer.singleShot(150, do_grab_step3)

    def do_grab_step2() -> None:
        pix2 = win1.grab()
        pix2.save(str(out2), "PNG")
        print(f"Conflict screenshot saved to {out2} ({pix2.width()}x{pix2.height()})")
        QTimer.singleShot(150, capture_step3)

    def capture_step2() -> None:
        win1.key_capture.set_key("Ctrl")
        win1.size_editor.list_widget.setCurrentRow(2)
        QTimer.singleShot(150, do_grab_step2)

    def capture_step1() -> None:
        pix1 = win1.grab()
        pix1.save(str(out1), "PNG")
        print(f"Default screenshot saved to {out1} ({pix1.width()}x{pix1.height()})")
        QTimer.singleShot(150, capture_step2)

    QTimer.singleShot(250, capture_step1)
    app.exec()


if __name__ == "__main__":
    main()
