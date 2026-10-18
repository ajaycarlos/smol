# PROGRESS.md

Agents: update this after EVERY task. Keep it short and current. New sessions rely on it.

## Current milestone
M1 — Image engine + CLI (M0 Feasibility Spikes complete).

## Environment
- Distro / desktop / session type: Linux / X-Cinnamon / x11
- File manager: nemo (installed)
- Python: 3.12.3
- Optional & required tools: uv, ffmpeg, ffprobe, gs (Ghostscript), qpdf, git, notify-send
- Chosen path from SPIKE.md: Path A (X11 full Filee-like experience)
- Default trigger key: Super (primary default; Ctrl+Alt secondary; plain Ctrl avoided due to file manager copy collision)

## Done
- Bootstrap repository structure (P0.1): pyproject.toml, package init files,
  tests/gitignore/license, `smol --version` support
- Add `smol doctor` subcommand (P0.2): checklist table with ✓/✗ and install hints
  for Python 3.12+, external tools, desktop environment, and file manager detection.
  Unit tests covering present, missing, and mock conditions.
- Create Spike A (`spikes/a_key_hold.py`): global key hold detection for candidate
  trigger keys (Ctrl+Alt, Super, Right Alt, Right Ctrl) measuring hold time in ms.
  Supports X11 (python-xlib via query_keymap and XRecord) and Linux evdev (/dev/input).
  Unit tests in `tests/test_spike_a.py`.
- Create Spike B (`spikes/b_drag_and_cursor.py`): detect file manager drag start
  while candidate trigger key is held and read global cursor position in screen coordinates.
  Supports X11 global cursor reading via XQueryPointer and reports architectural
  evidence with screen centre fallback for Wayland. Unit tests in `tests/test_spike_b.py`.
- Create Spike C (`spikes/c_overlay_drop.py`): 300×300 translucent, round, frameless,
  always-on-top drop target window using PySide6. Accepts `text/uri-list` file drops.
  Evaluates Variant 1 (window visible before drag) and Variant 2 (window appears during
  active drag on a timer). Verifies instant appearance (<150 ms target met, ~1–3 ms)
  and non-blocking interaction with the active file manager (`WA_ShowWithoutActivating`).
  Unit tests in `tests/test_spike_c.py`.
- Synthesize feasibility spike results in `SPIKE.md` (M0 complete): Documented machine
  compatibility table, evaluated trigger key collision risks (plain Ctrl avoided due to
  file manager copy behavior), selected Path A (full Filee-like cursor overlay on X11),
  updated `PLAN.md` Section 9 and Milestone M4.
- Implement test sample generation (`tests/make_samples.py`) and on-demand pytest fixture
  (`samples_dir` in `tests/conftest.py`) generating 11 synthetic test images: portrait (~1.2 MB,
  gradient+noise), landscape, screenshot PNG, tiny, already-small (~30 KB), grayscale, transparent
  PNG, CMYK, EXIF-rotated (tag 6), WebP photo, and incompressible noise floor. Verified in
  `tests/test_samples.py` with `Pillow` and `pillow-heif` dependencies.
- Implement smol.core foundation utilities:
  - `parse_size` and `format_size` in `smol/core/size.py` with 1 KB = 1000 bytes decimal sizing, case-insensitivity, whitespace tolerance, and clear error messages.
  - `Result` dataclass in `smol/core/result.py` with standard fields (`ok`, `output_path`, `original_bytes`, `final_bytes`, `width`, `height`, `quality`, `steps`, `warning`, `error`).
  - `output_path` in `smol/core/paths.py` with non-overwriting collision resolution (`-1`, `-2`).
  - Unit tests in `tests/core/test_basics.py` validating standard sizes, boundary sizes, and hostile filenames (spaces, unicode, leading dash, uppercase extensions, no extension).
