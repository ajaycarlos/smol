# smol

> **Shrink any file to at most a chosen size.**
> Hold a key, drag a file, drop it on a size in a donut menu at the cursor. Offline, private, and honest.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](MIT%20LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-green.svg)](https://www.python.org/)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux%20(X11)-orange.svg)]()

`smol` is a Linux desktop tool that shrinks files to fit strict size limits (like a portal demanding a photo under 100 KB or a PDF under 1 MB) without opening a browser, uploading your data to third-party servers, or degrading quality more than necessary.

```
       [ Hold Super ]  +  [ Drag File ]
                    │
                    ▼
           ╭─────────────────╮
           │   20 KB   50 KB │
     2 MB  │                 │  100 KB
           │   [photo.jpg]   │
     1 MB  │    (1.2 MB)     │  200 KB
           │                 │
           │  Custom  500 KB │
           ╰─────────────────╯
                    │
           [ Drop on 100 KB ]
                    │
                    ▼
       photo_100KB.jpg (98.4 KB)  ✓ Done
```

---

## Demo

<!-- DEMO_GIF_PLACEHOLDER: Replace with assets/demo.gif when screen recording is captured -->
![smol demo walkthrough](assets/demo-placeholder.png)

*(To launch an interactive demo of the donut overlay on your own desktop right now, run `smol donut --demo`).*

---

> [!IMPORTANT]
> ### Requirements & Session Compatibility
>
> | Feature | X11 Sessions | Wayland Sessions |
> |---|---|---|
> | **Hold-Key Donut Overlay** (`smol daemon`) | **Supported** (Default) | *Not supported in v1.0* (Requires global key & pointer grab) |
> | **File Manager Right-Click** ("Shrink to...") | **Supported** | **Supported** |
> | **Terminal Command-Line** (`smol shrink`) | **Supported** | **Supported** |
> | **Interactive Settings** (`smol settings`) | **Supported** | **Supported** |
>
> - **Hold-key donut requires X11**: Linux desktops using native X11 (such as **Cinnamon**, **MATE**, **Xfce**, or choosing **"Ubuntu on Xorg" / "GNOME on Xorg"** at the login display manager gear icon) support the full hold-key drag-and-drop overlay.
> - **Wayland users**: You can use the file manager right-click integration, the CLI, and the standalone `smol donut --files <file>` palette on any desktop session.
>
> **System Packages**:
> - **PDF compression**: Requires `ghostscript` and `qpdf` (`sudo apt install ghostscript qpdf`).
> - **Qt 6 / PySide6**: Requires `libxcb-cursor0` on Debian/Ubuntu (`sudo apt install libxcb-cursor0`).
> - **AppImage users**: Ubuntu 22.04+ requires FUSE (`sudo apt install libfuse2t64` or `libfuse2`).

---

## Core Promises (Engine Invariants)

1. **Output is always $\le$ target bytes**: 1 KB = 1,000 bytes (decimal standard, safe for upload forms using 1,000 or 1,024). `smol` aims for 92–99% of the target, never over it.
2. **Original files are NEVER modified or overwritten**: The output is saved next to the original as `<name>_<size>.<ext>` (e.g. `portrait_100KB.jpg`). If a file already exists, it adds `-1`, `-2`.
3. **Honest failure**: If reaching a target would degrade the image below minimum dimension floors (200 px) or quality floors, `smol` fails honestly, reports the smallest achievable size, and lets you retry at that size. It never creates an oversized file and calls it success.
4. **100% Offline & Private**: Zero network calls, zero analytics, zero external API dependencies. All processing happens locally on your CPU.
5. **Format preservation**: Keeps input format by default (JPEG $\to$ JPEG, PNG $\to$ PNG, WebP $\to$ WebP, PDF $\to$ PDF). Metadata and GPS tags are stripped by default for privacy.

---

## Installation

Choose the installation method that suits your workflow:

### Option 1: Standalone AppImage (Recommended for testing)

No Python setup required. Download the pre-built x86_64 AppImage from the releases:

```bash
# 1. Install system dependencies (PDF tools + FUSE)
sudo apt update && sudo apt install -y ghostscript qpdf libxcb-cursor0 libfuse2t64

# 2. Make executable
chmod +x smol-0.9.0-x86_64.AppImage

# 3. Test run
./smol-0.9.0-x86_64.AppImage --version
./smol-0.9.0-x86_64.AppImage doctor
```

> [!NOTE]
> If FUSE is unavailable (e.g., inside Docker, WSL, or minimal live environments), run with:
> `./smol-0.9.0-x86_64.AppImage --appimage-extract-and-run <command>`

### Option 2: Debian / Ubuntu Package (`.deb`)

Install system-wide with standard package management:

```bash
# 1. Install runtime dependencies
sudo apt update && sudo apt install -y ghostscript qpdf libxcb-cursor0

# 2. Install the package
sudo dpkg -i dist/smol_0.9.0_amd64.deb || sudo apt install -f -y

# 3. Verify
smol --version
smol doctor
```

This installs `/opt/smol/`, symlinks `/usr/bin/smol`, registers desktop entries in `/usr/share/applications/`, and installs application icons into `/usr/share/icons/hicolor/`.

### Option 3: via `uv` or Python Virtual Environment

If you develop with Python or prefer isolated user-space tools:

```bash
# Option A: Install as an isolated user tool with uv
uv tool install .

# Option B: Clone and run in a virtualenv
git clone https://github.com/your-username/smol.git
cd smol
uv venv
source .venv/bin/activate
uv pip install -e .
```

### Option 4: Quick-Install Script

The repository includes a helper installation script:

```bash
./install.sh
```

---

## Usage

`smol` offers three distinct interaction paths:

### 1. The Hold-Key Donut Overlay (X11)

The fastest way to compress a file:

1. **Hold the trigger key** (Default: `Super` / Windows key).
2. **Drag a file** in your file manager (e.g., Nemo, Nautilus, Dolphin, Thunar).
3. The liquid-glass donut menu summons under your cursor within 25 ms.
4. **Hover** over any target segment to preview predicted size and resolution (e.g., `~96 KB, 800×600`). Segments larger than the input file are dimmed.
5. **Drop the file** onto your chosen size segment (or drop onto **Custom...** for a specific byte count).
6. A live circular countdown shows compression progress.
7. Upon completion, a non-intrusive toast notification appears with:
   - **Open folder**: Reveals the new file in your file manager.
   - **Copy path**: Copies the absolute path to your clipboard.
   - **Undo**: Safely deletes the generated file (the original is never touched).

*(Press `Esc` at any time to dismiss the donut).*

### 2. Right-Click Context Menu Integration

Work directly from your desktop file manager without running background listeners:

```bash
# Install "Shrink to..." submenu in your file manager
smol integrate install

# Check status
smol integrate status
```

Supported file managers:
- **Nemo** (Cinnamon)
- **Nautilus** (GNOME)
- **Dolphin** (KDE Plasma)
- **Thunar** (Xfce)

Right-click any image or PDF, open the **Shrink to...** menu, and select your target size (e.g., `100 KB`). A desktop notification reports the before and after sizes.

To remove right-click actions cleanly:
```bash
smol integrate uninstall
```

### 3. Command Line (`smol shrink`)

Use `smol` directly in scripts, terminals, or automation pipelines:

```bash
# Shrink an image to under 100 KB
smol shrink photo.jpg --max 100KB

# Shrink multiple images with desktop notifications
smol shrink *.jpg --max 200KB --notify

# Compress a PDF document to under 1 MB
smol shrink scanned_contract.pdf --max 1MB

# Dry-run prediction without writing any files
smol shrink banner.png --max 50KB --dry-run

# Allow format conversion (e.g., PNG -> JPEG if PNG cannot fit)
smol shrink screenshot.png --max 30KB --allow-convert

# Machine-readable JSON output
smol shrink portrait.jpg --max 100KB --json

# Save outputs to a custom destination directory
smol shrink photo.jpg --max 100KB --out-dir ./compressed/
```

---

## The Trigger Key & Why Plain Ctrl is Not Used

- **Default Key**: `Super` (the Windows key / Command key).
- **Secondary Preset**: `Ctrl+Alt` (configurable in `smol settings`).

### Why not plain `Ctrl`?
In all major Linux desktop file managers (Nemo, Nautilus, Dolphin, Thunar), holding `Ctrl` while dragging a file triggers **"Copy File"** instead of move. Reusing plain `Ctrl` for summoning an overlay causes unintended file duplications across your folders.

### Why not plain `Alt`?
In Linux window managers (X11 / Xorg), `Alt + Click/Drag` is reserved for moving application windows across the screen.

`Super` provides a collision-free modifier key that file managers ignore during drag gestures.

---

## Donut Modes: Classic Ring vs. Smart Ring

You can configure the ring layout in `smol settings`:

- **Classic Fixed Ring (Default)**:
  - Stable, predictable 8-segment layout: `20 KB`, `50 KB`, `100 KB`, `200 KB`, `500 KB`, `1 MB`, `2 MB`, `Custom...`.
  - Segments larger than the input file are dimmed.
  - Builds physical muscle memory: 100 KB is always in the exact same physical direction from your cursor.
- **Smart Ring (Opt-in)**:
  - Dynamically computes and ranks target segments tailored to the dragged file's size and feasibility.
  - Ideal for users handling wildly varying file sizes from 100 KB to 50 MB.

---

## Settings & Configuration

Launch the liquid-glass configuration panel:

```bash
smol settings
```

The settings panel allows you to configure:
- **Trigger key**: Capture any key or modifier combination with live conflict warnings.
- **Target sizes**: Add, remove, and reorder segments on the donut ring.
- **Output directory**: Save next to the original file (default) or send all shrunk outputs to a designated folder.
- **Format options**: Toggle format preservation and lossy format fallback (`--allow-convert`).
- **Privacy**: Strip GPS and camera EXIF metadata (enabled by default).
- **Accessibility**: Enable **Reduce motion** for instant fades and zero animation delays.
- **Autostart**: Launch the hold-key daemon automatically on desktop login.

Settings are stored in standard XDG format at `~/.config/smol/config.toml`.

---

## Supported Formats & Honest Limits

### Supported Formats (v1.0)

| Format | Input | Output | Optimization Method |
|---|---|---|---|
| **JPEG** | `.jpg`, `.jpeg` | `.jpg` | Binary search quality (floor 60 to 95) $\to$ Lanczos downscaling ladder |
| **PNG** | `.png` | `.png` | Palette quantization (256 $\to$ 128 $\to$ 64 colors) $\to$ downscaling |
| **WebP** | `.webp` | `.webp` | Binary search quality $\to$ Lanczos downscaling ladder |
| **HEIC / AVIF** | `.heic`, `.avif` | `.jpg` | Decodes via `pillow-heif` $\to$ sRGB $\to$ JPEG compression pipeline |
| **PDF** | `.pdf` | `.pdf` | 6-rung Ghostscript DPI ladder (200 $\to$ 60 DPI) + `qpdf` stream optimization |

### Known Limitations & Honest Compression Limits

`smol` does not perform "magic" that destroys files, and upholds transparent limits:
1. **X11 Requirement for Hold-Key Donut**: The hold-key donut overlay requires an X11 desktop session. On Wayland sessions, use the right-click file-manager context menu or the CLI `smol shrink` (both work on any session type).
2. **Minimum Dimension Floor**: Images will never be downscaled below `200 px` on their short side (configurable via `--min-side` or Settings) to prevent creating unreadable postage stamps.
3. **Incompressible Data**: If an image or PDF is already tightly compressed and cannot reach your target even at lowest quality and minimum dimensions, `smol` halts and reports honest feedback:
   ```
   Smallest I can make this is ~142 KB at 200 px; try a larger target.
   ```
4. **Text-Only Vector PDFs**: Vector text and embedded fonts cannot be raster-downsampled. `smol` reports the smallest achievable size without corrupting vector paths.
5. **PNG Format Preservation**: Input PNGs keep the `.png` format by default. If 64-color palette quantization cannot reach the target, use `--allow-convert` or enable it in Settings to allow fallback to JPEG.
6. **Archive Drag Protocol**: Dragging files directly from archive managers (e.g. File Roller) does not provide file URIs at drag-enter under X11 Xdnd protocol; `smol` falls back to classifying at drop time.
7. **Decompression Bomb Guard**: Images exceeding 89.5 million pixels are safely refused to protect system memory.
8. **Already Small Enough**: If a file is already smaller than the target, `smol` skips re-compression, leaving the original untouched.

---

## Troubleshooting

### Run `smol doctor`
Whenever something feels off, run:
```bash
smol doctor
```
`smol doctor` inspects your Python environment, display server (X11 vs Wayland), installed desktop environment, file manager, and external dependencies (`gs`, `qpdf`).

### Common Issues

#### 1. The donut does not appear when holding Super and dragging
- Check your session type with `echo $XDG_SESSION_TYPE`. If it reports `wayland`, see the [Requirements](#requirements--session-compatibility) box above.
- Verify the background daemon is running:
  ```bash
  smol daemon status
  ```
  If not running, start it with `smol daemon start`.
- Inspect daemon activity logs:
  ```bash
  smol daemon logs --lines 20
  ```

#### 2. AppImage fails with `error while loading shared libraries: libfuse.so.2`
On Ubuntu 22.04+ and Debian 12+, install the modern FUSE compatibility library:
```bash
sudo apt install -y libfuse2t64  # Or libfuse2
```
Alternatively, run without FUSE:
```bash
./smol-*.AppImage --appimage-extract-and-run doctor
```

#### 3. Qt / PySide6 complains about `libxcb-cursor.so.0`
Install the missing X11 XCB cursor library:
```bash
sudo apt install -y libxcb-cursor0
```

#### 4. PDF compression fails with missing tool error
Make sure Ghostscript and qpdf are installed on your host system:
```bash
sudo apt install -y ghostscript qpdf
```

---

## Uninstallation

To cleanly remove `smol` from your system:

### 1. Remove File Manager & Autostart Integrations
```bash
smol integrate uninstall
smol integrate autostart uninstall
```

### 2. Remove the Application

- **If installed via `.deb`**:
  ```bash
  sudo apt remove -y smol
  ```
- **If installed via `uv tool`**:
  ```bash
  uv tool uninstall smol
  ```
- **If using AppImage**:
  Simply delete the `.AppImage` file.
- **Convenience script**:
  ```bash
  ./uninstall.sh
  ```

### 3. Optional: Remove User Configuration
To remove stored custom sizes, settings, and daemon state:
```bash
rm -rf ~/.config/smol ~/.local/state/smol ~/.cache/smol
```

---

## Not Supported Yet (Roadmap)

The following features are intentionally deferred for future releases (see [BACKLOG.md](BACKLOG.md)):
- **Video & Audio Compression**: Deferred to v1.1 to guarantee rock-solid image and PDF quality for v1.0.
- **Office Documents**: `.docx`, `.pptx`, `.xlsx` image re-compression planned for post-v1.0.
- **Wayland Native Hold-Key Overlay**: Waiting for standardized Wayland layer-shell / global key capture protocols.
- **Windows Support**: Windows 10 & 11 planned for v2.0 (Windows 7/8 are unsupported).
- **Exact Target Padding**: Artificially inflating small files to reach an exact minimum byte size is deferred to v1.3+.

---

## Architecture & Design Decisions

- For architectural diagrams and data flows, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
- For settled architectural and product design decisions, see [docs/decisions/](docs/decisions/) and [DECISIONS.md](DECISIONS.md).

---

## License

This project is licensed under the [MIT License](MIT%20LICENSE).
See [NOTICE](NOTICE) for third-party component licenses and attributions.
