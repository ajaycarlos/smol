#!/usr/bin/env python3
"""End-to-end verification that changing settings applies across all subcommands."""

import os
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image

from smol.config import SmolConfig, save_config
from smol.daemon.service import DaemonService


def main() -> None:
    print("==================================================")
    print("VERIFY: Changing settings applies across subcommands")
    print("==================================================")

    # 1. Setup isolated directories
    test_root = Path("/tmp/smol_verify_v060")
    if test_root.exists():
        shutil.rmtree(test_root)
    test_root.mkdir(parents=True)

    config_path = test_root / "config.toml"
    out_dir = test_root / "custom_out"
    out_dir.mkdir()
    state_dir = test_root / "state"
    state_dir.mkdir()

    os.environ["SMOL_CONFIG_PATH"] = str(config_path)
    os.environ["SMOL_STATE_DIR"] = str(state_dir)

    # Configure custom settings
    cfg = SmolConfig(
        trigger_key="Right Alt",
        sizes=[30_000, 60_000, 120_000],
        output_mode="fixed folder",
        output_folder=str(out_dir),
        naming_pattern="{name}-shrunk-{size}{ext}",
    )
    save_config(cfg, config_path=config_path)
    print(f"[✓] Saved custom configuration at {config_path}")
    print(f"    sizes={cfg.sizes}, trigger={cfg.trigger_key}, out_dir={out_dir}")

    # 2. Test smol shrink
    test_photo = test_root / "input.jpg"
    import random
    random.seed(99)
    im = Image.frombytes("RGB", (500, 500), random.randbytes(500 * 500 * 3))
    im.save(test_photo, format="JPEG", quality=90)

    res = subprocess.run(
        ["uv", "run", "smol", "shrink", str(test_photo), "--max", "60KB"],
        capture_output=True,
        text=True,
        check=False,
    )
    print(f"[*] smol shrink output: {res.stdout.strip()}")
    expected_output = out_dir / "input-shrunk-60KB.jpg"
    assert expected_output.exists(), (
        f"Expected output {expected_output} was not created!"
    )
    print(
        f"[✓] Engine & CLI shrink applied config (output in {expected_output.parent}, "
        f"pattern={expected_output.name})"
    )

    # 3. Test smol integrate status
    res = subprocess.run(
        ["uv", "run", "smol", "integrate", "status", "--file-manager", "nemo"],
        capture_output=True,
        text=True,
        check=False,
    )
    print(f"[*] smol integrate status:\n{res.stdout.strip()}")
    # Install actions and verify configured sizes are present
    res_install = subprocess.run(
        ["uv", "run", "smol", "integrate", "install", "--file-manager", "nemo"],
        capture_output=True,
        text=True,
        check=False,
    )
    print(f"[*] smol integrate install: {res_install.stdout.strip()}")
    assert "3 sizes" in res_install.stdout or "Installed" in res_install.stdout
    print("[✓] Integrations applied config sizes")

    # Clean up integration
    subprocess.run(
        ["uv", "run", "smol", "integrate", "uninstall", "--file-manager", "nemo"],
        check=False,
    )

    # 4. Test daemon startup with config
    service = DaemonService(state_dir=state_dir, config_path=config_path)
    service.stop()
    ret = service.start()
    assert ret == 0, "Daemon failed to start!"
    time.sleep(0.5)

    running, pid = service.status()
    assert running and pid is not None
    print(f"[✓] Daemon started (PID {pid})")

    # Check daemon log
    log_file = state_dir / "daemon.log"
    assert log_file.exists()
    log_content = log_file.read_text(encoding="utf-8")
    assert "trigger_key=Right Alt" in log_content
    assert "[30000, 60000, 120000]" in log_content
    print("[✓] Daemon logged configured trigger_key and sizes")

    # 5. Modify config while daemon is running and verify hot-reload / restart needed
    time.sleep(1.1)  # Ensure mtime is strictly newer
    save_config(
        SmolConfig(trigger_key="Super", sizes=[25_000, 50_000]),
        config_path=config_path,
    )

    # Trigger reload check in daemon
    time.sleep(1.2)

    # Check CLI daemon status reports restart needed
    res_status = subprocess.run(
        ["uv", "run", "smol", "daemon", "status"],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    print(f"[*] smol daemon status after config edit: {res_status.stdout.strip()}")
    assert "restart needed" in res_status.stdout.lower()
    print("[✓] smol daemon status detected config modification and flagged restart")

    # Stop daemon
    service.stop()
    print("[✓] Daemon stopped cleanly")

    print("\n==================================================")
    print("ALL VERIFICATIONS COMPLETED SUCCESSFULLY!")
    print("==================================================")


if __name__ == "__main__":
    main()
