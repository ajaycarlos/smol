# Security Policy and Threat Model

`smol` is a Linux desktop application that shrinks image and PDF files to user-specified target sizes. This document details `smol`'s threat model, security boundaries, protections, and limitations.

---

## 1. Threat Model & Environment

`smol` operates as a local, fully offline desktop tool. It performs **zero network calls** and accepts inputs solely from the local filesystem via the command-line interface, desktop drag-and-drop, hold-key daemon triggers, or file-manager context menus.

### Attack Vectors & Threat Sources
1. **Hostile Filenames**: Files with leading dashes (`-rf.jpg`), spaces, unicode, control characters, newlines, or path traversal sequences (`../../etc/shadow`).
2. **Untrusted Files**: Malicious or malformed images, decompression bombs ("zip/image bombs"), and PostScript/PDF files containing exploit payloads.
3. **Hostile File Types**: FIFOs (named pipes), Unix sockets, or device nodes dropped onto the application to trigger denial of service or hanging.
4. **Untrusted Configurations**: Corrupted or maliciously crafted `config.toml` files containing invalid types, `NaN`, `Infinity`, or excessive allocation lengths.
5. **Disk Exhaustion**: Maliciously filling the disk during compression (`ENOSPC`) to cause inconsistent state or dangling temporary files.

---

## 2. What `smol` Protects Against

### Subprocess and Command Injection
- **No Shell Execution**: Subprocesses (`gs`, `qpdf`, `notify-send`) are invoked exclusively via list arguments with `shell=False`.
- **Leading-Dash Argument Neutralization**: Filenames beginning with dashes are passed using absolute paths (`path.resolve()`) or explicit `--` / `-f` argument delimiters, preventing CLI flag injection. The desktop notification dispatcher automatically prepends `"--"` when title or body starts with `-`.
- **Ghostscript Sandboxing**: All Ghostscript calls (`shrink_pdf` and PDF thumbnail rasterization) strictly enforce `-dSAFER` to disable PostScript file and command execution primitives.

### Path Traversal and Overwrite Protection
- **Directory Traversal Neutralization**: All filename components formatted into output templates (`naming_pattern`) are sanitized to strip path separators (`/`, `\\`) and whole directory traversal path segments (`..`), while preserving valid intra-name dots (e.g. `holiday..photo.jpg`, `photo.final.jpg`).
- **Original File Preservation**: The original file is strictly read-only and is never modified or overwritten. Collisions are handled deterministically with numeric suffixes (`-1`, `-2`).
- **Symlink Overwrite and Follow Prevention**: Output path generation checks `candidate.exists() or candidate.is_symlink()`, preventing collisions with or silent overwriting of preexisting regular files, symlinks, or dangling symlinks.
- **Atomic Writes & Safe Permissions**: Outputs and configuration updates are written to unpredictable temporary files in the same directory/filesystem and atomically moved into place via `os.replace` only upon full verification. Temporary files explicitly apply the process umask (`0o666 & ~umask`) rather than restrictive default `0600`, ensuring readable outputs across users and groups according to system settings. On failure or cancellation, temporary files are cleanly unlinked.

### Text, HTML, and Log Injection
- **UI Rich-Text Escaping**: Filenames rendered in Qt rich-text contexts (e.g., `ToastWindow`) are escaped with `html.escape()` to prevent markup injection.
- **Display Sanitization**: Control characters, ANSI escape sequences, carriage returns, and newlines in filenames are stripped or replaced with spaces in the donut radial window, CLI human-readable console output, and desktop notifications, while `--json` outputs preserve raw paths for scripting.
- **Log Forgery Neutralization**: All log entries emitted by the daemon sanitize inputs against ANSI escape sequences and newline injection to prevent log spoofing.

### Resource Exhaustion & Denial of Service
- **Decompression Bomb Protection**: Pillow's pixel limit is explicitly set to `Image.MAX_IMAGE_PIXELS = 89_478_485` (~350 MB uncompressed RGB) with `DecompressionBombWarning` treated strictly as an engine error, preventing unbounded memory allocation and process aborts.
- **PDF Size and Page Limits**: PDF inputs are capped before Ghostscript invocation at `MAX_PDF_SIZE_BYTES = 500_000_000` (500 MB) and `MAX_PDF_PAGES = 2_000` pages, failing honestly with clear error messages.
- **FIFO & Device Guarding (TOCTOU Resistance)**: Pre-drop and classification file sniffing checks `os.stat` mode and immediately opens headers with `os.O_NONBLOCK | os.O_RDONLY`. Post-open `os.fstat(fd)` verifies that the opened descriptor is a regular file (`stat.S_ISREG`), preventing TOCTOU symlink/FIFO swap race conditions.
- **Batch Clamping**: Batch classification caps header sniffing at 50 files to prevent unbounded I/O latency.
- **ENOSPC Handling**: Clean recovery from disk-full errors (`errno.ENOSPC`), deleting all temporary artifacts and returning an honest failure result.

### Configuration & State Hardening
- **Strict Validation**: Bounded validation for all numeric fields; rejection of `NaN`, `Infinity`, negative numbers, and values $>100\text{ GB}$. Favourites, recents, and presets are capped against hostile payload flooding.
- **Private Permissions**: Configuration and state directories are created with `0o700` (user-only), and daemon log files are restricted to `0o600`.
- **Automatic Backup Recovery**: Corrupted or unparseable configuration files are backed up to `.bak` files with automatic fallback to safe defaults.

---

## 3. What `smol` Does NOT Protect Against

- **Compromised User Accounts**: An attacker with shell access under the same local user account can directly read or alter files, configuration, and state directories.
- **Vulnerabilities in Underlying C Libraries**: Zero-day vulnerabilities in system libraries (e.g., `libjpeg`, `libpng`, `libheif`, or Ghostscript's internal renderer beyond `-dSAFER`) require system-level security updates.
- **Physical Machine Access**: Keyloggers or hardware sniffers capturing global keystrokes.

---

## 4. Reporting a Security Vulnerability

If you discover a security vulnerability in `smol`, please report it responsibly by contacting the project maintainers directly or opening a confidential security advisory on GitHub. Please do not report security vulnerabilities via public GitHub issues.
