# PROGRESS.md

Agents: update this after EVERY task. Keep it short and current. New sessions rely on it.

## Current milestone
Packaging (AppImage complete; .deb packaging next); ready for v1.0 release.

## Environment
- Distro / desktop / session type: Linux / X-Cinnamon / x11
- File manager: nemo (installed)
- Python: 3.12.3
- Optional & required tools: uv, gs (Ghostscript), qpdf, git, notify-send (ffmpeg/ffprobe optional, deferred)
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
- Implement `smol shrink FILE... --max <size>` CLI subcommand (smol/cli.py):
  - Added options: `--json` (machine-readable results), `--dry-run` (predict without writing), `--out-dir` (custom destination), `--allow-convert` (PNG to JPEG fallback), `--keep-metadata` (preserve EXIF/camera metadata), and `--min-side` (short-side pixel floor).
  - Formatted human output: `<name>  <orig> → <final>  (<w>×<h> q<quality>)`.
  - Handled exit codes: 0 for all ok, 1 for failures (impossible targets, missing/unreadable files), 2 for bad usage.
  - Added optional `out_dir` support in `smol/core/paths.py` and `dry_run` + `out_dir` handling in `smol/core/image.py`.
  - Added comprehensive test suite in `tests/test_cli_shrink.py` (12 tests) verifying argument validation, JSON schema, dry-run safety, honest impossible target reporting, options forwarding, and batch processing.
- Engine review & promise verification (v0.1.0-engine):
  - Fixed High severity gap: added post-write disk size verification in `shrink_image` ensuring `final_bytes <= target_bytes` and reopening verification directly from disk; unlinks file and returns honest failure if violated.
  - Fixed Medium severity gap: implemented lossy scale refinement for JPEG and WebP when downscaled resolution fits at `quality_floor` and max downscaled quality undershoots target; refines scale upward to maximize pixel resolution and reliably land in the 92–99% target window.
  - Fixed Medium severity gap: guarded `min_dim` to be at least 1 pixel in `shrink_image` to prevent zero-dimension crashes when non-positive limits are passed.
  - Added 40 MP test sample (`forty_mp.jpg`, 7300×5500) to `tests/make_samples.py` and test suite, completing the 15+ sample coverage specified in PLAN.md M1.
  - Added comprehensive unit tests in `tests/core/test_image.py` verifying 40 MP shrinking, lossy scale refinement hitting 92–99%, `min_dim` boundary protection, and post-write size check failure handling.
- VERIFY: `uv run smol shrink tests/samples/portrait.jpg --max 100KB` produces 99.51 KB file (470×627 q85); `uv run smol shrink tests/samples/forty_mp.jpg --max 100KB` produces 98.59 KB file (3931×2962 q89); `uv run pytest` (106 passed in 11.15s); `uv run ruff check .` clean. Tagged `v0.1.0-engine`.
- Implement `smol integrate install|uninstall|status` and desktop notifications (Milestone M2):
  - Created `smol.integrations.manager` with reversible right-click integration for Nemo (.nemo_action per size + `actions-tree.json` submenu "Shrink to…") with sizes 20 KB, 50 KB, 100 KB, 200 KB, 500 KB, 1 MB, 2 MB, alongside adapters for Nautilus, Dolphin, and Thunar.
  - Safe hostile filename quoting via `--` argument separator and `Quote=double`, protecting filenames with spaces, unicode, and leading dashes.
  - Non-destructive install and clean reversible uninstallation preserving preexisting user configurations.
  - Desktop notification support via `--notify` in `smol shrink` invoking `notify-send` for success and critical errors.
  - Added unit and CLI test suite in `tests/test_integrate.py` (7 tests).
- Implement desktop notifications and terminal fallback (`smol.integrations.notifier`):
  - Created `JobNotifier` context manager and notification dispatcher supporting `notify-send` with automatic terminal fallback.
  - Success notification formatted as `photo.jpg: 1.02 MB → 97 KB` with before and after sizes.
  - Honest engine message on failure (e.g. `Smallest I can make this is ~... at 200 px; try a larger target.`).
  - Batch job summaries (`3 files shrunk, 1 failed`, `2 files shrunk`, `2 files failed`).
  - Working notification (`Working…`) triggered when a job exceeds 1.5 seconds, cleanly cancelled when jobs complete in under 1.5 seconds.
  - Unit and integration tests in `tests/test_notifier.py` and `tests/test_integrate.py`.
  - VERIFY: right-click shrink execution with `--notify` sends notification with before/after sizes (`photo.jpg: 1.24 MB → 99.51 KB`); all 122 tests pass; ruff clean.
- Milestone M2 Polish & Release (v0.2.0):
  - Ran full test suite (122 passed in ~10s) and ruff linter (clean).
  - Synchronized package and CLI versions to 0.2.0 across `pyproject.toml`, `smol/cli.py`, and `tests/test_basic.py`.
  - Added comprehensive `README.md` with "Try it" section covering installation with uv/venv, file manager right-click integration (`smol integrate install/uninstall`), and CLI usage examples (`smol shrink`).
  - VERIFY: `smol --version` outputs `smol 0.2.0`; `uv run pytest` (122 passed); `uv run ruff check .` clean. Tagged `v0.2.0`.
- Implement pure-math donut geometry foundation (smol/ui/donut_geometry.py):
  - Created DonutGeometry and SegmentGeometry dataclass with zero Qt dependencies.
  - Segment angular spans: first segment starts at top (0°), proceeding clockwise with configurable gap angles.
  - Hit testing via segment_at(dx, dy): returns segment index or None for center hole (r < r_in), outside (r > r_out), or inter-segment gap angles.
  - Label anchor point calculations: (x, y) coordinates placed at segment midpoint angle at radius (r_in + r_out) / 2.
  - Input parameter validation for N >= 1, r_in > 0, r_out > r_in, gap_angle < 360/N.
  - Comprehensive unit test suite in tests/ui/test_donut_geometry.py covering N from 1 to 12, radial/angular boundaries, gaps, center, and outside hits.
  - VERIFY: 45 new tests passed (167 total test suite passing in ~10s); ruff check clean.

- Implement `smol donut --files FILE...` overlay window (smol/ui/donut_window.py, smol/cli.py):
  - Frameless, translucent (`WA_TranslucentBackground`), always-on-top (`WindowStaysOnTopHint`), tool overlay window centred on cursor with screen boundary clamping.
  - Painted with QPainter using `donut_geometry` with 8 segments: 20 KB, 50 KB, 100 KB, 200 KB, 500 KB, 1 MB, 2 MB, Custom…
  - Segments larger than the input file are dimmed (rgba 0,0,0,120) with 35% label opacity and unclickable; Custom… and active segments remain 100% white.
  - Liquid glass visual treatment: desktop snapshot Gaussian blur behind donut, semi-transparent dark tint (rgba 15,15,25,180), outer edge light bend highlight gradient, inner ring highlight (rgba 255,255,255,40), 1px thin separators (rgba 255,255,255,30), hover brightening with subtle radial glow behind labels, and overall 0.96 window opacity.
  - Equalized segment separators removing 12 o'clock gap imbalance; enhanced centre typography (10pt bold filename, 9pt demibold size) and thumbnail soft drop shadow.
  - Dismissal on Esc key press or clicking outside the outer donut ring.
  - Segment click prints chosen size to stdout and cleanly exits.
  - Comprehensive unit and CLI test suite in `tests/ui/test_donut_window.py` and `tests/test_cli_donut.py` (18 tests).
  - VERIFY: `uv run smol donut --help` displays usage; all 185 tests pass in ~11s; `uv run ruff check` clean.

- Implement Donut hover predictions with debounce and caching (smol/ui/prediction.py, smol/ui/donut_window.py):
  - Created `PredictionWorker` QThread computing `shrink_image(..., dry_run=True)` off the UI thread without blocking the Qt event loop.
  - Implemented `PredictionService` with 150 ms debounce timer, cooperative stale request cancellation on hover change / leave, and per-(file, target_bytes) prediction caching.
  - Formatted predictions as `~{size}, {w}×{h}` (e.g. `~96 KB, 600×800`) or concise honest failure messages (`Smallest ~...`), rendered in the center card in vibrant cyan-white.
  - Added unit test suite in `tests/ui/test_prediction.py` (6 tests) and extended `tests/ui/test_donut_window.py` (2 new tests) validating debounce timing, cancellation, cache hits, and center card rendering.
  - VERIFY: Hovering shows prediction within ~0.27s (< 1s target); event loop processes smoothly without window freeze; 193 tests pass; ruff clean.

