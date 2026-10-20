"""smol.core.classify — Safe pre-drop file classification.

Sniffs headers (reading at most 32 bytes) without decoding images.
Refuses FIFOs, sockets, device files, and non-regular files without opening them.
Handles symlinks, folders, remote URIs, and caps inspection at 50 files.
"""

from __future__ import annotations

import os
import stat
import urllib.parse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

# Supported extensions mapping
EXTENSION_MAP: dict[str, str] = {
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".jpe": "jpeg",
    ".png": "png",
    ".webp": "webp",
    ".heic": "heic",
    ".heif": "heic",
    ".avif": "heic",
    ".pdf": "pdf",
}

SUPPORTED_KINDS: frozenset[str] = frozenset({"jpeg", "png", "webp", "heic", "pdf"})


@dataclass(frozen=True)
class Classification:
    # kind: jpeg | png | webp | heic | pdf | folder | unsupported | unreadable | remote
    kind: str
    reason: str | None = None
    mismatch_note: str | None = None
    path: str = ""

    @property
    def is_supported(self) -> bool:
        return self.kind in SUPPORTED_KINDS


@dataclass(frozen=True)
class BatchClassification:
    items: list[Classification]
    total_count: int
    classified_count: int
    more_count: int = 0
    more_label: str = ""
    has_unknown: bool = False

    @property
    def supported_items(self) -> list[Classification]:
        return [c for c in self.items if c.is_supported]

    @property
    def unsupported_items(self) -> list[Classification]:
        return [c for c in self.items if not c.is_supported]

    @property
    def all_supported(self) -> bool:
        return (
            not self.has_unknown
            and len(self.items) > 0
            and len(self.supported_items) == self.total_count
        )

    @property
    def none_supported(self) -> bool:
        return len(self.supported_items) == 0

    @property
    def mixed(self) -> bool:
        return 0 < len(self.supported_items) < self.total_count


def sniff_header(data: bytes) -> str | None:
    """Sniff up to 32 bytes of file header to identify format."""
    if len(data) >= 3 and data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if len(data) >= 8 and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    if len(data) >= 5 and data.startswith(b"%PDF-"):
        return "pdf"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12].lower()
        if brand in (
            b"heic",
            b"heix",
            b"hevc",
            b"heim",
            b"heis",
            b"mif1",
            b"msf1",
            b"avif",
            b"avis",
        ):
            return "heic"
        compat = data[16:32].lower()
        if any(b in compat for b in (b"heic", b"mif1", b"avif")):
            return "heic"
    # Known unsupported headers (zip/docx, elf, gzip, 7z, rar)
    if data.startswith(
        (
            b"PK\x03\x04",
            b"PK\x05\x06",
            b"PK\x07\x08",
            b"\x7fELF",
            b"\x1f\x8b",
            b"7z\xbc\xaf\x27\x1c",
            b"Rar!\x1a\x07",
        )
    ):
        return "unsupported"
    return None


