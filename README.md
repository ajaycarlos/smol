# smol

> Shrink any file to at most a chosen size. Offline, private, and honest.

`smol` is a Linux-first desktop utility that compresses files to fit strict size limits (like upload forms requiring images under 100 KB) without degrading quality more than necessary.

- **Output guarantee**: The output is always $\le$ target bytes (using decimal 1 KB = 1,000 bytes).
- **Non-destructive**: Your original file is never overwritten. Outputs are saved alongside as `<name>_<size>.<ext>`.
- **Honest**: If a target cannot be reached without ruining the file below minimum dimension/quality floors, `smol` tells you honestly instead of creating an unusable file or pretending success.
- **Offline & Private**: Zero network calls, zero tracking.

### Supported Formats (v1.0)
- **Images**: JPEG, PNG, WebP, HEIC (and AVIF)
- **Documents**: PDF only

*(Video and audio compression are deferred to v1.1).*

---

## Try it

### 1. AppImage (Standalone Executable)

A self-contained AppImage is provided for Linux (x86_64), containing all Python dependencies and PySide6:

```bash
# Make executable and run
chmod +x smol-0.9.0-x86_64.AppImage
./smol-0.9.0-x86_64.AppImage --version
./smol-0.9.0-x86_64.AppImage donut --demo
./smol-0.9.0-x86_64.AppImage shrink photo.jpg --max 100KB
```

#### FUSE Requirement (Ubuntu 22.04+)
AppImages require FUSE 2 to mount. On Ubuntu 22.04, 24.04+, and newer Debian/Mint systems, install `libfuse2`:
```bash
sudo apt install libfuse2t64   # Ubuntu 24.04+ / Debian 13
# or: sudo apt install libfuse2  # Ubuntu 22.04 / Debian 12
```

#### Fallback Without FUSE (`--appimage-extract-and-run`)
If FUSE is unavailable (e.g., inside containers, CI environments, or live USBs), use the built-in fallback:
```bash
./smol-0.9.0-x86_64.AppImage --appimage-extract-and-run <command>
```

#### External Tools (Ghostscript & qpdf)
Ghostscript (`gs`) and `qpdf` are **not bundled** inside the AppImage. To shrink PDF files, install them via your package manager:
```bash
sudo apt install ghostscript qpdf
```
Run `./smol-0.9.0-x86_64.AppImage doctor` to verify system tool availability.

### 2. Manual Installation via uv / Python

```bash
# Clone and enter directory
cd smol

# Create virtual environment and install in editable mode
uv venv
source .venv/bin/activate
uv pip install -e .

# Check environment, dependencies, and file manager detection
smol doctor
```

### 3. Right-Click File Manager Integration

Install right-click actions for your file manager (supports **Nemo**, **Nautilus**, **Dolphin**, and **Thunar**):

```bash
# Install "Shrink to..." submenu actions
smol integrate install

# Verify integration status
smol integrate status
```

Now simply right-click any image in your file manager, select **Shrink to...**, and choose a target size (e.g. `100 KB`). A desktop notification appears showing the before and after sizes.

To remove right-click actions cleanly at any time:
```bash
smol integrate uninstall
```

### 4. CLI Examples (`smol shrink`)

You can also shrink images directly from your terminal:

```bash
# Shrink an image to under 100 KB
smol shrink photo.jpg --max 100KB

# Shrink multiple images with desktop notifications
smol shrink *.jpg --max 200KB --notify

# Allow conversion (e.g. fallback from PNG to JPEG if target is unreachable in PNG)
smol shrink screenshot.png --max 50KB --allow-convert

# Dry-run prediction without writing any files
smol shrink banner.webp --max 500KB --dry-run

# Output results as machine-readable JSON
smol shrink photo.jpg --max 100KB --json

# Save output to a specific directory
smol shrink photo.jpg --max 100KB --out-dir ./shrunk/
```

---

## Running Tests

```bash
# Run test suite
uv run pytest

# Check code formatting and linting
uv run ruff check .
```

## License

MIT
