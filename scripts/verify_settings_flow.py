"""Verification script for smol settings workflow.

Tests:
1. Change trigger key and sizes in SettingsWindow and save.
2. Confirm config file is updated on disk.
3. Reload SettingsWindow to verify settings are read correctly.
4. Start the daemon, verify running status.
5. Check daemon logs show new trigger_key and sizes.
6. Verify DonutWindow picks up new sizes from config.
7. Stop the daemon cleanly.
"""

import sys
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

from smol.config import get_config_path, load_config
from smol.ui.donut_window import DonutWindow
from smol.ui.settings_window import SettingsWindow


def main() -> int:
    config_file = get_config_path()
    print(f"[*] Target config path: {config_file}")

    # Step 1: Open SettingsWindow, change trigger key and sizes, and save
    app = QApplication.instance()
    if app is None:
        app = QApplication(["verify_settings"])

    print("[*] Opening SettingsWindow...")
    win = SettingsWindow()
    print(f"    Initial trigger key: {win.key_capture.get_key()}")
    print(f"    Initial sizes: {win.size_editor.get_sizes()}")

    # Change trigger key
    new_key = "Ctrl+Alt"
    win.key_capture.set_key(new_key)
    print(f"    Updated trigger key to: {win.key_capture.get_key()}")

    # Change sizes
    new_sizes = [50_000, 75_000, 100_000, 200_000]
    win.size_editor.set_sizes(new_sizes)
    print(f"    Updated sizes to: {win.size_editor.get_sizes()}")

    # Save
    saved = win.save()
    assert saved, "SettingsWindow.save() failed!"
    print("[✓] Settings saved successfully via SettingsWindow.")
    win.deleteLater()
    app.processEvents()

    # Step 2: Confirm config file on disk
    loaded_cfg = load_config()
    print(
        f"[*] Loaded config: trigger_key={loaded_cfg.trigger_key}, "
        f"sizes={loaded_cfg.sizes}"
    )
    assert loaded_cfg.trigger_key == new_key, (
        f"Expected {new_key}, got {loaded_cfg.trigger_key}"
    )
    assert loaded_cfg.sizes == new_sizes, (
        f"Expected {new_sizes}, got {loaded_cfg.sizes}"
    )
    print("[✓] Config file on disk contains new values.")

    # Step 3: Open a fresh SettingsWindow and verify reload
    win2 = SettingsWindow()
    assert win2.key_capture.get_key() == new_key
    assert win2.size_editor.get_sizes() == new_sizes
    win2.deleteLater()
    app.processEvents()
    print("[✓] Reloaded SettingsWindow confirmed new trigger key and sizes.")

    # Step 4: Verify DonutWindow picks up the new sizes
    donut = DonutWindow(files=[Path("tests/samples/portrait.jpg")])
    primary_sizes = [s.target_bytes for s in donut.segments[: len(new_sizes)]]
    primary_labels = [s.label for s in donut.segments[: len(new_sizes)]]
    print(f"[*] DonutWindow segments: {primary_labels} (bytes: {primary_sizes})")
    assert primary_sizes == new_sizes, (
        f"Donut segments {primary_sizes} do not match new sizes {new_sizes}"
    )
    donut.deleteLater()
    app.processEvents()
    print("[✓] DonutWindow picked up new sizes across subcommands.")

    # Step 5: Test Daemon lifecycle with new config
    from smol.daemon.service import DaemonService, get_log_path

    print("[*] Starting daemon with updated settings...")
    daemon_service = DaemonService()
    # Stop any existing daemon first
    daemon_service.stop()

    start_ret = daemon_service.start()
    print(f"    Daemon start returned: {start_ret}")
    assert start_ret == 0, f"Daemon start failed with exit code {start_ret}"

    # Verify daemon status
    time.sleep(0.5)
    running, pid = daemon_service.status()
    print(f"[*] Daemon status: running={running}, pid={pid}")
    assert running and pid is not None, "Daemon is not running after start!"
    print(f"[✓] Daemon running with PID {pid}.")

    # Verify log output contains new trigger_key and sizes
    log_path = get_log_path()
    assert log_path.exists(), f"Log file {log_path} does not exist!"
    log_text = log_path.read_text(encoding="utf-8")
    print("[*] Verifying daemon log entries for new config...")
    assert "trigger_key=Ctrl+Alt" in log_text, (
        "Daemon log missing trigger_key=Ctrl+Alt!"
    )
    assert "[50000, 75000, 100000, 200000]" in log_text, (
        "Daemon log missing updated sizes!"
    )
    print("[✓] Daemon successfully logged new trigger_key=Ctrl+Alt and new sizes!")

    # Step 6: Stop daemon cleanly
    print("[*] Stopping daemon...")
    stop_ret = daemon_service.stop()
    print(f"    Daemon stop returned: {stop_ret}")
    running, _ = daemon_service.status()
    assert not running, "Daemon is still running after stop!"
    print("[✓] Daemon stopped cleanly.")

    print("\n==========================================")
    print("ALL SETTINGS VERIFICATION CHECKS PASSED!")
    print("==========================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
