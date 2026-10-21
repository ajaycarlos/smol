# Architecture — smol

This document details the system design, component boundaries, and execution pipelines of `smol`.

---

## 1. System Overview & Component Diagram

`smol` is built on a modular, decoupled architecture where the **core compression engine is 100% headless** and can be driven identically by the CLI, desktop file managers, or the interactive donut overlay.

```
                         ┌─────────────────────────────┐
                         │   X11 Desktop Environment   │
                         │   (Cinnamon / MATE / Xfce)  │
                         └──────────────┬──────────────┘
                                        │
             [Hold Super + Drag File]   │   [Right-Click File]
                        │               │           │
                        ▼               │           ▼
             ┌─────────────────────┐    │   ┌───────────────────────────────┐
             │     smol daemon     │    │   │      smol.integrations        │
             │   (KeyHoldTracker,  │    │   │ (Nemo / Nautilus / Dolphin /  │
             │     DragTracker)    │    │   │     Thunar context menus)     │
             └──────────┬──────────┘    │   └───────────────┬───────────────┘
                        │               │                   │
                     summons            │                   │
                        ▼               │                   │
             ┌─────────────────────┐    │                   │
             │       smol.ui       │    │                   │
             │   (DonutWindow,     │    │                   │
             │   Toast, Settings)  │    │                   │
             └──────────┬──────────┘    │                   │
                        │               │                   │
                 delegates work         │                   │
                        ▼               │                   │
             ┌─────────────────────┐    │                   │
             │    ShrinkWorker     │    │                   │
             │      (QThread)      │    │                   │
             └──────────┬──────────┘    │                   │
                        │               │                   │
                        └───────┬───────┴───────────┬───────┘
                                │                   │
                                ▼                   ▼
             ┌──────────────────────────────────────────────┐
             │                   smol.cli                   │
             │  (`smol shrink FILE... --max <size> --json`) │
             └──────────────────────┬───────────────────────┘
                                    │
                                    ▼
             ┌──────────────────────────────────────────────┐
             │                  smol.core                   │
             │             (Strictly Headless)              │
             │                                              │
             │  ┌─────────────────┐    ┌─────────────────┐  │
             │  │   image.py      │    │     pdf.py      │  │
             │  │  (Pillow /      │    │  (Ghostscript / │  │
             │  │   pillow-heif)  │    │      qpdf)      │  │
             │  └─────────────────┘    └─────────────────┘  │
             │  ┌────────────────────────────────────────┐  │
             │  │  router.py, size.py, paths.py, config  │  │
             │  └────────────────────────────────────────┘  │
             └──────────────────────┬───────────────────────┘
                                    │
                         writes atomically next to src
                                    ▼
                     [ original_100KB.jpg (verified <= target) ]
```

---

## 2. Component Responsibilities

| Subsystem | Modules | Responsibilities | Invariants |
|---|---|---|---|
| **Engine** (`smol.core`) | `image.py`, `pdf.py`, `router.py`, `size.py`, `paths.py`, `config.py`, `result.py` | Compression logic, format ladders, binary searches, disk verification, atomic file creation. | **Strictly Headless**: No Qt/UI imports. Output disk bytes must be $\le$ target bytes. Original files are never modified. |
| **CLI** (`smol.cli`) | `cli.py` | Unified console command entry point: `shrink`, `donut`, `daemon`, `settings`, `integrate`, `doctor`. | Non-zero exit code on failure. Stable human-readable and `--json` schemas. |
| **Daemon** (`smol.daemon`) | `service.py`, `listener.py` | Global key hold detection (`python-xlib`), pointer tracking (`XQueryPointer`), drag thresholding, summon coordinator. | $\le 1\%$ idle CPU. Ungrabs X11 grabs on any crash/exit. Wayland guard prevents invalid grabs. |
| **UI** (`smol.ui`) | `donut_window.py`, `donut_geometry.py`, `worker.py`, `prediction.py`, `custom_input.py`, `toast.py`, `settings_window.py` | Frameless translucent Qt 6 overlays, smooth 60 fps animations, debounced hover predictions, toast feedback, settings window. | **Off-UI Execution**: Engine compression runs in background `QThread` workers. UI never hangs. Esc always dismisses. |
| **Integrations** (`smol.integrations`) | `manager.py`, `autostart.py`, `notifier.py` | Native context menu actions (.nemo_action, Nautilus scripts, .desktop service menus), XDG autostart, desktop notifications. | Non-destructive install and clean reversible uninstallation. Safe shell-quoting for hostile filenames. |

---

## 3. Data Pipelines

### 3.1 Image Pipeline (`smol.core.image`)
1. **Validation & Sniffing**: Inspects input file headers (max 32 bytes). Rejects non-regular files and FIFOs.
2. **Decompression Bomb Guard**: Verifies pixel count $\le 89.5 \text{ MP}$ before decoding.
3. **Normalization**:
   - Transposes EXIF orientation into pixel coordinates (`ImageOps.exif_transpose`).
   - Strips GPS and camera metadata (unless `--keep-metadata` requested).
   - Converts color profiles / CMYK / grayscale to sRGB via LittleCMS.
   - Flattens transparent alphas onto white backgrounds when writing JPEGs.
4. **Already Small Bypass**: If `original_bytes <= target_bytes`, returns success immediately without touching the file.
5. **Quality Binary Search**: Performs binary search over quality range (floor 60 to 95) with optimized 4:2:0 subsampling.
6. **Lanczos Downscaling Ladder**: If floor quality at 100% resolution exceeds target, calculates estimated scale ratio and steps down resolutions using high-quality Lanczos resampling.
7. **Minimum Dimension Floor**: Halts at `min_dim = 200 px` short side. If target is still unreached, returns honest failure detailing smallest achievable size.
8. **Lossy Scale Refinement**: When downscaling fits at quality floor, optimizes scale upward to maximize pixel resolution and land predictably in the 92–99% size window.
9. **Atomic Write & Post-Write Verification**: Writes to a temporary file in destination folder. Measures exact disk bytes. Reopens file to verify integrity. Replaces atomically. Unlinks and fails if disk size exceeds target bytes.

### 3.2 PDF Pipeline (`smol.core.pdf`)
1. **Type & State Check**: Verifies PDF syntax and checks if already $\le$ target bytes.
2. **Ghostscript DPI Ladder**: Evaluates 6 predefined rungs of decreasing raster resolution and distiller quality:
   - `200 DPI` (q80) $\to$ `150 DPI` (q75) $\to$ `120 DPI` (q70) $\to$ `96 DPI` (q65) $\to$ `72 DPI` (q55) $\to$ `60 DPI` (q50).
   - Stops at the highest quality rung whose output fits $\le$ target bytes.
3. **Object-Stream Optimization**: Passes intermediate PDF through `qpdf --object-streams=generate` to compress non-image structures.
4. **Syntax Verification**: Runs `qpdf --check --warning-exit-0` before accepting output.
5. **Atomic Write & Honest Limits**: Text-only vector PDFs that cannot shrink report honest failure without corruption.

---

## 4. Key Invariants & Safety Guarantees

1. **Inviolable Size Guarantee**: An output file is NEVER released to the user if its disk size exceeds target bytes.
2. **Source Immutability**: The original input file is strictly read-only; destination outputs are created adjacent to the original with collision counters (`-1`, `-2`).
3. **Clean Cancellation**: Pressing `Esc` or clicking Undo kills any active worker threads or child subprocesses immediately and removes partial files, leaving 0 leftovers.
4. **Offline Isolation**: No network calls, remote telemetry, or web dependencies exist in any layer.