- Implement Donut engine execution on segment click and drop with worker thread, center states, and failure retry (smol/ui/worker.py, smol/ui/donut_window.py):
  - Created `ShrinkWorker(QThread)` running compression jobs off the UI thread emitting progress and results signals without blocking the Qt event loop.
  - Added file drag-and-drop (`setAcceptDrops(True)`) accepting `text/uri-list` file drops onto active segments so the daemon or user can drop files directly onto targets.
  - Implemented center card state transitions: `working` (displays "Working…" and progress status), `success` (displays "✓ Done" with before/after size or batch summary), and `failure` (displays honest engine message and a clickable "Retry (at smallest)" button).
  - Connected segment clicks and drop events to start background shrink jobs and re-run on failure retry at smallest achievable size.
  - Added unit test suite in `tests/ui/test_shrink_worker.py` (3 tests) and extended `tests/ui/test_donut_window.py` (5 tests).
  - VERIFY: Clicking segment and dropping file triggers worker thread without freezing UI; honest failure displays retry option and re-runs cleanly; 201 tests pass; ruff clean.

- Implement Custom size popup dialog and config persistence (smol/ui/custom_input.py, smol/core/config.py, smol/ui/donut_window.py):
  - Created `CustomInputDialog` floating liquid glass card near cursor with positive number input, KB/MB toggle, Enter confirm, and Esc cancel.
  - Implemented strict input validation rejecting zero, negative numbers, empty input, and non-numeric values with inline error messaging.
  - Created `smol.core.config` to manage user configuration in `~/.config/smol/config.toml` (or `$XDG_CONFIG_HOME/smol/config.toml`), storing up to the last 3 unique custom sizes in bytes via atomic writes.
  - Integrated custom sizes into `DonutWindow`: dynamically displays the remembered custom sizes as extra segments before "Custom…", and opens the popup near cursor when clicking or dropping files onto "Custom…".
  - Confirming custom input updates config, re-initializes donut geometry, and triggers the shrink worker thread.
  - Added unit test suites in `tests/core/test_config.py` (7 tests), `tests/ui/test_custom_input.py` (8 tests), and `tests/ui/test_donut_custom.py` (4 tests).
  - VERIFY: 220 tests passing in ~13s; `uv run ruff check .` clean.

- Support multiple files, mixed types, already-small files, and read-only output folders (smol/ui/donut_window.py, smol/core/image.py, smol/ui/custom_input.py):
  - Multiple files: centre card displays "{N} files" with aggregated file size; thumbnail gracefully selects the first valid image from the file list.
  - Mixed types: unsupported file formats (e.g. text files) are verified upfront, clearly flagged with an informative skip message, and skipped without failing the entire batch or preventing valid images from being shrunk.
  - Already-small files: files already <= target bytes are safely kept untouched without creating duplicate files, informing the user in the centre card and batch summaries.
  - Read-only output folders: detects non-writable target directories and permission errors upfront and during atomic write, returning an honest failure suggesting an alternative directory (e.g. `~/Downloads` or `~/Desktop`).
  - Signal safety: upgraded PySide6 target size signals to `Signal(object)` preventing 32-bit integer overflow and crash on large custom targets.
  - Added unit test suite in `tests/ui/test_donut_multi.py` (5 tests) and CLI test in `tests/test_cli_donut.py`. Isolated test config via pytest fixture.
  - VERIFY: `smol donut --files a.jpg b.png c.txt` handles all three types sensibly with no crash; 226 tests passing in ~16s; `uv run ruff check .` clean.

- Visual critique & liquid glass design overhaul across 5 donut states (v0.3.0):
  - Captured screenshots across 5 states (idle, hover, long filename, 800×600 compact screen, many segments dimmed) on both light and dark desktop wallpapers using `scripts/capture_donut_states.py`.
  - Critiqued honestly across readability, spacing, hit areas, and contrast on light/dark backgrounds.
  - Fixed top 5 issues in `smol/ui/donut_window.py`:
    1. Dimmed segment contrast on light wallpaper: eliminated inverse contrast/light bleed using a unified base glass disc (`rgba(16, 18, 27, 215)`), darker recessed segment tint (`rgba(10, 12, 18, 160)`), and crisp high-contrast slate labels (`rgba(160, 172, 195, 175)`) with soft dark drop shadows.
    2. Floating elevation & outer rim: added a 12px smooth radial ambient drop shadow elevating the donut off any wallpaper, plus a continuous specular rim highlight gradient and etched-glass separator lines.
    3. Center card vertical layout: balanced thumbnail, filename, and file size/prediction positions with symmetrical top/bottom margins, eliminating vertical crowding.
    4. Long filename typography: added adaptive font sizing (9pt DemiBold for >22 chars) and soft text drop shadows, preventing harsh truncation and ensuring clear legibility against complex desktop backgrounds.
    5. Compact display (800×600) adaptation & boundary clamping: added `adapt_compact_size()` scaling to 340×340 on screens <=720px height with 8px boundary margins, maintaining comfortable touch/click hit targets without dominating small screens.
  - Added regression test suite in `tests/ui/test_donut_window.py` covering compact scaling, screen clamping, and visual state rendering.
  - VERIFY: Screenshots show visible improvement across all 5 states on both light and dark wallpapers; all 229 tests pass; `uv run ruff check .` clean. Tagged `v0.3.0`.
- Implement hold-key and drag monitoring integration into daemon (Milestone M4: Path A X11 full Filee-like + Path C fallback):
  - Created `smol.daemon.listener` with `KeyHoldTracker` (tracking `Super`, `Ctrl+Alt`, `Right Alt`, `Right Ctrl`), `DragTracker` (detecting button1 drag initiation with distance threshold >= 6px), and `ListenerCoordinator` coordinating summoning, drop retention, and dismissal.
  - Implemented `X11EventListener(QThread)` with `python-xlib` querying `d.query_keymap()` and `root.query_pointer()` only while trigger key is held, achieving ~1% idle CPU.
  - Fail-safe ungrab guarantee (`ensure_ungrab`) releasing X11 keyboard and pointer grabs on SIGTERM, SIGINT, `atexit`, and in finally blocks so system input is never locked on crash.
  - Extended `DonutWindow` with `center_at(x, y)` with boundary clamping, `center_on_screen()` (for Path C), `reset_state()`, and `drop_received` / `dismissed` signals.
  - Integrated full Qt event loop into `DaemonService.run()` with clean signal handling and structured logging of every state transition to `~/.local/state/smol/daemon.log`.
  - Added test suites in `tests/daemon/test_listener.py` and `tests/daemon/test_daemon_summon.py` (14 new tests, 250 total).
  - Recorded `python-xlib` dependency and licensing (LGPL-2.1-or-later) in `NOTICE` and `pyproject.toml`.
  - VERIFY: `smol daemon start/status/stop` runs cleanly; idle CPU ~1%; `uv run pytest` (250 passed); `uv run ruff check .` clean.

- Core engine quality search verification & highest quality enforcement in `shrink_image`:
  - Verified binary search in `_lossy_quality_search_and_downscale` rigorously finds and returns the maximal quality <= target.
  - Added unit test `test_shrink_image_selects_highest_quality_in_range` proving `quality + 1` from the source image exceeds target.
  - Root cause documented for 524 KB PNG -> 147 KB incident: unquantized PNG was 517 KB (> 500 KB target), and 256-color palette quantization produced 147.85 KB because PNG has no lossy quality knob.

