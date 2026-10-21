"""Tests for security audit, hardening, and defensive invariants."""

from __future__ import annotations

import errno
import html
import os
import stat
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from smol.config import save_config, validate_config_dict
from smol.core.classify import classify
from smol.core.image import shrink_image
from smol.core.paths import output_path
from smol.core.pdf import shrink_pdf
from smol.core.result import Result
from smol.core.suggest import estimate_floor
from smol.daemon.service import DaemonService
from smol.integrations.autostart import AutostartIntegrator
from smol.integrations.manager import NemoIntegrator
from smol.integrations.notifier import send_notification
from smol.ui.donut_window import _load_thumbnail_pixmap
from smol.ui.toast import ToastWindow

# ---------------------------------------------------------------------------
# 1. Subprocess Calls & Ghostscript -dSAFER
# ---------------------------------------------------------------------------


def test_pdf_ghostscript_has_dsafer_and_safe_args(tmp_path: Path) -> None:
    """Ghostscript commands in shrink_pdf must include -dSAFER.

    Also ensures leading dashes in filenames are handled safely.
    """
    # Create a dummy PDF with leading dash in filename
    src_pdf = tmp_path / "-rf_weird_test.pdf"
    # Minimal PDF syntax
    src_pdf.write_bytes(
        b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
        b"xref\n0 3\n0000000000 65535 f \n0000000010 00000 n \n0000000060 00000 n \n"
        b"trailer\n<< /Size 3 /Root 1 0 R >>\nstartxref\n116\n%%EOF\n"
    )

    executed_cmds: list[list[str]] = []

    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        executed_cmds.append(list(cmd))
        if cmd[0].endswith("gs") or cmd[0] == "gs":
            # Simulate GS failure or success
            res = MagicMock()
            res.returncode = 1
            res.stdout = ""
            res.stderr = ""
            return res
        return real_run(cmd, *args, **kwargs)

    with patch("subprocess.run", side_effect=fake_run):
        shrink_pdf(src_pdf, target_bytes=50)

    # Verify at least one GS command was constructed
    gs_cmds = [c for c in executed_cmds if c and (c[0] == "gs" or c[0].endswith("/gs"))]
    assert len(gs_cmds) > 0, "Ghostscript was not invoked"
    for cmd in gs_cmds:
        assert "-dSAFER" in cmd, f"Ghostscript command missing -dSAFER: {cmd}"
        # Filename should follow '--', '-f', or be an absolute path so it's not a flag
        idx = (
            cmd.index(str(src_pdf.resolve()))
            if str(src_pdf.resolve()) in cmd
            else cmd.index(str(src_pdf))
        )
        assert idx > 0
        # If passed as str(src_pdf), must be preceded by '-f' or '--'
        flag_before = cmd[idx - 1]
        assert flag_before in ("-f", "--") or str(cmd[idx]).startswith("/"), (
            f"Filename with leading dash not guarded in GS command: {cmd}"
        )


def test_donut_pdf_thumbnail_has_dsafer_and_dash_safe(tmp_path: Path) -> None:
    """PDF thumbnail rasterization must include -dSAFER.

    Must also guard leading dash filenames.
    """
    pdf_path = tmp_path / "-leading_dash_thumb.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 dummy")

    captured_cmds: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        captured_cmds.append(list(cmd))
        res = MagicMock()
        res.returncode = 1
        res.stdout = b""
        res.stderr = b""
        return res

    with patch("subprocess.run", side_effect=fake_run):
        _load_thumbnail_pixmap(pdf_path)

    gs_cmds = [c for c in captured_cmds if c and (c[0] == "gs" or c[0].endswith("/gs"))]
    assert len(gs_cmds) > 0
    for cmd in gs_cmds:
        assert "-dSAFER" in cmd, f"Thumbnail GS call missing -dSAFER: {cmd}"
        # Must guard filename with -f, --, or absolute path
        file_arg = cmd[-1]
        assert file_arg.startswith("/") or cmd[-2] in ("-f", "--")


def test_notify_send_uses_separator_and_escapes() -> None:
    """notify-send must guard options before summary/body to prevent injection."""
    executed_cmds: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        executed_cmds.append(list(cmd))
        res = MagicMock()
        res.returncode = 0
        return res

    with (
        patch("shutil.which", return_value="/usr/bin/notify-send"),
        patch("subprocess.run", side_effect=fake_run),
    ):
        # Pass a hostile summary and body starting with dashes and containing HTML tags
        send_notification("-u", "-rf <b>weird 'name\"</b>.jpg\nline2")

    assert len(executed_cmds) == 1
    cmd = executed_cmds[0]
    assert "--" in cmd, f"notify-send call did not include '--' separator: {cmd}"
    sep_idx = cmd.index("--")
    # All summary and body arguments must appear after '--'
    assert sep_idx < len(cmd) - 2


# ---------------------------------------------------------------------------
# 2. Hostile Filenames & Path Traversal
# ---------------------------------------------------------------------------


