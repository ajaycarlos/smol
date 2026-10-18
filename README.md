# smol

> Shrink any file to at most a chosen size. Offline, private, and honest.

`smol` is a Linux-first desktop utility that compresses files to fit strict size limits (like upload forms requiring images under 100 KB) without degrading quality more than necessary.

- **Output guarantee**: The output is always $\le$ target bytes (using decimal 1 KB = 1,000 bytes).
- **Non-destructive**: Your original file is never overwritten. Outputs are saved alongside as `<name>_<size>.<ext>`.
- **Honest**: If a target cannot be reached without ruining the file below minimum dimension/quality floors, `smol` tells you honestly instead of creating an unusable file or pretending success.
- **Offline & Private**: Zero network calls, zero tracking.

---

## Try it

### 1. Installation

Prerequisites: Python 3.12+ and [uv](https://docs.astral.sh/uv/) (or standard venv/pip). External tools like `notify-send` are used for desktop notifications.

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

### 2. Right-Click File Manager Integration

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

### 3. CLI Examples (`smol shrink`)

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
