"""Tests for smol desktop notifications and terminal fallback."""

import time
from pathlib import Path
from unittest.mock import MagicMock

from smol.core.result import Result
from smol.integrations.notifier import (
    JobNotifier,
    format_notification,
    send_notification,
)


def test_format_notification_single_success():
    """Verify single file success notification format."""
    res = Result(
        ok=True,
        output_path=Path("photo_100kb.jpg"),
        original_bytes=1_020_000,
        final_bytes=97_000,
    )
    results = [(Path("photo.jpg"), res)]
    summary, body, urgency = format_notification(results)
    assert summary == "smol"
    assert body == "photo.jpg: 1.02 MB → 97 KB"
    assert urgency == "normal"


def test_format_notification_single_failure_honest_message():
    """Verify single file failure produces the honest engine message."""
    error_msg = "Smallest I can make this is ~112 KB at 200 px; try a larger target."
    res = Result(
        ok=False,
        original_bytes=500_000,
        error=error_msg,
    )
    results = [(Path("photo.jpg"), res)]
    summary, body, urgency = format_notification(results)
    assert summary == "smol"
    assert body == error_msg
    assert urgency == "critical"


def test_format_notification_batch_summary():
    """Verify batch notifications format properly."""
    ok_res = Result(ok=True, original_bytes=1000, final_bytes=900)
    fail_res = Result(ok=False, original_bytes=1000, error="too big")

    # 3 success, 1 failed
    results = [
        (Path("a.jpg"), ok_res),
        (Path("b.jpg"), ok_res),
        (Path("c.jpg"), ok_res),
        (Path("d.jpg"), fail_res),
    ]
    summary, body, urgency = format_notification(results)
    assert summary == "smol"
    assert body == "3 files shrunk, 1 failed"
    assert urgency == "critical"

    # All 3 success
    summary, body, urgency = format_notification(results[:3])
    assert body == "3 files shrunk"
    assert urgency == "normal"

    # 1 success
    summary, body, urgency = format_notification([(Path("a.jpg"), ok_res)])
    # Single file has specific format
    assert body != "1 file shrunk"

    # All failed
    summary, body, urgency = format_notification(
        [
            (Path("a.jpg"), fail_res),
            (Path("b.jpg"), fail_res),
        ]
    )
    assert body == "2 files failed"
    assert urgency == "critical"


def test_send_notification_notify_send(monkeypatch):
    """Verify send_notification invokes notify-send when available."""
    mock_run = MagicMock()
    monkeypatch.setattr(
        "shutil.which",
        lambda cmd: "/usr/bin/notify-send" if cmd == "notify-send" else None,
    )
    monkeypatch.setattr("subprocess.run", mock_run)

    success = send_notification("smol", "photo.jpg: 1.02 MB → 97 KB", urgency="normal")
    assert success is True
    mock_run.assert_called_once_with(
        [
            "notify-send",
            "-u",
            "normal",
            "-a",
            "smol",
            "smol",
            "photo.jpg: 1.02 MB → 97 KB",
        ],
        check=True,
    )


def test_send_notification_fallback_to_terminal(monkeypatch, capsys):
    """Verify fallback prints to terminal when notify-send is not available."""
    monkeypatch.setattr("shutil.which", lambda cmd: None)

    success = send_notification("smol", "photo.jpg: 1.02 MB → 97 KB", urgency="normal")
    assert success is False
    out = capsys.readouterr().out
    assert "photo.jpg: 1.02 MB → 97 KB" in out


def test_send_notification_subprocess_error_fallback(monkeypatch, capsys):
    """Verify fallback prints to terminal when notify-send execution raises error."""
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/notify-send")

    def mock_fail(*args, **kwargs):
        raise OSError("Failed to execute notify-send")

    monkeypatch.setattr("subprocess.run", mock_fail)

    success = send_notification("smol", "photo.jpg: 1.02 MB → 97 KB", urgency="normal")
    assert success is False
    out = capsys.readouterr().out
    assert "photo.jpg: 1.02 MB → 97 KB" in out


def test_working_notification_fired_after_timeout(monkeypatch):
    """Verify 'Working…' notification is sent if job duration exceeds threshold."""
    sent = []

    def mock_send(summary, body, urgency="normal"):
        sent.append((summary, body, urgency))
        return True

    # Job taking 0.08s with 0.03s threshold
    with JobNotifier(notify=True, working_timeout=0.03, sender=mock_send):
        time.sleep(0.08)

    assert any(body == "Working…" for _, body, _ in sent)


def test_working_notification_cancelled_if_fast(monkeypatch):
    """Verify 'Working…' notification is NOT sent if job finishes before threshold."""
    sent = []

    def mock_send(summary, body, urgency="normal"):
        sent.append((summary, body, urgency))
        return True

    # Fast job finishing in 0.01s with 0.1s threshold
    with JobNotifier(notify=True, working_timeout=0.1, sender=mock_send):
        time.sleep(0.01)

    time.sleep(0.12)
    assert not any(body == "Working…" for _, body, _ in sent)
