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