- Implement robust drag-drop handling, URI decoding, job queueing, and `smol daemon logs` (P5.3):
  - Created standalone `parse_drop_uris(mime_data)` supporting `text/uri-list`, QUrl arrays, `file://localhost/` syntax, percent-encoded Unicode and spaces, and multiple files from different folders.
  - Implemented job queueing in `DonutWindow` (`queue_or_start_shrink`, `job_queue` property, chained execution in `_on_shrink_finished`) allowing users to drop additional files while a job is currently working without losing drops or failing silently.
  - Added clean drag cancellation (`on_drag_cancelled`) and early trigger key release handling in `ListenerCoordinator` and `X11EventListener`, resetting `DragTracker` and dismissing the overlay.
  - Added `smol daemon logs [--lines N]` subcommand displaying running status, PID, log path, drop/job summary metrics, and formatted recent log history.
  - Added test suites in `tests/daemon/test_drop_robustness.py` and `tests/daemon/test_daemon_logs.py` (10 new tests, 262 total passed).
  - VERIFY: `smol daemon logs` displays activity summary and recent history; all 262 tests pass; `uv run ruff check .` clean.

- Add XDG autostart integration `smol integrate autostart install|uninstall|status`:
  - Created `AutostartIntegrator` (`smol/integrations/autostart.py`) managing `~/.config/autostart/smol.desktop` (honoring `$XDG_CONFIG_HOME`) to start `smol daemon start` at desktop login.
  - Reversible and idempotent install/uninstall operations with atomic file writes via temporary file replacement.
  - Wired `smol integrate autostart install|uninstall|status` into CLI (`smol/cli.py`) alongside existing file manager actions.
  - Added test suite in `tests/test_autostart.py` (7 tests covering file creation, status, idempotency, and CLI dispatch).
  - VERIFY: `smol integrate autostart install/status/uninstall` verified end-to-end; all 269 tests pass; `uv run ruff check .` clean.

- Benchmark and optimize daemon idle resources and donut latency (Milestone M4 performance verification & release v0.4.0):
  - Created reproducible performance measurement harness (`scripts/measure_performance.py`) measuring trigger-to-visible latency, cold-start time-to-first-pixel, warm summon latency, idle CPU %, and resident memory on active X11 display (`DISPLAY=:0`).
  - Pre-built `DonutWindow` hidden during daemon startup in `smol/daemon/service.py`, warming native X11 window surfaces, glyph caches, and painter pipelines before the first user trigger.
  - Reduced first-use time-to-first-pixel from 36.0 ms down to 20.65 ms (< 150 ms target).
  - Optimized `X11EventListener` in `smol/daemon/listener.py` with `idle_poll_interval=0.08` (80 ms) and keymap comparison (`km == last_km`) skipping keycode parsing when keyboard state is unchanged; tuned Qt heartbeat timer to 500 ms in `smol/daemon/service.py`.
  - Reduced daemon idle CPU from 2.2%–4.1% down to ~0% (`top`: 0.0%, direct /proc 5s sample: 0.60% of 1 core).
  - Reduced idle resident memory (RSS) from 118.2 MB down to 92.9 MB.
  - Measured warm summon-to-visible latency at 22.81 ms (Min 16.38 ms, Max 30.46 ms, target < 150 ms).
  - Synchronized package version to 0.4.0 across `pyproject.toml`, `smol/cli.py`, and `tests/test_basic.py`.
  - VERIFY: all 269 tests passing; `uv run ruff check .` clean; all performance targets verified and met; tagged `v0.4.0`.

- Implement open and hover animations and reduce_motion toggle (PLAN.md Section 6):
  - Open: segments fan out from centre with 120 ms `OutCubic` scale using `QPropertyAnimation` targeting 60 fps.
  - Hover: active hovered segment smoothly scales up 6% (`hover_scale = 1.06`), smoothly brightens, and label anchor tracks outward; transitioning/hovered segments render on top with outer rim edge hover support.
  - Prediction label: smoothly fades in with `prediction_opacity` (120 ms OutCubic) and cross-fades against original file size.
- Implement drop animations, real ring progress, and live size countdown (PLAN.md Section 6):
  - On drop: unchosen segments fade out (`other_segments_opacity` 1.0 -> 0.0 in 160 ms OutCubic); chosen segment pulses into a ring around the center thumbnail (240 ms OutQuad pulse, 200 ms transition).
  - Ring progress: tracks real core engine encode iterations for images (via `step_callback` in `_lossy_quality_search_and_downscale` and `shrink_image`) and stub progression for PDF/video files; draws active cyan progress arc sweeping clockwise from 12 o'clock around the thumbnail.
  - Live size countdown: center card dynamically updates with current candidate buffer bytes as steps arrive, counting down from original file size to final output size.
  - Fast-path bypass: if a job completes in under 300 ms (e.g. already small files or sub-threshold jobs), bypasses intermediate animation delays and skips straight to completed state (`✓ Done`) without fake progress.
  - Reduced motion support: when `reduce_motion=True`, animations resolve instantly (opacity = 0, scale/pulse = 0) with simple state transitions.
  - Test suite in `tests/ui/test_donut_drop_progress.py` (7 tests) and verification harness `scripts/verify_drop_progress.py`.
  - VERIFY: shrinking `tests/samples/portrait.jpg` (1.24 MB -> 99.5 KB) logs 10 real progress steps, smooth ring fill to 100%, and countdown from 1.24 MB down to 99,508 bytes over ~508 ms; all 288 tests pass; ruff clean.
- Implement completion sequence, soft checkmark burst (~600 ms), sliding toast, undo safety, and amber failure retry:
  - Ring snaps shut: sets ring progress to 100% upon compression completion.
  - Soft checkmark burst: plays ~600 ms OutCubic burst with expanding translucent emerald halo and scaling checkmark vector path (instant under `reduce_motion=True`).
  - Toast overlay (`ToastWindow` in `smol/ui/toast.py`): slides in near cursor/corner with dark sapphire liquid glass styling, formatted text (`photo.jpg  1.02 MB → 97 KB`), and action buttons: Open folder, Undo, Copy path.
  - Auto-hide & hover pause: 6-second auto-dismiss countdown pauses when mouse enters the toast and resumes when mouse leaves.
  - Hard safety invariant: Undo strictly deletes only the newly created output file, with defense-in-depth safety checks ensuring the original source file is never deleted or modified.
  - Failure state: renders amber progress ring around thumbnail, honest engine error explanation, and "Use smallest possible" button that triggers retry at the smallest achievable size.
  - Test suites in `tests/ui/test_toast.py` (8 tests) and `tests/ui/test_completion_sequence.py` (3 tests) plus verification script `scripts/verify_completion_toast.py`.
  - VERIFY: end-to-end verification confirms ring snap, 600 ms burst, toast display, 6s timer pause/resume on hover, copy path, undo output deletion with original file 100% intact, and failure amber ring with "Use smallest possible" retry; all 299 tests pass; ruff clean.
- Add `smol donut --demo` for 15-second screen recording demo (Milestone M5 release v0.5.0):
  - Added `--demo` flag to `smol donut` in `smol/cli.py` launching the interactive overlay over a sample photo without requiring `--files`.
  - Implemented `_get_demo_photo()` resolving `tests/samples/portrait.jpg` or creating a realistic ~1.2 MB portrait JPEG in `~/.cache/smol/` if executed outside development repository.
  - Added test suite in `tests/test_cli_donut.py` (7 tests) verifying `--demo` invocation, file resolution, and fallback generation.
  - Synchronized package and CLI versions to 0.5.0 across `pyproject.toml`, `smol/cli.py`, and `tests/test_basic.py`.
  - VERIFY: `smol --version` outputs `smol 0.5.0`; `smol donut --help` displays `--demo`; `smol donut` without args exits with code 2 and helpful usage; all 301 tests pass; `uv run ruff check .` clean. Tagged `v0.5.0`.
- Implement `smol/config.py` configuration manager with `tomllib` and `tomli-w`:
  - Added `tomli-w>=1.0.0` (MIT license) dependency for atomic TOML serialization.
  - Implemented `SmolConfig` dataclass and dictionary-like interface managing `~/.config/smol/config.toml` (honoring `$SMOL_CONFIG_PATH` and `$XDG_CONFIG_HOME`).
  - Supported schema validation across all required settings: `trigger_key`, `sizes`, `output_mode` (next to original | fixed folder), `output_folder`, `naming_pattern`, `keep_format`, `allow_convert`, `strip_metadata`, `min_side`, `reduce_motion`, `theme`, `autostart`.
  - Emits user warnings and cleanly falls back to safe defaults on corrupted files, partial files, or invalid field types without crashing.
  - Added unit test suite in `tests/test_config.py` (8 tests).
  - VERIFY: all 309 tests pass; `uv run ruff check .` clean.

