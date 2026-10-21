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
        with pytest.warns(UserWarning, match="Invalid config value"):
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


# ---------------------------------------------------------------------------
# 9. P10.1b: Real Hostile Filename Shrinking & CLI Sanitization
# ---------------------------------------------------------------------------


def _generate_1_2mb_jpeg(path: Path) -> None:
    """Generate a realistic synthetic ~1.2 MB JPEG image."""
    import random

    random.seed(42)
    # 1800x1400 noise + gradient yields ~1.2MB JPEG at quality 90
    w, h = 1800, 1400
    im = Image.new("RGB", (w, h))
    pixels = []
    for y in range(h):
        for x in range(w):
            r = int((x / w) * 255)
            g = int((y / h) * 255)
            b = random.randint(0, 255)
            pixels.append((r, g, b))
    im.putdata(pixels)
    im.save(path, format="JPEG", quality=90)


def test_real_shrink_hostile_filenames(tmp_path: Path, qapp) -> None:
    """P10.1b (1): Real 1.2 MB JPEG files with hostile names shrunk to 100 KB.

    Tests:
    - -rf weird 'name".jpg
    - newline in filename
    - ESC sequence in filename
    Verifies output paths, notifier args, toast text, daemon log line, and CLI output.
    """
    from smol.cli import main
    from smol.daemon.service import sanitize_for_log

    base_jpeg = tmp_path / "base_source.jpg"
    _generate_1_2mb_jpeg(base_jpeg)
    assert base_jpeg.stat().st_size > 1_000_000  # Verify ~1.2 MB

    names = [
        "-rf weird 'name\".jpg",
        "name\nwith\nnewlines.jpg",
        "\x1b[31mcolor_esc\x1b[0m.jpg",
    ]

    hostile_files: list[Path] = []
    for n in names:
        f = tmp_path / n
        f.write_bytes(base_jpeg.read_bytes())
        hostile_files.append(f)

    results: list[tuple[Path, Result]] = []
    for f in hostile_files:
        # Shrink to 100 KB
        res = shrink_image(f, 100_000)
        assert res.ok is True
        assert res.output_path is not None
        assert res.output_path.exists()
        assert res.final_bytes <= 100_000
        assert res.output_path.parent.resolve() == tmp_path.resolve()
        assert "\n" not in res.output_path.name
        assert "\r" not in res.output_path.name
        assert "\x1b" not in res.output_path.name
        results.append((f, res))

    # Test notifier receives '--' and sanitized text
    mock_run = MagicMock()
    with (
        patch("shutil.which", return_value="/usr/bin/notify-send"),
        patch("subprocess.run", mock_run),
    ):
        for f, _res in results:
            send_notification("smol", f"{f.name}: shrunk")
        assert mock_run.call_count == len(results)
        # Check that the call for the dash filename received '--'
        dash_cmd = mock_run.call_args_list[0][0][0]
        assert "--" in dash_cmd
        sep_idx = dash_cmd.index("--")
        assert dash_cmd[sep_idx + 2].startswith("-rf")

        for call_args in mock_run.call_args_list:
            cmd = call_args[0][0]
            summary = cmd[-2]
            body = cmd[-1]
            assert "\x1b" not in summary and "\x1b" not in body

    # Test toast text is plain / escaped
    toast = ToastWindow(results=results)
    toast_msg = toast._format_message()
    assert "\x1b" not in toast_msg

    # Test daemon log line stays on ONE line
    for f in hostile_files:
        log_line = sanitize_for_log(f"Received file drop: {f.name}")
        assert "\n" not in log_line
        assert "\r" not in log_line
        assert "\x1b" not in log_line

    # Test CLI human-readable output neutralizes control chars and newlines
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        ret = main(
            ["shrink", str(hostile_files[0]), str(hostile_files[1]), "--max", "100KB"]
        )
    assert ret == 0
    cli_out = buf.getvalue()
    # No ANSI escape or split lines from filename in human output
    assert "\x1b" not in cli_out

    # Test CLI JSON output keeps exact source name
    import json

    buf_json = io.StringIO()
    with redirect_stdout(buf_json):
        ret_json = main(["shrink", str(hostile_files[1]), "--max", "100KB", "--json"])
    assert ret_json == 0
    parsed_json = json.loads(buf_json.getvalue())
    assert len(parsed_json) == 1
    assert parsed_json[0]["src"] == str(hostile_files[1])


# ---------------------------------------------------------------------------
# 10. P10.1b: classify.py fstat TOCTOU Race Rejection
# ---------------------------------------------------------------------------


def test_classify_fstat_race_rejects_fifo(tmp_path: Path) -> None:
    """P10.1b (2): classify() calls os.fstat on fd.

    Rejects race where file is FIFO.
    """
    fake_file = tmp_path / "race_test.jpg"
    fake_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 30)

    def fake_fstat(fd: int):
        return os.stat_result(
            (
                stat.S_IFIFO | 0o644,  # mode: FIFO!
                0,  # ino
                0,  # dev
                1,  # nlink
                1000,  # uid
                1000,  # gid
                0,  # size
                0,  # atime
                0,  # mtime
                0,  # ctime
            )
        )

    with patch("os.fstat", side_effect=fake_fstat):
        c = classify(fake_file)
        assert not c.is_supported
        assert c.kind in ("unsupported", "unreadable")
        assert "FIFO" in (c.reason or "") or "regular" in (c.reason or "")


