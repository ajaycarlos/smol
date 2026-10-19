# PROGRESS.md

Agents: update this after EVERY task. Keep it short and current. New sessions rely on it.

## Current milestone
M4 — Hold-key daemon service & summoning integration (In progress).

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
  - Added `reduce_motion` config toggle in `~/.config/smol/config.toml` (`get_reduce_motion`, `set_reduce_motion` in `smol/core/config.py`): disables all scaling (segments stay 1.0 scale) and provides instant changes and simple fades only.
  - Added test suite in `tests/ui/test_donut_animation.py` (10 tests) and verification harness `scripts/verify_animations.py`.
  - VERIFY: open scale fans out 0.0 -> 1.0 in 120 ms OutCubic; hover reaches 1.06 (+6.0%); prediction opacity fades 0.0 -> 1.0; with reduce_motion on, no scaling occurs (scale remains 1.0); all 281 tests pass; ruff clean.

## Current milestone
M5 — Animation and polish (In progress: open, hover, and prediction animations completed).

## Next
- Drop segment pulse into ring around thumbnail, other segments fading.
- Working ring progress and countdown.
- Done checkmark burst (600 ms) and toast with Open folder / Undo / Copy path.

## Decisions
- 2026-10-18: Choose Path A (full Filee-like experience) for Linux X11/Cinnamon desktop based on M0 spike benchmarks (<4 ms overlay latency, XQueryPointer real-time coordinates, python-xlib key monitoring).
- 2026-10-18: Choose Super (Windows key) as default trigger key with Ctrl+Alt as secondary option; plain Ctrl rejected because Ctrl+drag triggers file copy in Linux file managers.
- 2026-10-18: Enforce post-write disk verification in core engine to guarantee no output file can ever be written or returned as successful above target_bytes.
- 2026-10-19: Standardize unified deep glass foundation disc (`rgba(16, 18, 27, 215)`) under frosted desktop snapshot to guarantee consistent text contrast and eliminate inverted brightness on light wallpapers.
- 2026-10-19: Pre-build DonutWindow hidden during daemon startup to eliminate cold-start widget initialization latency on first user summon.
- 2026-10-19: Adopt 80 ms idle keymap polling with fast-path unchanged keymap skip in X11EventListener, achieving ~0% idle CPU while keeping key response time under ~80 ms.

## Known limits (v0.4.0)
- Input files already <= target size are untouched (reports no-op warning unless `--force` / `force_reencode` is enabled).
- Incompressible or sub-floor data: if minimum dimension floor (default 200 px) still exceeds target, engine honestly fails rather than producing unusable sub-floor thumbnails or oversized files.
- PNG format kept by default (`--keep-format`): if 64-color palette quantization and downscaling cannot reach target, engine reports honest failure suggesting `--allow-convert`.
- Decompression bomb threshold: images exceeding 89.5 million pixels are safely rejected to protect system memory.