- Implement `smol settings` PySide6 window and CLI subcommand (Milestone M6):
  - Created `SettingsWindow` in `smol/ui/settings_window.py` with dark sapphire liquid glass styling, responsive `QScrollArea`, and Esc key dismissal.
  - Trigger-key capture box: live key event recording with modifier combinations, preset shortcuts (`Super`, `Ctrl+Alt`, `Right Alt`, `Right Ctrl`), and warning badges for conflicts with file-manager shortcuts (e.g. `Ctrl` copy conflict, `Shift` move conflict, `Alt` window movement).
  - Target sizes list editor: add custom size dialog with `parse_size` validation, remove, and reorder (Up/Down) with live byte formatting.
  - Output rules: radio selection between original file directory and fixed destination folder with interactive folder picker (`QFileDialog`).
  - Options & behavior toggles: keep format, allow convert (lossy fallback), strip metadata && GPS tags, reduce motion (instant transitions), and start at login (synced with `AutostartIntegrator`).
  - Save button with validation, config persistence via `save_config`, autostart installation sync, and status feedback banner.
  - Wired `smol settings [--config PATH]` into CLI (`smol/cli.py`).
  - Captured screenshots with layout verification: verified radio button circular indicators and ampersand mnemonic escaping.
  - Added test suites in `tests/ui/test_settings_window.py` (7 tests) and `tests/test_cli_settings.py` (2 tests), bringing test suite to 318 passed tests.
  - VERIFY: Changed trigger key (`Ctrl+Alt`) and sizes (`[50 KB, 75 KB, 100 KB, 200 KB]`), saved, restarted daemon, verified new values took effect across daemon startup logs, DonutWindow segments, and CLI commands.

- Make engine, CLI, donut, daemon, and integrations read from smol/config.py (v0.6.0):
  - Centralized all configuration reading across engine, CLI, donut, daemon, and file-manager integrations to `smol/config.py`, eliminating duplicate hardcoded defaults.
  - Core engine (`smol/core/image.py` & `smol/core/paths.py`): reads fallback options (`min_dim`, `strip_metadata`, `keep_format`, `allow_convert`, `out_dir`, `naming_pattern`) directly from `smol.config.load_config()`.
  - CLI (`smol/cli.py`): strictly enforces `CLI flag > config file > default` precedence for `--min-side`, `--keep-metadata`, `--allow-convert`, and `--out-dir`.
  - Donut UI (`smol/ui/donut_window.py`): dynamically builds segments and motion settings from `smol.config`, removing hardcoded fallback lists, and supports runtime `reload_config()`.
  - Daemon (`smol/daemon/service.py` & `smol/daemon/listener.py`): monitors config modifications on disk via periodic timer, hot-reloads running DonutWindow segments and listener target key, logs clear notices on change, and reports `[restart needed: config modified]` in `smol daemon status`.
  - Integrations (`smol/integrations/manager.py`): dynamically generates context menu action files for Nemo, Nautilus, Dolphin, and Thunar from configured sizes.
  - Added test suites in `tests/test_config_precedence.py` (4 tests), `tests/test_config_subcommands.py` (3 tests), and `tests/daemon/test_daemon_config_reload.py` (2 tests), bringing test suite to 327 tests.
  - VERIFY: `scripts/verify_config_subcommands.py` verified setting changes propagate across `smol shrink`, `smol integrate`, and `smol daemon`. Tagged `v0.6.0`.

- Implement smol/core/pdf.py PDF compression engine (Milestone M7 / PLAN.md Section 7.2):
  - Created `shrink_pdf(src, target_bytes, options)` using a 6-rung Ghostscript ladder at decreasing DPI (200→150→120→96→72→60) and JPEG quality (~80→50) via PostScript `/ColorImageDict` and `/GrayImageDict` `/QFactor` distiller parameters.
  - Stops at the first (highest quality) rung whose output fits `<= target_bytes`.
  - Runs `qpdf --object-streams=generate` for object stream optimisation on intermediate outputs.
  - Validates syntactic integrity with `qpdf --check --warning-exit-0` before acceptance.
  - Safe subprocess execution with list arguments, never shell strings.
  - Atomic writes in the destination directory using temporary file replacement, with immediate cleanup of temp files on failure or error.
  - Honest failure reporting when impossible (smallest achievable size reported) and for incompressible text-only PDFs.
  - Bypass for already `<= target_bytes` files returning `ok=True` without writing duplicates or touching original.
  - Added sample generators `make_scanned_pdf` (~4.87 MB multi-page scanned PDF at 300 DPI) and `make_text_pdf` (vector text PDF).
  - Added test suite in `tests/core/test_pdf.py` (9 tests) and verification harness `scripts/verify_pdf_engine.py`.
  - VERIFY: ~4.87 MB scanned PDF goes to 415.33 KB (under 1 MB target) in 2 steps, and `qpdf --check` passes cleanly (exit code 0); text-only PDF fails honestly reporting smallest achievable size; all 336 tests pass; ruff clean.

- Route by file type in the engine: images → image engine, PDFs → pdf engine (Milestone M7 / release v0.7.0):
  - Created `smol.core.router` (`detect_file_type` and `shrink_file`) routing images to `shrink_image` and PDFs to `shrink_pdf`, and exposed in `smol.core`.
  - Wired `smol shrink` CLI to dispatch via `shrink_file` with clean human output formatting (`scanned_doc.pdf  4.87 MB → 415.33 KB  (q75)`) and `--json` support.
  - Wired Donut background worker (`ShrinkWorker`) to execute `shrink_file` and stream Ghostscript ladder rung numbers (`1/6, 2/6, ...`) as real step progress with live size countdown.
  - Wired hover predictions (`PredictionWorker` in `smol/ui/prediction.py`) to run dry-run predictions on PDFs.
  - Wired Donut overlay (`smol/ui/donut_window.py`) to recognize PDFs for hover prediction, accept dropped PDF files, and render first-page thumbnails via Ghostscript.
  - Wired file manager right-click context menus (`smol/integrations/manager.py`): added PDF extensions and MIME types to Nemo (`Extensions=...pdf;`), Dolphin (`application/pdf;`), and Thunar (`*.pdf;*.PDF;` and `<other-files />`).
  - Added test suites in `tests/core/test_routing.py` (7 tests), `tests/test_cli_shrink.py` (2 tests), `tests/ui/test_shrink_worker.py` (1 test), `tests/ui/test_prediction.py` (1 test), and `tests/test_integrate.py` (1 test).
  - Created end-to-end verification script `scripts/verify_pdf_routing_flow.py` proving PDF routing, thumbnail generation, ladder rung emissions (16.7% -> 33.3%), 4.87 MB -> 415.33 KB shrink under 500 KB target, clean `qpdf --check`, and Ghostscript rasterization.
  - Synchronized package and CLI versions to 0.7.0 across `pyproject.toml`, `smol/cli.py`, and `tests/test_basic.py`.
  - VERIFY: `scripts/verify_pdf_routing_flow.py` passes with all checks; `uv run smol shrink tests/samples/sample_scanned.pdf --max 1MB` produces 415.33 KB file in 2 steps; all 348 tests pass; `uv run ruff check .` clean. Tagged `v0.7.0`.

- Implement pure media math and ffprobe wrapper (`smol/core/media_math.py`):
  - Created pure functions for video bitrate calculation with 0.92 safety factor and audio deduction.
  - Implemented bits-per-pixel resolution ladder step-down (1080→720→480→360) ensuring even dimension pairs and aspect ratio preservation without upscaling.
  - Implemented audio-only bitrate calculation with 0.92 safety factor and 24 kbps floor enforcement, failing honestly when target is impossible.
  - Added secure `ffprobe` wrapper (`probe_media`) returning `MediaInfo` (duration, resolution, fps, stream presence) using list arguments.
  - Added unit test suite in `tests/core/test_media_math.py` (19 tests) covering standard clips, sub-second clips, huge targets, impossible targets, invalid inputs, resolution stepping, audio floor checks, and real ffprobe execution.
  - VERIFY: `uv run pytest -q tests/core/test_media_math.py` passes (19 passed in 0.36s); full test suite (367 passed); `uv run ruff check .` clean.