# ---------------------------------------------------------------------------
# 11. P10.1b: Output Files Same-Directory & Normal Umask Permissions
# ---------------------------------------------------------------------------


def test_output_file_same_dir_and_umask_permissions(tmp_path: Path) -> None:
    """P10.1b (3): Output temp file in same directory.

    Final file has normal umask perms.
    """
    src = tmp_path / "sample_umask.jpg"
    im = Image.new("RGB", (400, 400), "green")
    im.save(src, quality=95)

    # Set known umask 0o022 -> should result in 0o644 permissions (not 0o600)
    old_umask = os.umask(0o022)
    try:
        res = shrink_image(src, 1_500)
        assert res.ok is True
        assert res.output_path is not None
        assert res.output_path.parent.resolve() == tmp_path.resolve()

        st_mode = stat.S_IMODE(res.output_path.stat().st_mode)
        assert st_mode == 0o644, (
            f"Final file has incorrect mode {oct(st_mode)}, expected 0o644"
        )
    finally:
        os.umask(old_umask)


# ---------------------------------------------------------------------------
# 12. P10.1b: sanitize_filename_component Preserves Dots
# ---------------------------------------------------------------------------


def test_sanitize_filename_component_preserves_dots_and_strips_traversal(
    tmp_path: Path,
) -> None:
    """P10.1b (4): remove only whole '..' components.

    Names like holiday..photo.jpg stay unchanged.
    """
    from smol.core.paths import sanitize_filename_component

    # Legitimate embedded dots must stay completely unchanged
    assert sanitize_filename_component("holiday..photo.jpg") == "holiday..photo.jpg"
    assert sanitize_filename_component("photo.final.jpg") == "photo.final.jpg"
    assert (
        sanitize_filename_component("my..sample..image.png") == "my..sample..image.png"
    )

    # Traversal whole components must be stripped
    assert sanitize_filename_component("..") == "file"
    assert sanitize_filename_component("../photo.jpg") == "photo.jpg"
    assert sanitize_filename_component("../../foo/bar") == "foo_bar"
    assert sanitize_filename_component("foo/../bar") == "foo_bar"

    # Check output_path preserves holiday..photo
    out = output_path(tmp_path / "holiday..photo.jpg", 100_000)
    assert "holiday..photo" in out.name
    assert "holiday_photo" not in out.name


# ---------------------------------------------------------------------------
# 13. P10.1b: Decompression Bomb Warning as Error & PDF Limits
# ---------------------------------------------------------------------------


def test_decompression_bomb_warning_treated_as_error_in_engine(tmp_path: Path) -> None:
    """P10.1b (5): DecompressionBombWarning must be treated as an error."""
    from smol.core.image import DEFAULT_MAX_IMAGE_PIXELS

    # State explicit MAX_IMAGE_PIXELS value
    assert DEFAULT_MAX_IMAGE_PIXELS == 89_478_485

    bomb_path = tmp_path / "bomb_header.jpg"
    im = Image.new("RGB", (200, 200), "red")
    im.save(bomb_path)

    with patch("PIL.Image.MAX_IMAGE_PIXELS", 30_000):
        # 40,000 pixels is > 30,000 and <= 60,000; emits DecompressionBombWarning
        res = shrink_image(bomb_path, 500)
        assert res.ok is False
        assert "decompression bomb" in (res.error or "").lower()


def test_pdf_has_size_and_page_limits(tmp_path: Path) -> None:
    """P10.1b (5): PDF engine must enforce size and page count limits."""
    from smol.core.pdf import MAX_PDF_PAGES, MAX_PDF_SIZE_BYTES

    assert MAX_PDF_SIZE_BYTES > 0
    assert MAX_PDF_PAGES > 0

    # Test file exceeding size limit
    fake_huge_pdf = tmp_path / "huge.pdf"
    fake_huge_pdf.write_bytes(b"%PDF-1.4 dummy")

    with patch.object(Path, "stat") as mock_stat:
        st = MagicMock()
        st.st_size = MAX_PDF_SIZE_BYTES + 10_000
        mock_stat.return_value = st
        res = shrink_pdf(fake_huge_pdf, 50_000)
        assert res.ok is False
        assert "exceeds safety limit" in (res.error or "")

    # Test file exceeding page limit
    fake_pages_pdf = tmp_path / "many_pages.pdf"
    fake_pages_pdf.write_bytes(b"%PDF-1.4 dummy")

    def fake_run(cmd, *args, **kwargs):
        if "--show-npages" in cmd:
            res = MagicMock()
            res.returncode = 0
            res.stdout = f"{MAX_PDF_PAGES + 500}\n"
            return res
        return MagicMock(returncode=1)

    with patch("subprocess.run", side_effect=fake_run):
        res_pages = shrink_pdf(fake_pages_pdf, 50_000)
        assert res_pages.ok is False
        assert "exceeds safety limit" in (res_pages.error or "")