def test_output_path_prevents_path_traversal(tmp_path: Path) -> None:
    """output_path must never escape the target directory even with hostile patterns."""
    src = tmp_path / "photo.jpg"
    src.write_bytes(b"data")

    # Hostile patterns attempting traversal or absolute override
    traversal_patterns = [
        "../../{name}_{size}{ext}",
        "/etc/{name}_{size}{ext}",
        "....//....//{name}_{size}{ext}",
        "sub/../../{name}_{size}{ext}",
        "{name}/../../../{size}{ext}",
    ]

    for pat in traversal_patterns:
        out = output_path(src, 100_000, pattern=pat)
        # Output must reside directly in tmp_path (parent directory), never outside
        assert out.parent.resolve() == tmp_path.resolve(), (
            f"Path traversal succeeded for pattern '{pat}': resolved to '{out}'"
        )
        assert "/" not in out.name, (
            f"Directory separator leaked into filename: {out.name}"
        )
        assert ".." not in out.name


def test_output_path_neutralizes_newlines_and_control_chars(tmp_path: Path) -> None:
    """output_path must strip newlines, carriage returns, and control chars."""
    hostile_src = tmp_path / "weird\nname\r\x00\x1b[31m.jpg"
    out = output_path(hostile_src, 100_000)

    assert "\n" not in out.name
    assert "\r" not in out.name
    assert "\x00" not in out.name
    assert "\x1b" not in out.name
    assert out.parent.resolve() == tmp_path.resolve()


# ---------------------------------------------------------------------------
# 3. Safe Classification & TOCTOU Non-Blocking
# ---------------------------------------------------------------------------


def test_classify_non_blocking_fifo_does_not_hang(tmp_path: Path) -> None:
    """classify() must open files non-blocking to prevent hanging on FIFO races."""
    fifo_path = tmp_path / "test_fifo.jpg"
    try:
        os.mkfifo(fifo_path)
    except (AttributeError, OSError):
        pytest.skip("mkfifo not supported on this platform/filesystem")

    # Classify the FIFO directly (should refuse as FIFO without hanging)
    c = classify(fifo_path)
    assert not c.is_supported
    assert "FIFO" in (c.reason or "") or c.kind in ("unsupported", "unreadable")


def test_classify_huge_file_count_capped(tmp_path: Path) -> None:
    """classify_files must cap batch inspection at 50 files."""
    from smol.core.classify import classify_files

    paths = [tmp_path / f"file_{i}.jpg" for i in range(120)]
    batch = classify_files(paths)
    assert batch.classified_count == 50
    assert batch.total_count == 120
    assert batch.more_count == 70
    assert batch.has_unknown is True


# ---------------------------------------------------------------------------
# 4. Decompression Bomb & Resource Limits
# ---------------------------------------------------------------------------


def test_thumbnail_and_floor_decompression_bomb_guard(tmp_path: Path) -> None:
    """Thumbnail loader and floor estimator must catch DecompressionBombError."""
    bomb_path = tmp_path / "huge_bomb.jpg"
    im = Image.new("RGB", (1000, 1000), "white")
    im.save(bomb_path)

    # Force low pixel threshold to trigger DecompressionBombError
    with patch("PIL.Image.MAX_IMAGE_PIXELS", 500):
        # 1. Thumbnail loader must return None without raising an exception
        pix = _load_thumbnail_pixmap(bomb_path)
        assert pix is None

        # 2. estimate_floor must return safe fallback without raising
        floor_res = estimate_floor(bomb_path)
        assert floor_res.bytes > 0
        assert floor_res.source == "estimate"


# ---------------------------------------------------------------------------
# 5. Config Hardening: NaN, Infinity, Huge Numbers, and Temp Leaks
# ---------------------------------------------------------------------------


def test_config_validation_rejects_nan_inf_huge_values() -> None:
    """validate_config_dict must cleanly reject NaN, Inf, negative, and huge values."""
    hostile_configs = [
        {"sizes": {"ladder": [float("nan"), 100_000]}},
        {"sizes": {"ladder": [float("inf"), 100_000]}},
        {"sizes": {"ladder": [-50_000, 100_000]}},
        {"sizes": {"ladder": [10**18, 100_000]}},
        {"min_side": 10**10},
        {"min_side": float("nan")},
        {"naming_pattern": "A" * 10_000},
        {"trigger_key": "B" * 5_000},
    ]

    for hc in hostile_configs:
        validated = validate_config_dict(hc)
        # All ladder sizes must be reasonable positive ints (< 100 GB)
        for s in validated["sizes"]["ladder"]:
            assert isinstance(s, int)
            assert 0 < s <= 100_000_000_000
        # min_side must be reasonable
        assert 1 <= validated["min_side"] <= 100_000
        assert len(validated["naming_pattern"]) <= 500
        assert len(validated["trigger_key"]) <= 100