- Implement smol.core image shrinking foundation (`smol/core/image.py`):
  - `shrink_image(src, target_bytes, options)` JPEG compression pipeline: decode, EXIF rotation transpose (`ImageOps.exif_transpose`), metadata stripping, sRGB conversion (flattening alpha onto white background).
  - Handles already <= target files by returning `Result(ok=True)` with warning note without copying or modifying original.
  - Quality binary search between floor (60) and 95 with `optimize=True`, 4:2:0 subsampling, and baseline encoding.
  - Clean honest failure if quality floor 60 exceeds target size without downscaling.
  - Verification on reopening and atomic write via temporary file in target directory.
  - Comprehensive unit tests in `tests/core/test_image.py` covering portrait and landscape targets (100 KB and 200 KB) landing between 90% and 100% of target, original file integrity, already-small bypass, and atomic write.
- Implement downscaling ladder and honest failure in `smol/core/image.py`:
  - Extended `shrink_image` with Lanczos downscaling loop when quality floor 60 at full resolution exceeds target size.
  - Initial scale estimation `scale = sqrt(target / size_at_floor) * 0.98`, Lanczos resampling, quality search in 60–90, and iterative 0.9 scale stepping down to configurable minimum short-side floor (`min_dim`, default 200 px).
  - Honest failure reporting when target is unreachable at minimum dimension floor (`"Smallest I can make this is ~... at 200 px; try a larger target."`) preserving original file and creating no partial files.
  - Extended `Result` dataclass in `smol/core/result.py` with `scale: float | None` recording downscale ratio along with `quality` and `steps` (total encode attempt count).
  - Unit tests in `tests/core/test_image.py` verifying downscaling success (portrait to 100 KB landing >= 90%), incompressible noise floor honest failure (`noise_cannot_shrink.jpg` targeting 5 KB), and custom `min_dim` constraints.
- Handle format edge cases, metadata stripping, and decompression bomb guard in `shrink_image`:
  - Strip GPS and camera EXIF metadata by default, with option to preserve (`options={"strip_metadata": False}`).
  - Bake EXIF rotation into pixels via `ImageOps.exif_transpose`, resetting orientation tag to 1 if metadata is preserved to prevent double-rotation.
  - Convert CMYK and other color modes to sRGB cleanly.
  - Convert embedded ICC profiles to standard sRGB via `ImageCms.profileToProfile`.
  - Flatten PNG transparency (RGBA, LA, palette transparency) onto solid white for JPEG output.
  - Guard against decompression bombs by checking pixel limits (`max_pixels` option) and catching `Image.DecompressionBombError` with clear error messages.
  - Add comprehensive unit tests in `tests/core/test_image.py` asserting no GPS tags, swapped dimensions for rotated samples, white background for transparent PNGs, sRGB output for CMYK/grayscale, and decompression bomb error handling.
- Add format-specific handlers in smol.core (smol/core/image.py):
  - WebP quality search and Lanczos downscale matching JPEG behavior while keeping .webp format.
  - PNG palette quantisation ladder (256→128→64 colours) and downscaling with scale refinement, keeping .png format by default.
  - PNG fallback to JPEG with a warning when target is unreachable within constraints and allow_convert=True; honest failure suggesting allow_convert when False.
  - Auto-conversion of HEIC and AVIF inputs to JPEG output (.jpg).
  - Registered pillow_heif opener for HEIF/AVIF decoding support in Pillow.
  - Supported optional target extension override in smol/core/paths.py output_path.
  - Added sample.heic, sample.avif, and realistic screenshot.png (~855 KB) to tests/make_samples.py and updated tests/test_samples.py.
- VERIFY: PNG screenshot sample reaches 100 KB without changing format (98,733 bytes, 98.7% of target). uv run pytest (89 passed), uv run ruff check . clean.

## Next
- Milestone M1: Implement smol shrink CLI subcommand with options (--max, --json, --dry-run, --keep-format/--allow-convert).


## Decisions
- 2026-10-18: Choose Path A (full Filee-like experience) for Linux X11/Cinnamon desktop based on M0 spike benchmarks (<4 ms overlay latency, XQueryPointer real-time coordinates, python-xlib key monitoring).
- 2026-10-18: Choose Super (Windows key) as default trigger key with Ctrl+Alt as secondary option; plain Ctrl rejected because Ctrl+drag triggers file copy in Linux file managers.

## Known issues
- (none yet)