# ---------------------------------------------------------------------------
# 14. P10.1b: Item 6 Checks (Symlinks, Grab Release, Undo Safety)
# ---------------------------------------------------------------------------


def test_output_path_never_overwrites_or_follows_symlink(tmp_path: Path) -> None:
    """P10.1b (6f): output_path never follows or overwrites symlinks."""
    src = tmp_path / "pic.jpg"
    src.write_bytes(b"data")

    # 1. Existing valid symlink at pic_100KB.jpg
    target_real = tmp_path / "real_file.jpg"
    target_real.write_bytes(b"target data")
    symlink_valid = tmp_path / "pic_100KB.jpg"
    symlink_valid.symlink_to(target_real)

    # 2. Existing dangling symlink at pic_100KB-1.jpg
    dangling = tmp_path / "pic_100KB-1.jpg"
    dangling.symlink_to(tmp_path / "non_existent.jpg")

    # output_path must detect BOTH valid and dangling symlinks as collision
    out = output_path(src, 100_000)
    assert out.name == "pic_100KB-2.jpg"
    assert not out.exists()
    assert not out.is_symlink()


def test_undo_deletes_only_output_file_this_run(tmp_path: Path, qapp) -> None:
    """P10.1b (6g): Undo deletes ONLY the newly created output file."""
    src = tmp_path / "source.jpg"
    src.write_bytes(b"original source content")
    out = tmp_path / "source_100KB.jpg"
    out.write_bytes(b"compressed content")
    other = tmp_path / "unrelated.jpg"
    other.write_bytes(b"unrelated content")

    res = Result(
        ok=True,
        output_path=out,
        original_bytes=len(src.read_bytes()),
        final_bytes=len(out.read_bytes()),
    )
    toast = ToastWindow(results=[(src, res)])

    deleted = toast.undo()
    assert deleted == [out.resolve()]
    assert not out.exists(), "Output file was not deleted"
    assert src.exists(), "CRITICAL: Original file was deleted by Undo!"
    assert src.read_bytes() == b"original source content"
    assert other.exists(), "Unrelated file was affected by Undo!"


def test_daemon_grabs_released_and_single_instance_lock(tmp_path: Path) -> None:
    """P10.1b (6b): X11 key/pointer grabs released and single-instance lock."""
    from smol.daemon.listener import ensure_ungrab

    # 1. ensure_ungrab must be safe to call repeatedly without exception
    ensure_ungrab()
    ensure_ungrab()

    # 2. Single-instance lock behaviour
    state_dir = tmp_path / "daemon_state"
    svc1 = DaemonService(state_dir=state_dir, config_path=tmp_path / "config.toml")
    svc2 = DaemonService(state_dir=state_dir, config_path=tmp_path / "config.toml")

    # First instance acquires lock successfully
    assert svc1.acquire_lock() is True
    assert svc1.lock_path.exists()
    assert svc1.pid_path.exists()
    assert svc1.pid_path.read_text(encoding="utf-8").strip() == str(os.getpid())

    # Second instance must fail to acquire lock
    assert svc2.acquire_lock() is False

    # Release lock
    svc1.release_lock()
    assert not svc1.pid_path.exists()

    # After release, lock can be acquired again by svc2
    assert svc2.acquire_lock() is True
    svc2.release_lock()


def test_config_and_favourites_recents_hostile_caps() -> None:
    """P10.1b (6c): config and favourites/recents caps with hostile values."""
    hostile = {
        "sizes": {
            "ladder": [1000 * i for i in range(1, 100)],  # 99 ladder entries
            "pinned": [2000 * i for i in range(1, 100)],  # 99 pinned entries
            "recents": [3000 * i for i in range(1, 100)],  # 99 recents entries
        }
    }
    validated = validate_config_dict(hostile)
    assert len(validated["sizes"]["ladder"]) <= 7
    assert len(validated["sizes"]["pinned"]) <= 12
    assert len(validated["sizes"]["recents"]) <= 5


def test_wayland_guard_exit_code_3_audit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """P10.1b (6d): Wayland guard exit code 3."""
    from smol.cli import main
    from smol.daemon.service import check_wayland_session

    env = {"XDG_SESSION_TYPE": "wayland"}
    assert check_wayland_session(env) is True

    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.delenv("DISPLAY", raising=False)

    code = main(["daemon", "start"])
    assert code == 3
    captured = capsys.readouterr()
    assert "smol's hold-key donut needs an X11 session" in (captured.err + captured.out)


def test_no_leftover_ffmpeg_in_core() -> None:
    """P10.1b (6e): grep for leftover ffmpeg/ffprobe/video/audio in smol/core."""
    core_dir = Path(__file__).parent.parent / "smol" / "core"
    for py_file in core_dir.glob("*.py"):
        text = py_file.read_text(encoding="utf-8").lower()
        assert "ffmpeg" not in text, (
            f"Found leftover ffmpeg reference in {py_file.name}"
        )
        assert "ffprobe" not in text, (
            f"Found leftover ffprobe reference in {py_file.name}"
        )