def classify(path_or_uri: str | Path) -> Classification:
    """Classify a single file or URI safely without decoding images."""
    raw_str = str(path_or_uri)

    # Check for URI schemes
    if raw_str.startswith("file://"):
        parsed = urllib.parse.urlparse(raw_str)
        local_path = urllib.parse.unquote(parsed.path)
    elif "://" in raw_str or raw_str.startswith("data:"):
        return Classification(
            kind="remote", reason="remote", mismatch_note=None, path=raw_str
        )
    else:
        local_path = raw_str

    # Inspect filesystem metadata first (lstat)
    try:
        st_l = os.lstat(local_path)
    except FileNotFoundError:
        return Classification(
            kind="unreadable",
            reason="File not found",
            mismatch_note=None,
            path=local_path,
        )
    except PermissionError:
        return Classification(
            kind="unreadable",
            reason="Permission denied",
            mismatch_note=None,
            path=local_path,
        )
    except OSError as e:
        return Classification(
            kind="unreadable", reason=str(e), mismatch_note=None, path=local_path
        )

    # Check for symlink
    if stat.S_ISLNK(st_l.st_mode):
        try:
            st = os.stat(local_path)
        except FileNotFoundError:
            return Classification(
                kind="unreadable",
                reason="Broken symlink",
                mismatch_note=None,
                path=local_path,
            )
        except PermissionError:
            return Classification(
                kind="unreadable",
                reason="Permission denied",
                mismatch_note=None,
                path=local_path,
            )
        except OSError as e:
            return Classification(
                kind="unreadable", reason=str(e), mismatch_note=None, path=local_path
            )

        # Do not follow symlinks to non-regular files
        if stat.S_ISDIR(st.st_mode):
            return Classification(
                kind="folder",
                reason="folder, not supported",
                mismatch_note=None,
                path=local_path,
            )
        if not stat.S_ISREG(st.st_mode):
            return Classification(
                kind="unsupported",
                reason="symlink to non-regular file",
                mismatch_note=None,
                path=local_path,
            )
    else:
        st = st_l

    # Check for directories
    if stat.S_ISDIR(st.st_mode):
        return Classification(
            kind="folder",
            reason="folder, not supported",
            mismatch_note=None,
            path=local_path,
        )

    # Refuse FIFOs, sockets, character/block devices without opening
    if stat.S_ISFIFO(st.st_mode):
        return Classification(
            kind="unsupported",
            reason="FIFO, not supported",
            mismatch_note=None,
            path=local_path,
        )
    if stat.S_ISSOCK(st.st_mode):
        return Classification(
            kind="unsupported",
            reason="socket, not supported",
            mismatch_note=None,
            path=local_path,
        )
    if stat.S_ISCHR(st.st_mode) or stat.S_ISBLK(st.st_mode):
        return Classification(
            kind="unsupported",
            reason="device file, not supported",
            mismatch_note=None,
            path=local_path,
        )

    # Require regular file
    if not stat.S_ISREG(st.st_mode):
        return Classification(
            kind="unsupported",
            reason="not a regular file",
            mismatch_note=None,
            path=local_path,
        )

    # Read at most 32 bytes for header sniffing
    try:
        with open(local_path, "rb") as f:
            header = f.read(32)
    except PermissionError:
        return Classification(
            kind="unreadable",
            reason="Permission denied",
            mismatch_note=None,
            path=local_path,
        )
    except OSError as e:
        return Classification(
            kind="unreadable", reason=str(e), mismatch_note=None, path=local_path
        )

    ext = Path(local_path).suffix.lower()
    ext_kind = EXTENSION_MAP.get(ext)
    header_kind = sniff_header(header)

    if header_kind is not None:
        if header_kind == "unsupported":
            reason = (
                f"Unsupported file type ({ext})" if ext else "Unsupported file type"
            )
            mismatch = (
                f"Header is unsupported, but extension is {ext}" if ext_kind else None
            )
            return Classification(
                kind="unsupported",
                reason=reason,
                mismatch_note=mismatch,
                path=local_path,
            )
        # Sniff the header first: trust the header if header and extension disagree
        mismatch_note = None
        if ext and (ext_kind is None or ext_kind != header_kind):
            mismatch_note = f"Header is {header_kind}, but extension is {ext}"
        return Classification(
            kind=header_kind,
            reason=None,
            mismatch_note=mismatch_note,
            path=local_path,
        )

    # Sniff the extension second
    if ext_kind is not None:
        return Classification(
            kind=ext_kind,
            reason=None,
            mismatch_note=None,
            path=local_path,
        )

    # Header does not match any supported format and extension is unsupported
    reason = f"Unsupported file type ({ext})" if ext else "Unsupported file type"
    return Classification(
        kind="unsupported",
        reason=reason,
        mismatch_note=None,
        path=local_path,
    )


def classify_files(paths_or_uris: Sequence[str | Path]) -> BatchClassification:
    """Classify up to 50 files; the rest count as '+N more' (unknown)."""
    total = len(paths_or_uris)
    classified_paths = paths_or_uris[:50]
    more_count = max(0, total - 50)
    items = [classify(p) for p in classified_paths]

    return BatchClassification(
        items=items,
        total_count=total,
        classified_count=len(items),
        more_count=more_count,
        more_label=f"+{more_count} more" if more_count > 0 else "",
        has_unknown=(more_count > 0),
    )
