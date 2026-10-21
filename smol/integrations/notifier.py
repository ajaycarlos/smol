import html
import re
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Self

from smol.core.result import Result
from smol.core.size import format_size


def format_notification(results: list[tuple[Path, Result]]) -> tuple[str, str, str]:
    """Format notification (summary, body, urgency) from shrink results.

    Formats:
    - Single success: "photo.jpg: 1.02 MB → 97 KB"
    - Single failure: honest engine error message
    - Batch mixed: "3 files shrunk, 1 failed"
    - Batch all success: "3 files shrunk"
    - Batch all failure: "2 files failed"
    """
    summary = "smol"
    if not results:
        return summary, "", "normal"

    if len(results) == 1:
        src_path, res = results[0]
        # Neutralize control characters and newlines in filenames
        clean_name = (
            re.sub(r"[\r\n\x00-\x1f]", " ", src_path.name).strip() or src_path.name
        )
        if res.ok:
            orig_str = format_size(res.original_bytes, spaced=True)
            final_str = format_size(res.final_bytes, spaced=True)
            body = f"{clean_name}: {orig_str} → {final_str}"
            urgency = "normal"
        else:
            body = res.error or f"Failed to shrink {clean_name}"
            urgency = "critical"
        return summary, body, urgency

    # Batch summary
    shrunk_count = sum(1 for _, res in results if res.ok)
    failed_count = sum(1 for _, res in results if not res.ok)

    if failed_count == 0:
        plural = "files" if shrunk_count != 1 else "file"
        body = f"{shrunk_count} {plural} shrunk"
        urgency = "normal"
    elif shrunk_count == 0:
        plural = "files" if failed_count != 1 else "file"
        body = f"{failed_count} {plural} failed"
        urgency = "critical"
    else:
        shrunk_plural = "files" if shrunk_count != 1 else "file"
        failed_plural = "failed"
        body = f"{shrunk_count} {shrunk_plural} shrunk, {failed_count} {failed_plural}"
        urgency = "critical"

    return summary, body, urgency


def send_notification(
    summary: str,
    body: str,
    urgency: str = "normal",
    app_name: str = "smol",
    print_fallback: bool = True,
) -> bool:
    """Send desktop notification via notify-send, falling back to terminal.

    Guarantees safe invocation using '--' separator and XML/HTML escaping.
    Returns True if notify-send succeeded, False if fallen back to terminal.
    """
    safe_summary = html.escape(summary)
    safe_body = html.escape(body)
    if shutil.which("notify-send"):
        cmd = [
            "notify-send",
            "-u",
            urgency,
            "-a",
            app_name,
        ]
        if safe_summary.startswith("-"):
            cmd.append("--")
        cmd.extend([safe_summary, safe_body])

        try:
            subprocess.run(
                cmd,
                check=True,
            )
            return True
        except (subprocess.SubprocessError, OSError):
            pass

    if print_fallback and body:
        print(body)
    return False


class JobNotifier:
    """Context manager managing job notifications and working threshold timer."""

    def __init__(
        self,
        notify: bool = True,
        working_timeout: float = 1.5,
        sender: Callable[[str, str, str], bool] | None = None,
    ) -> None:
        self.notify = notify
        self.working_timeout = working_timeout
        self.sender = sender or send_notification
        self._timer: threading.Timer | None = None
        self._working_sent: bool = False
        self._lock = threading.Lock()

    def __enter__(self) -> Self:
        if self.notify and self.working_timeout > 0:
            self._timer = threading.Timer(self.working_timeout, self._on_timeout)
            self._timer.daemon = True
            self._timer.start()
        return self

    def _on_timeout(self) -> None:
        with self._lock:
            self._working_sent = True
            self.sender("smol", "Working…", "low")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def notify_results(self, results: list[tuple[Path, Result]]) -> bool:
        """Cancel working timer and send final result notification."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

        if not self.notify or not results:
            return False

        summary, body, urgency = format_notification(results)
        return self.sender(summary, body, urgency)
