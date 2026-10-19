from pathlib import Path
from unittest.mock import MagicMock, patch

from smol.cli import main


def test_cli_donut_missing_files_flag(capsys):
    ret = main(["donut"])
    assert ret == 2
    err = capsys.readouterr().err
    assert "--files" in err or "required" in err


def test_cli_donut_nonexistent_file(capsys):
    ret = main(["donut", "--files", "/path/that/does/not/exist.jpg"])
    assert ret in (1, 2)
    err = capsys.readouterr().err
    assert "File not found" in err or "does not exist" in err


def test_cli_donut_help(capsys):
    ret = main(["donut", "--help"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "smol donut" in out
    assert "--files" in out


def test_cli_donut_successful_selection(samples_dir, monkeypatch, capsys):
    portrait = samples_dir / "portrait.jpg"

    # Mock DonutWindow execution: simulate selecting "100 KB"
    mock_window = MagicMock()
    mock_window.selected_size = "100 KB"

    def fake_exec(self):
        # Trigger the on_select callback if provided
        if self.on_select:
            self.on_select("100 KB")
        return 0

    with patch("smol.ui.donut_window.DonutWindow.run_overlay", fake_exec):
        ret = main(["donut", "--files", str(portrait)])

    assert ret == 0
    out = capsys.readouterr().out
    assert "100 KB" in out


def test_cli_donut_mixed_files(samples_dir, tmp_path, capsys):
    a_jpg = tmp_path / "a.jpg"
    b_png = tmp_path / "b.png"
    c_txt = tmp_path / "c.txt"

    import shutil

    shutil.copy(samples_dir / "portrait.jpg", a_jpg)
    shutil.copy(samples_dir / "screenshot.png", b_png)
    c_txt.write_text("Plain text file")

    captured_window = None

    def fake_run(self):
        nonlocal captured_window
        captured_window = self
        if self.on_select:
            self.on_select("100 KB")
        return 0

    with patch("smol.ui.donut_window.DonutWindow.run_overlay", fake_run):
        ret = main(["donut", "--files", str(a_jpg), str(b_png), str(c_txt)])

    assert ret == 0
    assert captured_window is not None
    assert captured_window.file_name == "3 files"
    assert len(captured_window.file_paths) == 3


def test_cli_donut_demo_flag(capsys):
    captured_window = None

    def fake_run(self):
        nonlocal captured_window
        captured_window = self
        if self.on_select:
            self.on_select("100 KB")
        return 0

    with patch("smol.ui.donut_window.DonutWindow.run_overlay", fake_run):
        ret = main(["donut", "--demo"])

    assert ret == 0
    assert captured_window is not None
    assert len(captured_window.file_paths) == 1
    demo_file = captured_window.file_paths[0]
    assert demo_file.exists()
    assert demo_file.stat().st_size > 0


def test_cli_donut_demo_fallback_generator(tmp_path, monkeypatch):
    from smol.cli import _get_demo_photo

    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))

    # Temporarily hide repo sample to test generation logic
    fake_cli_path = tmp_path / "nonexistent_pkg" / "cli.py"
    fake_cli_path.parent.mkdir(parents=True)

    def fake_path(*args):
        if args and "portrait.jpg" in str(args):
            return fake_cli_path
        return Path(*args)

    with patch("smol.cli.Path", side_effect=fake_path):
        photo = _get_demo_photo()

    assert photo.exists()
    assert photo.stat().st_size > 100_000