- Implement two-pass x264 video compression pipeline (`smol/core/video.py`):
  - Created `shrink_video(src, target_bytes, options)` using ffmpeg two-pass x264 with list arguments exclusively (never shell strings).
  - Isolated pass-log temporary files in dedicated temp directory (`smol_passlog_*`), guaranteed 100% cleaned up via finally block on success, failure, or cancellation.
  - Bitrate retry ladder: if pass 2 output overshoots target, cuts bitrate 5% and retries (up to 3 retries).
  - Resolution step-down integration via `decide_resolution` and bits-per-pixel ladder (1080→720→480→360).
  - Atomic destination writes via PID-tagged temp file in target directory, with non-overwriting collision resolution (`-1`, `-2`).
  - Honest failure reporting when target is impossible (bandwidth cannot accommodate duration/audio/video floors) or when retries are exhausted.
  - Exported `shrink_video` in `smol.core`.
  - Added unit and integration tests in `tests/core/test_video.py` (11 tests).
  - VERIFY: `scripts/verify_video_shrink.py` generated 30s 1080p synthetic clip (~19.3 MB) and shrank to 8 MB target, landing at 7.39 MB (7,391,367 bytes = 92.39% of target) at 1280x720, and complete decode playback check passed with 0 errors; full test suite (378 passed); ruff clean.
- Fix video engine pre-emptive early exit and normalize "already small enough" note (`smol/core/video.py`):
  - Normalized `target_bytes` (supporting int, float, and string representations via `parse_size`).
  - Added "already small enough" bypass when target >= original size returning original file with warning matching image engine semantics.
  - Removed pre-emptive bitrate/audio rejections; only reject early if total bandwidth is below minimum viable threshold (50 kbps total).
- Route video in engine and Donut UI (`smol/core/router.py`, `smol/ui/donut_window.py`):
  - Wired `shrink_file` in `smol/core/router.py` to dispatch video files (`.mp4`, `.mov`, `.mkv`, `.webm`, `.avi`) directly to `shrink_video`.
  - Added instant dry-run prediction support in `shrink_video` for Donut segment hover (`~{size}, {w}×{h}`).
  - Added fast 1-frame ffmpeg video thumbnail rendering in `smol/ui/donut_window.py` (`_load_thumbnail_pixmap`).
  - Added video extension awareness to `DonutWindow._first_image_path`.
- Implement audio compression engine matching codec family with bitrate calculation (Milestone M8 / PLAN.md Section 7.3):
  - Created `smol.core.audio` (`shrink_audio`) matching input family to appropriate audio encoder:
    * MP3 family (`.mp3`): `libmp3lame`
    * AAC / M4A family (`.m4a`, `.aac`): `aac`
    * Opus / OGG family (`.opus`, `.ogg`): `libopus` with `-vbr constrained`
    * Fallback for uncompressed/lossless (`.wav`, `.flac`): `libmp3lame`
  - Computes target bitrate from target bytes and duration with 0.92 safety factor via `compute_audio_bitrate`.
  - Enforces 24 kbps floor (`AUDIO_BITRATE_FLOOR` = 24,000 bps) returning honest failure stating smallest achievable size if target is impossible.
  - Implements bitrate overshoot retry ladder: cuts bitrate by 5% on overshoot (up to 3 retries).
  - Post-write size verification ensuring disk size strictly <= target bytes.
  - Non-destructive atomic destination write with collision resolution (`-1`, `-2`).
  - Fast bypass for files already <= target bytes returning `ok=True` without rewriting.
  - Instant dry-run prediction support (`options={"dry_run": True}`).
  - Exported `shrink_audio` in `smol.core` and wired into `smol.core.router` (`detect_file_type` and `shrink_file`).
  - Added unit test suite in `tests/core/test_audio.py` (10 tests) covering all codec families, 24 kbps floor enforcement, untouched original integrity, already-small bypass, dry-run, routing dispatch, retry on overshoot, and 3-minute tone playback check.
  - Created standalone verification script `scripts/verify_audio_shrink.py`.
  - VERIFY: a 3-minute generated tone (180s, ~4.32 MB) shrinks to 1 MB target, landing at 900.41 KB (90.04% of target), and passes complete decode/playback check with 0 errors; full test suite (391 passed in ~49s); `uv run ruff check .` clean.

- Parse ffmpeg `-progress pipe:1` output into progress events and size countdown (`smol/core/video.py`, `smol/core/audio.py`):
  - Streamed ffmpeg progress output via `subprocess.Popen(bufsize=1)` parsing `out_time_us` against media duration.
  - Emits normalized progress fractions across passes (video pass 1: 0.0–0.5, pass 2: 0.5–1.0; audio: 0.0–1.0) and live countdown bytes (`orig_bytes - diff * p`).
  - Added cooperative cancellation check and process registration via `cancel_check` and `on_process_started`.
- Clean cancellation and process cleanup (`smol/ui/worker.py`, `smol/ui/donut_window.py`):
  - Wired `Esc` key press in `DonutWindow` to cancel active compression worker.
  - In `ShrinkWorker`, tracking active `subprocess.Popen` with thread safety and killing the ffmpeg process (`SIGKILL`) immediately on `cancel()`.
  - Guaranteed removal of partial output files and pass-log directories on cancellation, leaving 0 leftover files and 0 orphaned processes.
- Wire video and audio into Donut UI, CLI, and file managers:
  - Removed legacy video stub in `ShrinkWorker`, enabling real background compression for all supported video and audio formats.
  - Added audio formats (`.mp3`, `.m4a`, `.aac`, `.opus`, `.ogg`, `.flac`, `.wav`) to `DonutWindow` first path prediction loader.
  - Updated right-click file manager integrations in `smol/integrations/manager.py` for Nemo, Dolphin, and Thunar to include all video and audio extensions and MIME types.
- Release v0.8.0:
  - Bumped project version to `0.8.0` in `pyproject.toml`, `smol/cli.py`, `tests/test_basic.py`, and `uv.lock`.
  - Added test suite coverage in `tests/core/test_video.py`, `tests/core/test_audio.py`, `tests/ui/test_shrink_worker.py`, `tests/ui/test_donut_window.py`, `tests/test_cli_shrink.py`, and `tests/test_integrate.py`.
  - Created automated verification script `scripts/verify_video_donut_flow.py`.
  - VERIFY: Shrinking video from donut shows moving progress (5 steps, 1.0% to 100.0%); Esc cancels cleanly with no partial file left behind; right-click configs include video/audio; full test suite passes (401 passed in ~55s); `uv run ruff check .` clean. Tagged `v0.8.0`.

- Clean up and defer video and audio compression to v1.1 (ship image + PDF for v1.0):
  - Removed `smol/core/video.py`, `smol/core/audio.py`, and `smol/core/media_math.py`.
  - Removed video/audio routing, video thumbnail extraction, and video/audio MIME types/extensions from engine (`smol.core.router`), Donut UI (`smol/ui/donut_window.py`), worker thread (`smol/ui/worker.py`), and file manager integrations (`smol/integrations/manager.py`).
  - Moved `ffmpeg` and `ffprobe` from required tools to optional/future tools section in `smol doctor` with install guidance for future v1.1.
  - Removed standalone video/audio unit test suites (`tests/core/test_video.py`, `tests/core/test_audio.py`, `tests/core/test_media_math.py`), CLI video/audio tests, and verification scripts.
  - Updated `PLAN.md` to mark M8 (video/audio) and M9 as deferred to v1.1.
  - Updated `README.md` to document supported formats in v1.0 as images (JPEG, PNG, WebP, HEIC, AVIF) and PDF only.
  - Re-routed active DonutWindow Esc cancellation test in `tests/ui/test_donut_window.py` to use images.