def test_config_save_tempfile_cleanup_on_error(tmp_path: Path) -> None:
    """save_config must guarantee temporary file removal if write or replace fails."""
    cfg_file = tmp_path / "config.toml"

    with (
        patch("tomli_w.dumps", side_effect=OSError("Disk write error")),
        pytest.raises(OSError),
    ):
        save_config({"trigger_key": "Super"}, config_path=cfg_file)

    # Assert no dangling temporary files in tmp_path
    temp_files = list(tmp_path.glob("*.tmp*"))
    assert len(temp_files) == 0, f"Dangling temporary files left behind: {temp_files}"


def test_log_and_config_directory_permissions(tmp_path: Path) -> None:
    """Daemon logs must be private (0o600) and state/config dirs restricted (0o700)."""
    state_dir = tmp_path / "state"
    svc = DaemonService(state_dir=state_dir, config_path=tmp_path / "config.toml")
    logger = svc.setup_logging()
    logger.info("Test permission message")

    # Flush handlers
    for h in logger.handlers:
        h.flush()

    assert svc.log_path.exists()
    log_mode = stat.S_IMODE(svc.log_path.stat().st_mode)
    # File must be readable/writable by owner only (0o600)
    assert log_mode == 0o600, f"Log file permissions too open: {oct(log_mode)}"

    dir_mode = stat.S_IMODE(state_dir.stat().st_mode)
    assert dir_mode == 0o700, f"State directory permissions too open: {oct(dir_mode)}"


# ---------------------------------------------------------------------------
# 6. Text Injection: Toast, Donut, and Log Neutralization
# ---------------------------------------------------------------------------


def test_toast_filename_plain_text_no_html_injection(qapp) -> None:
    """ToastWindow must render filenames as plain text without parsing HTML tags."""
    hostile_name = "test_<img src=x onerror=alert(1)>_bold.jpg"
    hostile_path = Path("/tmp") / hostile_name
    res = Result(
        ok=True,
        output_path=Path(f"/tmp/out_{hostile_name}"),
        original_bytes=200_000,
        final_bytes=90_000,
    )

    toast = ToastWindow(results=[(hostile_path, res)])
    msg = toast._format_message()

    # The HTML tags from the filename MUST be escaped so Qt does not interpret them
    assert "<img" not in msg
    assert "&lt;img" in msg
    assert html.escape(hostile_name) in msg


def test_daemon_log_neutralizes_newlines_and_ansi() -> None:
    """Daemon log strings must sanitize filenames containing newlines or ANSI."""
    from smol.daemon.service import sanitize_for_log

    hostile_name = "-rf weird\n2026-10-20 [INFO] Fake forged log entry\r\x1b[31mred.jpg"
    clean = sanitize_for_log(hostile_name)

    assert "\n" not in clean
    assert "\r" not in clean
    assert "\x1b" not in clean
    assert "Fake forged log entry" in clean  # text remains readable but neutral


# ---------------------------------------------------------------------------
# 7. Integrations & Quoting
# ---------------------------------------------------------------------------


def test_integration_quoting_with_spaces_in_path(tmp_path: Path) -> None:
    """Integration generators must properly quote binary paths with spaces."""
    bin_with_spaces = str(tmp_path / "My Apps" / "smol bin")
    actions_dir = tmp_path / "actions"
    nemo = NemoIntegrator(actions_dir=actions_dir, smol_bin=bin_with_spaces)
    res = nemo.install()
    assert res.ok

    # Check generated nemo_action files
    action_files = list(actions_dir.glob("*.nemo_action"))
    assert len(action_files) > 0
    content = action_files[0].read_text(encoding="utf-8")
    assert (
        f'Exec="{bin_with_spaces}"' in content or f"Exec='{bin_with_spaces}'" in content
    )

    # Check autostart desktop entry
    autostart_dir = tmp_path / "autostart"
    auto = AutostartIntegrator(autostart_dir=autostart_dir, smol_bin=bin_with_spaces)
    res_auto = auto.install()
    assert res_auto.ok
    desktop_content = auto.desktop_file.read_text(encoding="utf-8")
    assert f'Exec="{bin_with_spaces}"' in desktop_content


# ---------------------------------------------------------------------------
# 8. Disk Full (ENOSPC) Handling & Cleanup
# ---------------------------------------------------------------------------


def test_disk_full_enospc_honest_failure_and_cleanup(tmp_path: Path) -> None:
    """Image and PDF engines must handle ENOSPC cleanly with zero temp leaks."""
    src = tmp_path / "sample.jpg"
    im = Image.new("RGB", (100, 100), "blue")
    im.save(src)

    # Simulate ENOSPC on replace/write
    def fake_replace(*args, **kwargs):
        err = OSError()
        err.errno = errno.ENOSPC
        err.strerror = "No space left on device"
        raise err

    with patch("pathlib.Path.replace", side_effect=fake_replace):
        res = shrink_image(src, 400)

    assert not res.ok
    assert "space" in (res.error or "").lower() or "full" in (res.error or "").lower()

    # Zero temp files left
    tmp_leftovers = list(tmp_path.glob("*.tmp*"))
    assert len(tmp_leftovers) == 0, f"Dangling temp files: {tmp_leftovers}"
