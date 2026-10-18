"""Tests for smol integrate subcommand and file manager integration."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from smol.cli import main
from smol.integrations.manager import (
    INTEGRATION_SIZES,
    NemoIntegrator,
)


def test_nemo_install_creates_actions_and_submenu(tmp_path: Path):
    """Verify Nemo integration creates .nemo_action files and registers submenu."""
    actions_dir = tmp_path / "nemo" / "actions"
    config_dir = tmp_path / "config" / "nemo"
    integrator = NemoIntegrator(
        actions_dir=actions_dir,
        config_dir=config_dir,
        smol_bin="/custom/bin/smol",
    )

    result = integrator.install()
    assert result.ok is True
    assert "installed" in result.message.lower()

    # Verify 7 .nemo_action files created
    action_files = list(actions_dir.glob("smol_shrink_*.nemo_action"))
    assert len(action_files) == 7

    # Verify content of 100 KB action file
    action_100k = actions_dir / "smol_shrink_100kb.nemo_action"
    assert action_100k.exists()
    content = action_100k.read_text(encoding="utf-8")
    assert "[Nemo Action]" in content
    assert "Name=100 KB" in content
    assert "Exec=/custom/bin/smol shrink --notify --max 100KB -- %F" in content
    assert "Quote=double" in content
    assert "Extensions=jpg;jpeg;png;webp;heic;avif;" in content

    # Verify actions-tree.json created with submenu
    tree_file = config_dir / "actions-tree.json"
    assert tree_file.exists()
    tree_data = json.loads(tree_file.read_text(encoding="utf-8"))
    assert "toplevel" in tree_data
    assert len(tree_data["toplevel"]) == 1

    submenu = tree_data["toplevel"][0]
    assert submenu["uuid"] == "smol-shrink-submenu"
    assert submenu["type"] == "submenu"
    assert submenu["user-label"] == "Shrink to…"
    assert len(submenu["children"]) == 7
    child_uuids = [child["uuid"] for child in submenu["children"]]
    assert "smol_shrink_100kb.nemo_action" in child_uuids


def test_nemo_uninstall_removes_cleanly(tmp_path: Path):
    """Verify uninstallation removes all action files and actions-tree.json."""
    actions_dir = tmp_path / "nemo" / "actions"
    config_dir = tmp_path / "config" / "nemo"
    integrator = NemoIntegrator(
        actions_dir=actions_dir,
        config_dir=config_dir,
        smol_bin="/custom/bin/smol",
    )

    integrator.install()
    assert len(list(actions_dir.glob("smol_shrink_*.nemo_action"))) == 7
    assert (config_dir / "actions-tree.json").exists()

    uninst_res = integrator.uninstall()
    assert uninst_res.ok is True
    assert len(list(actions_dir.glob("smol_shrink_*.nemo_action"))) == 0
    # Because tree had no other entries, it should be cleanly removed
    assert not (config_dir / "actions-tree.json").exists()


def test_preserves_existing_unrelated_actions(tmp_path: Path):
    """Verify existing third-party actions in actions-tree.json are preserved."""
    actions_dir = tmp_path / "nemo" / "actions"
    config_dir = tmp_path / "config" / "nemo"
    config_dir.mkdir(parents=True, exist_ok=True)

    # Pre-existing actions-tree.json with user's custom action
    existing_tree = {
        "toplevel": [
            {
                "uuid": "existing_user_action.nemo_action",
                "type": "action",
                "user-label": "User Custom Action",
            }
        ]
    }
    tree_file = config_dir / "actions-tree.json"
    tree_file.write_text(json.dumps(existing_tree), encoding="utf-8")

    # Pre-existing unrelated action file
    actions_dir.mkdir(parents=True, exist_ok=True)
    unrelated_file = actions_dir / "existing_user_action.nemo_action"
    unrelated_file.write_text("[Nemo Action]\nName=Custom\n", encoding="utf-8")

    integrator = NemoIntegrator(
        actions_dir=actions_dir,
        config_dir=config_dir,
        smol_bin="/custom/bin/smol",
    )

    # Install
    integrator.install()
    tree_data = json.loads(tree_file.read_text(encoding="utf-8"))
    assert len(tree_data["toplevel"]) == 2
    assert tree_data["toplevel"][0]["uuid"] == "existing_user_action.nemo_action"
    assert tree_data["toplevel"][1]["uuid"] == "smol-shrink-submenu"

    # Uninstall
    integrator.uninstall()
    assert unrelated_file.exists()
    assert tree_file.exists()
    tree_data_after = json.loads(tree_file.read_text(encoding="utf-8"))
    assert len(tree_data_after["toplevel"]) == 1
    assert tree_data_after["toplevel"][0]["uuid"] == "existing_user_action.nemo_action"


def test_hostile_filename_safety(tmp_path: Path):
    """Verify action commands use -- delimiter and double quotes."""
    actions_dir = tmp_path / "nemo" / "actions"
    config_dir = tmp_path / "config" / "nemo"
    integrator = NemoIntegrator(
        actions_dir=actions_dir,
        config_dir=config_dir,
        smol_bin="/usr/bin/smol",
    )
    integrator.install()

    for action_file in actions_dir.glob("*.nemo_action"):
        content = action_file.read_text(encoding="utf-8")
        # Must have Quote=double so Nemo quotes the paths
        assert "Quote=double" in content
        # Must have -- before %F so filenames starting with - are not parsed as flags
        assert "-- %F" in content


def test_integrate_status_output(tmp_path: Path):
    """Verify status reporting for uninstalled and installed states."""
    actions_dir = tmp_path / "nemo" / "actions"
    config_dir = tmp_path / "config" / "nemo"
    integrator = NemoIntegrator(
        actions_dir=actions_dir,
        config_dir=config_dir,
        smol_bin="/custom/bin/smol",
    )

    # Before install
    status = integrator.status()
    assert status.installed is False
    assert status.file_manager == "nemo"
    assert len(status.installed_sizes) == 0

    # After install
    integrator.install()
    status_after = integrator.status()
    assert status_after.installed is True
    assert len(status_after.installed_sizes) == len(INTEGRATION_SIZES)


def test_cli_integrate_commands(capsys, monkeypatch, tmp_path: Path):
    """Verify smol integrate CLI subcommands: status, install, uninstall."""
    actions_dir = tmp_path / "nemo" / "actions"
    config_dir = tmp_path / "config" / "nemo"

    # Patch get_integrator to use tmp_path
    mock_integrator = NemoIntegrator(
        actions_dir=actions_dir,
        config_dir=config_dir,
        smol_bin="/custom/bin/smol",
    )
    monkeypatch.setattr(
        "smol.cli.get_integrator",
        lambda fm=None: mock_integrator,
    )

    # 1. Status before install
    ret = main(["integrate", "status"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "not installed" in out.lower()

    # 2. Install
    ret = main(["integrate", "install"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "installed" in out.lower()

    # 3. Status after install
    ret = main(["integrate", "status"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "installed" in out.lower()
    assert "100 KB" in out

    # 4. Uninstall
    ret = main(["integrate", "uninstall"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "uninstalled" in out.lower()


def test_shrink_notify_integration(tmp_path: Path, monkeypatch):
    """Verify smol shrink --notify sends desktop notification with before/after."""
    # Create a small dummy image
    from PIL import Image

    img_path = tmp_path / "photo.jpg"
    im = Image.new("RGB", (300, 300), color="blue")
    im.save(img_path, format="JPEG")

    mock_run = MagicMock()
    monkeypatch.setattr("subprocess.run", mock_run)

    ret = main(["shrink", str(img_path), "--max", "20KB", "--notify"])
    assert ret == 0

    # Ensure notify-send was called
    notify_calls = [
        call.args[0]
        for call in mock_run.call_args_list
        if call.args and call.args[0] and call.args[0][0] == "notify-send"
    ]
    assert len(notify_calls) >= 1, "notify-send was not called with --notify flag"
    final_call = notify_calls[-1]
    # ["notify-send", "-u", "normal", "-a", "smol", "smol", "<body text>"]
    body = final_call[-1]
    assert "photo.jpg:" in body
    assert "→" in body


def test_shrink_notify_batch_and_failure(tmp_path: Path, monkeypatch):
    """Verify batch and failure notification contents."""
    from PIL import Image

    img1 = tmp_path / "img1.jpg"
    img2 = tmp_path / "img2.jpg"
    Image.new("RGB", (100, 100), color="red").save(img1, "JPEG")
    Image.new("RGB", (100, 100), color="green").save(img2, "JPEG")

    mock_run = MagicMock()
    monkeypatch.setattr("subprocess.run", mock_run)

    # Batch success
    ret = main(["shrink", str(img1), str(img2), "--max", "50KB", "--notify"])
    assert ret == 0
    notify_calls = [
        call.args[0]
        for call in mock_run.call_args_list
        if call.args and call.args[0] and call.args[0][0] == "notify-send"
    ]
    assert notify_calls[-1][-1] == "2 files shrunk"

    # Single failure honest engine message
    mock_run.reset_mock()
    bad_file = tmp_path / "missing.jpg"
    ret = main(["shrink", str(bad_file), "--max", "50KB", "--notify"])
    assert ret != 0
    fail_calls = [
        call.args[0]
        for call in mock_run.call_args_list
        if call.args and call.args[0] and call.args[0][0] == "notify-send"
    ]
    assert len(fail_calls) >= 1
    # Body must be the honest engine message (File not found)
    assert "not found" in fail_calls[-1][-1].lower()