- Create smol/platform/ seam and Linux adapter with platformdirs (v1.0 Sequence Q0):
  - Created `smol.platform` seam with abstract interface (`Platform`, `KeyHoldAdapter`, `CursorPositionAdapter`, `IntegrationAdapter`, `AutostartAdapter`, `NotificationAdapter`) and `LinuxPlatform` adapter.
  - Added `platformdirs>=4.0.0` dependency (MIT license, documented in `NOTICE` and `pyproject.toml`) for standardized cross-platform resolution of `config_dir()`, `state_dir()`, and `cache_dir()`.
  - Implemented one-time non-destructive copy migration (`migrate_if_needed`) that copies legacy configuration/state files if target paths differ, never deleting old files, and logging migrations.
  - Replaced hard-coded `~/.config`, `~/.local/state`, and `~/.cache` paths across `smol.config`, `smol.daemon.service`, `smol.integrations.autostart`, `smol.integrations.manager`, and `smol.cli` to resolve through `smol.platform`.
  - Added comprehensive test suite in `tests/platform/test_platform.py` (13 tests) verifying default paths, XDG overrides, adapter stubs, migration safety, and mocked platform directory migrations.
  - VERIFY: All 361 tests pass; `uv run smol daemon status` and `uv run smol settings` work with existing user config; `grep -rn "\.config\|\.local/state" smol/` shows hard-coded paths only inside `smol/platform`.
- Implement smol/core/suggest.py size suggestion and floor estimation engine:
  - Created `suggest_sizes(original_bytes, floor_bytes, file_type, options)` with pure Python foundation (zero Qt dependencies, zero config imports).
  - Mode CLASSIC (default): returns fixed ladder in ascending order, never reshuffled; flags ineligibility when size >= original_bytes ("larger than the file") or size < floor_bytes ("too small for this file (min about X)"); strictly excludes pinned and recents.
  - Mode SMART (opt-in): filters candidate pool (pool + pinned + recents) to `floor * 1.05 <= size <= 0.9 * original`. If > max_segments (default 6) fit, selects max_segments spaced evenly on a log scale via dynamic programming, preferring anchors (100 KB, 200 KB, 500 KB, 1 MB, 2 MB) and larger values on ties. If < 3 candidates fit, generates relative rungs (0.75×, 0.5×, 0.25× rounded down to 1, 2, 2.5, or 5 × 10^k). Returns empty list ("Already small") if nothing fits.
  - Near-duplicate deduplication within 5% across both modes, keeping the larger size. Deterministic output across calls.
  - Created `estimate_floor(src, options)`: fast in-memory probe encode downscaled to min_dim at quality 60 for images (`source="predicted"`), and conservative heuristic for PDFs (`source="estimate"`).
  - Comprehensive unit test suite in `tests/core/test_suggest.py` (15 tests).
  - VERIFY: All 376 tests pass; ruff clean; verified 8-sample comparison table across 12 KB to 40 MB.

- Extend smol/config.py to schema version 1 and integrate with Donut UI and Settings window:
  - Schema v1: `config_version = 1`, `sizes.ladder` (max 7, default 20/50/100/200/500 KB/1 MB/2 MB), `sizes.pinned` (favourites, max 12), `sizes.recents` (LRU, max 5, 5% dedupe), `suggest.mode` ("classic" default | "smart"), `suggest.pool`, `suggest.max_segments` (default 6).
  - Migration: Preserves all existing values and unknown keys, adds defaults for new fields, and saves a one-time copy as `config.toml.bak` before migrating.
  - Donut UI: Uses `suggest_sizes` with max 8 segments including fixed last "Custom…". Classic mode dims ineligible entries with clear reasons. Non-blocking `FloorWorker` estimates floor in background without UI freeze. Hover predictions show `~96 KB` (or ineligibility reason if dimmed). Finished result and toast show check mark (`✓ {final_sz}`).
  - Custom popup: Upgraded `CustomInputDialog` listing favourites and recents with Up/Down arrow + Enter navigation, floor validation ("Smallest I can make this is about {floor}"), and LRU recents recording.
  - Settings window: Added Ladder editor (max 7), Favourites editor (max 12), and Donut Ring Mode switch ("Classic ring" vs "Smart ring") with full validation.
  - Result Provenance: Added `size_source` field (`"estimate"` | `"predicted"` | `"verified"`) in `Result` and exposed in `smol shrink --json`.
- Spike D: DragEnter / DragMove / Drop Data Inspection spike (`spikes/d_dragenter_data.py`):
  - Created interactive PySide6 always-on-top window (~320×320) awaiting real drag-and-drop operations from external applications.
  - Appends raw per-event log entries to `spikes/d_log.txt`: perf_counter timestamp, event type (ENTER, MOVE rate-limited to 100 ms, LEAVE, DROP), `source_is_none` (external app), action, MIME formats, `hasUrls()`, raw URLs (`toString()` and `toLocalFile()`), and URL read duration measured with `time.perf_counter()`.
  - Number keys 1 to 6 tag the next drag session; Esc closes the window and prints diagnostic summary table.
  - Added unit test suite in `tests/test_spike_d.py` (6 tests).
  - Empirical X11 findings verified on real drags across all 6 cases:
    * Case 1 (1 file from Nemo): URLs available at ENTER (5.26 ms cold, 0.45 ms warm) and MOVE (0.30–0.99 ms), NOT only at DROP.
    * Case 2 (12 files from Nemo): URLs available at ENTER (1.08 ms) and MOVE (0.33–1.10 ms), NOT only at DROP.
    * Case 3 (folder from Nemo): URLs available at ENTER (0.34 ms) and MOVE (0.29–0.84 ms), NOT only at DROP.
    * Case 4 (Archive Manager / File Roller): `hasUrls()` is False at ENTER, MOVE, and DROP! Formats are `XdndDirectSave0` and `XdndFileRoller0` without `text/uri-list`. Files dragged from archives require XDS protocol negotiation and cannot be read as URLs.
    * Case 5 (Mounted phone / MTP on GVFS): URLs available at ENTER (0.31 ms) and MOVE (0.31–2.20 ms) with valid `/run/user/1000/gvfs/mtp:...` path, NOT only at DROP.
    * Case 6 (Web browser / Chromium): URLs available at ENTER (0.36 ms) and MOVE (0.40–0.48 ms) as `data:image/jpeg;base64,...` (with `isLocalFile() == False`), NOT only at DROP.
  - Read latency for standard URL extractions is consistently <1.5 ms (<2.5 ms max on GVFS). All 398 tests pass; ruff clean.
- Implement pre-drop classification and Donut drag-enter states (A2 / A4.1):
  - Created `smol/core/classify.py` with `classify(path)` and `classify_files(paths)`:
    * Refuses non-regular files (FIFOs, sockets, character/block devices) using `os.lstat` before opening. Refuses broken symlinks and symlinks targeting non-regular files.
    * Sniffs header first (max 32 bytes) for JPEG, PNG, WebP, PDF, GIF, HEIF, TIFF, BMP, and ZIP/DOCX/ODT archives; falls back to extension second; trusts header on mismatch (e.g., PDF renamed to `.jpg`).
    * Identifies directories as `kind="folder"`, `reason="folder, not supported"`. Ignores non-`file://` remote URIs as `kind="remote"`.
    * Never decodes images during classification.
    * Caps batch inspection at 50 files; marks remainder as `+N more` (unknown).
  - Background classification worker (`ClassificationWorker` in `smol/ui/worker.py`):
    * Runs classification off the UI thread with cooperative cancellation (`sleep_stub` for testability).
  - Donut pre-drop drag-enter feedback (`DonutWindow` in `smol/ui/donut_window.py`):
    * Initiates background classification with a 300 ms timeout timer on `dragEnterEvent`.
    * Implements 4 distinct states:
      1. `all_supported`: Segments active; normal hover predictions.
      2. `none_supported`: Center card displays failure reason (e.g., "Unsupported file type (.docx)" or "folder, not supported"); all segments dimmed; mouse moves over segments display `ForbiddenCursor`; drops are ignored/rejected.
      3. `mixed`: Center card displays summary (e.g., "X of Y supported, Z will be skipped"); segments active; drop queues only supported files; completion toast displays skipped files by name (`Skipped: notes.docx`).
      4. `unknown`: Center card displays neutral "Checking..."; segments active; falls back to full classification at drop time.
    * Handles archive drops (e.g. Archive Manager / File Roller where URLs are not available at drag-enter) cleanly by entering neutral "Checking..." state and classifying at drop time when URLs arrive.
  - Comprehensive unit test suite in `tests/core/test_classify.py` (8 tests) and `tests/ui/test_donut_classify.py` (6 tests).
  - End-to-end verification script `scripts/verify_predrop_classify.py` covering all 5 core cases. All 411 tests pass; ruff clean.
