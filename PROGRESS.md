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
- VERIFY: `uv run pytest` passes (53 passed), `uv run ruff check .` clean.

## Next
- Milestone M1: Implement core image compression engine and `smol shrink` CLI with Pillow and pytest validation on 15+ samples.

## Decisions
- 2026-10-18: Choose Path A (full Filee-like experience) for Linux X11/Cinnamon desktop based on M0 spike benchmarks (<4 ms overlay latency, XQueryPointer real-time coordinates, python-xlib key monitoring).
- 2026-10-18: Choose Super (Windows key) as default trigger key with Ctrl+Alt as secondary option; plain Ctrl rejected because Ctrl+drag triggers file copy in Linux file managers.

## Known issues
- (none yet)