- Implement Wayland session guard for hold-key daemon and doctor warning (v1.0 Sequence Q0):
  - Added session guard in `smol/daemon/service.py` (`check_wayland_session`) and `smol/cli.py` refusing `smol daemon start` and `smol daemon run` when `XDG_SESSION_TYPE=wayland` (even if `DISPLAY` is set under XWayland) with exit code 3 and message: "smol's hold-key donut needs an X11 session. Right-click integration and the smol CLI still work. Log out and choose an X11/Xorg session at the login screen, or use right-click."
  - Updated `smol doctor` to emit a warning row (`! XDG_SESSION_TYPE (wayland: hold-key donut needs X11; CLI and right-click work)`) on Wayland.
  - Preserved autostart entry, right-click integration, and CLI tools on all sessions.
  - Unit tests in `tests/daemon/test_wayland_guard.py` (5 tests) and updated `tests/test_doctor.py`.
  - VERIFY: With `XDG_SESSION_TYPE=wayland`, `uv run smol daemon start` prints message and exits with code 3; daemon starts and stops cleanly on real X11 session.
- Pre-audit freeze (v0.9.0 baseline):
  - Completed and verified full test suite (416 tests passing, 0 failures, 0 skipped, 0 xfailed).
  - Confirmed ruff linter clean with zero warnings.
  - Completed drift check against PLAN.md, AGENTS.md, and DECISIONS.md with zero contradictions, zero TODOs/FIXMEs, and zero weakened tests.
  - Synchronized package and CLI versions to 0.9.0 across `pyproject.toml`, `smol/cli.py`, `tests/test_basic.py`, and `uv.lock`.
  - Updated `PLAN.md` to reflect completion of sequence Q0 through A5 and Feature Freeze.
  - VERIFY: ruff clean, 416 tests green, `smol --version` reports 0.9.0, tagged `v0.9.0`.
- Security and robustness audit (P10.1):
  - Fixed subprocess invocation security: added `-dSAFER` to Ghostscript in `smol/core/pdf.py` and `smol/ui/donut_window.py`; guarded leading-dash filenames with resolved absolute paths and `--` separators; validated zero shell=True calls across codebase.
  - Fixed path traversal in `smol/core/paths.py`: added `sanitize_filename_component` stripping `/`, `\\`, `..`, leading dots, and control characters from dynamic naming pattern components.
  - Fixed HTML/rich-text injection: escaped filenames via `html.escape` in `smol/ui/toast.py` and neutralized newlines/control characters in `smol/ui/donut_window.py` and `smol/integrations/notifier.py`.
  - Fixed log spoofing and injection: added `sanitize_for_log` in `smol/daemon/service.py` stripping ANSI sequences, control characters, and newlines.
  - Hardened config validation in `smol/config.py`: blocked `NaN`, `Infinity`, negative numbers, and values >100 GB; restricted config/state directories to `0o700` and daemon logs to `0o600`.
  - Hardened temp file lifecycle: ensured unpredictable names via `tempfile.NamedTemporaryFile` with `try...finally` unlinking across `config.py`, `image.py`, `pdf.py`, `autostart.py`, and `manager.py`.
  - Hardened error handling for disk exhaustion: added clean recovery for `errno.ENOSPC` with honest failure results and zero dangling files.
  - Protected against FIFO TOCTOU hangs: added `os.O_NONBLOCK` when sniffing file headers in `smol/core/classify.py`.
  - Protected against decompression bombs: caught `Image.DecompressionBombError` in `smol/ui/donut_window.py` and `smol/core/suggest.py`, avoiding Qt pixmap abort crashes and falling back to safe heuristics.
  - Hardened desktop integrations: properly quoted binary paths with spaces and added backup copy protection for corrupted Thunar XML files.
  - Authored `SECURITY.md` (1-page threat model: what smol protects against, what it does not protect against, reporting policy).
  - P10.1b Close gaps in security pass:
    - Hostile filenames with real shrinking (1.2 MB -> 100 KB) on `-rf weird 'name".jpg`, newline in name, ANSI escape `\x1b[31m`. Verified sane output names, notifier receives `--` and sanitized text, toast is plain text, daemon log stays on 1 line, and CLI console output strips ANSI escapes/newlines while `--json` keeps raw path.
    - TOCTOU resistance: added `os.fstat(fd)` post-open in `smol/core/classify.py` verifying `stat.S_ISREG(st_f.st_mode)`.
    - Atomic temporary files created in target directory/filesystem with normal umask (`0o666 & ~umask`) applied before `os.replace`, with cleanup on exception or cancellation.
    - Sanitization of naming patterns: updated `sanitize_filename_component` to remove only whole `..` path components and separators, preserving intra-name dots (`holiday..photo.jpg`, `photo.final.jpg`).
    - Resource exhaustion caps: explicit `Image.MAX_IMAGE_PIXELS = 89_478_485` with `DecompressionBombWarning` treated as error; enforced PDF limits `MAX_PDF_SIZE_BYTES = 500_000_000` (500 MB) and `MAX_PDF_PAGES = 2_000`.
    - Collision & symlink safety: `output_path` checks `(candidate.exists() or candidate.is_symlink())` to prevent symlink and dangling symlink overwrites.
    - Audit checklist verified: zero `shell=True` / `os.system`; daemon single-instance locking; config/favourites caps; Wayland guard exit code 3; zero leftover media/ffmpeg in core; undo deletes only output files.
    - Updated `SECURITY.md` and added test coverage across all gap areas (443 total tests passing, 0 ruff errors).
- Clean `uv tool install .` installation, `install.sh`, and `uninstall.sh`:
  - Added package metadata to `pyproject.toml` (`readme`, `license`, `build/` to `.gitignore`).
  - Updated `smol doctor` in `smol/cli.py` to print exact dependency installation hints for Debian/Ubuntu/Mint (`sudo apt install ghostscript qpdf libxcb-cursor0`).
  - Added `install.sh`: checks external dependencies (`gs`, `qpdf`), installs tool via `uv tool install --force .`, runs `smol doctor`, interactively offers right-click file-manager integration and autostart (autostart enabled only on X11 sessions, gracefully skipped with notice on Wayland), and explains uninstallation.
  - Added `uninstall.sh`: stops running daemon, removes right-click integrations and autostart entry, uninstalls CLI tool, and preserves configuration in `~/.config/smol` unless `--purge` is passed (purges config, state, and cache).
  - Added test suite in `tests/test_install_scripts.py` (6 tests).
  - VERIFY: Clean virtual environment installation verified; `smol doctor` runs cleanly; `install.sh` and `uninstall.sh` verified with integration removal and config preservation/purge; full test suite passes (449 tests); `uv run ruff check .` clean.
- Create placeholder app icon set and XDG desktop entry (D-009):
  - Created `assets/icon/smol.svg`: simple flat two-colour placeholder icon (dark graphite `#262B36` and vibrant cyan `#00D2B4`) featuring a donut ring with a smooth inward pinch at the top segment, clearly legible down to 16 px. (Note: this is an interim placeholder icon; full branding design track is scheduled post-v1.0 per D-009).
  - Created `assets/icon/smol-tray.svg`: clean monochrome silhouette tray icon in white (`#FFFFFF`) with inward pinch contour for system tray panels.
  - Generated standard hicolor PNG icon hierarchy across 8 sizes (`16, 24, 32, 48, 64, 128, 256, 512`) into `assets/icon/hicolor/<size>x<size>/apps/smol.png` using `rsvg-convert`.
  - Created standard XDG application entry `packaging/smol.desktop` (`Name=smol`, `Exec=smol donut`, `Icon=smol`, `Categories=Utility;Graphics;`, `Comment=Shrink any file to at most a chosen size`, `StartupNotify=false`).
  - VERIFY: PNG files exist at all 8 sizes, SVG files validated with `identify` and `QSvgRenderer`, and `desktop-file-validate packaging/smol.desktop` reports 0 errors.
- Produce standalone single-file AppImage using PyInstaller (onedir) and appimagetool:
  - Added `pyinstaller>=6.10.0` dev dependency and authored `packaging/smol.spec` configured for onedir compilation targeting `smol.cli:main` entrypoint.
  - Built and preserved stable PyInstaller onedir payload at `dist/smol/` (`dist/smol/smol`, 198 MB uncompressed) for subsequent reuse by `.deb` packaging.
  - Assembled `AppDir` with `packaging/smol.desktop`, hicolor PNG icons (16–512 px) and SVG from `assets/icon/`, and hardened `AppRun` script supporting GUI launch (defaults to donut when stdout is not a tty) and CLI pass-through with standard system path fallbacks.
  - Packaged standalone AppImage via `appimagetool`: output `dist/smol-0.9.0-x86_64.AppImage`, final size 66 MB (68,700,664 bytes).
  - Confirmed external Ghostscript (`gs`) and `qpdf` are strictly unbundled: `smol doctor` runs cleanly via AppImage and guides user on missing system tools.
  - Tested in isolated environment without Python or virtualenv on PATH: `./smol-0.9.0-x86_64.AppImage --version` outputs `smol 0.9.0`, image/PDF shrinking operates correctly, and donut overlay initializes cleanly on X11.
  - Verified `--appimage-extract-and-run` fallback for systems without FUSE.
  - Documented `libfuse2` requirement on Ubuntu 22.04+ (`libfuse2t64` / `libfuse2`), `--appimage-extract-and-run` fallback, and external tool prerequisites in `README.md`.
  - Added automated verification test script `scripts/verify_appimage.sh`.
  - VERIFY: AppImage runs `--version` (`smol 0.9.0`), opens donut window, size reported honestly at 66 MB, zero bundled `gs`/`qpdf`; all 449 unit tests pass; `ruff check .` clean.

## Next
- Packaging (.deb package reusing dist/smol/), docs, CI, QA, v1.0 release.

## Decisions
- 2026-10-20 (D-003): v1.0 hold-key donut runs on X11 only (Path A, python-xlib). Right-click and the CLI work on any session.
- 2026-10-20 (D-005): Video and audio deferred to BACKLOG.md; ffmpeg no longer required for v1.0.
- 2026-10-20 (D-007): Classic fixed ring is the default. Smart ring is opt-in in Settings. Max 8 segments including Custom; favourites and recents in Custom popup.
- 2026-10-20 (D-008): Pre-audit sequence is Q0, A1 to A5, freeze, then P10.1 security audit. Everything else waits for post-v1.0.
- 2026-10-20 (D-010): Packaging for v1.0: AppImage and .deb from PyInstaller output, plus uv tool install. No Flatpak or Snap.
- 2026-10-20 (D-011): Windows 10/11 only as v2.0 after a spike (see BACKLOG.md); Windows 7, 8, 8.1 rejected.
- 2026-10-20 (D-012): Results state their source: estimate, predicted, or verified. Promise shown to users is "<= target".
- 2026-10-20 (D-013): Inspecting dragged files before drop: regular files only, header sniffing only (max 32 bytes), never decode, never open FIFOs or devices, cap 50 files, 300 ms timeout.
- 2026-10-20 (D-014): File-size expansion/padding and range targets deferred to v1.3+ and must be labelled in result (method).
- 2026-10-20: Defer video and audio compression to v1.1 to ship a rock-solid, focused v1.0 release covering images (JPEG, PNG, WebP, HEIC, AVIF) and PDF only. Keep ffmpeg/ffprobe detection in smol doctor as optional tools.
- 2026-10-20: In `smol/core/video.py` and `smol/core/audio.py`, stream ffmpeg execution via `-progress pipe:1 -nostats` in line-buffered `subprocess.Popen`, parsing `out_time_us` against media duration and emitting normalized ring progress fractions and live byte countdowns on `progress=` block completions.
- 2026-10-20: In `smol/ui/worker.py`, maintain thread-safe registration of active child subprocesses (`_active_proc`) and immediately issue `proc.kill()` on `cancel()`, handling exit code -9 / `CancellationError` to unlink partial output files and leave zero disk leftovers.
- 2026-10-20: In `smol/core/audio.py`, match input audio families (`.mp3` -> `libmp3lame`, `.m4a`/`.aac` -> `aac`, `.opus`/`.ogg` -> `libopus`). For `libopus`, specify `-vbr constrained` to ensure adherence to calculated target bitrates.
- 2026-10-20: In `smol/core/audio.py`, enforce strict 24 kbps floor via `compute_audio_bitrate` with 0.92 safety margin, failing honestly with smallest achievable size when target bandwidth is too low.
- 2026-10-19: In `smol/core/video.py`, isolate ffmpeg pass logs in a dedicated temporary directory (`smol_passlog_*`) deleted in a `finally` block, ensuring no dangling `ffmpeg2pass*` files on disk even during failures or exceptions.
- 2026-10-19: On video target overshoot, retry up to 3 times cutting video bitrate by 5% on each attempt before honest failure reporting.
- 2026-10-19: In `smol/core/media_math.py`, keep calculation functions pure (zero ffmpeg calls), using 0.92 safety factor, 64 kbps default audio allocation, 0.06 bits-per-pixel threshold for ladder step-down, and 24 kbps audio floor.
- 2026-10-18: Choose Path A (full Filee-like experience) for Linux X11/Cinnamon desktop based on M0 spike benchmarks (<4 ms overlay latency, XQueryPointer real-time coordinates, python-xlib key monitoring).
- 2026-10-18: Choose Super (Windows key) as default trigger key with Ctrl+Alt as secondary option; plain Ctrl rejected because Ctrl+drag triggers file copy in Linux file managers.
- 2026-10-18: Enforce post-write disk verification in core engine to guarantee no output file can ever be written or returned as successful above target_bytes.
- 2026-10-19: Standardize unified deep glass foundation disc (`rgba(16, 18, 27, 215)`) under frosted desktop snapshot to guarantee consistent text contrast and eliminate inverted brightness on light wallpapers.
- 2026-10-19: Pre-build DonutWindow hidden during daemon startup to eliminate cold-start widget initialization latency on first user summon.
- 2026-10-19: Adopt 80 ms idle keymap polling with fast-path unchanged keymap skip in X11EventListener, achieving ~0% idle CPU while keeping key response time under ~80 ms.
- 2026-10-19: Enforce strict configuration hierarchy: CLI flag > config file > default across all engine and CLI subcommands.
- 2026-10-19: In `smol/core/pdf.py`, use Ghostscript downsampling ladder (DPI 200→60, QFactor 0.40→1.00) + `qpdf --object-streams=generate`, stopping at first matching rung and validating syntax with `qpdf --check`.
- 2026-10-19: Implement unified file-type router in `smol/core/router.py` streaming Ghostscript ladder rung numbers as progress fractions into Donut progress rings.

## Known limits (v1.0)
- Formats supported: Images (JPEG, PNG, WebP, HEIC, AVIF) and PDF only. Video and audio deferred to v1.1.
- Input files already <= target size are untouched (reports no-op warning unless `--force` / `force_reencode` is enabled).
- Incompressible or sub-floor data: if minimum dimension floor (default 200 px) still exceeds target, engine honestly fails rather than producing unusable corrupted files or oversized files.
- PNG format kept by default (`--keep-format`): if 64-color palette quantization and downscaling cannot reach target, engine reports honest failure suggesting `--allow-convert`.
- Decompression bomb threshold: images exceeding 89.5 million pixels are safely rejected to protect system memory.
- PDF: Incompressible text-only vector PDFs or PDFs already below downsampling limits report honest failures stating smallest achievable size.

