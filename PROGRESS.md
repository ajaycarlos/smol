# PROGRESS.md

Agents: update this after EVERY task. Keep it short and current. New sessions rely on it.

## Current milestone
M0 (Spike A, Spike B, and Spike C complete).

## Environment
- Distro / desktop / session type: Linux / X-Cinnamon / x11
- File manager: nemo (installed)
- Python: 3.12.3
- Optional & required tools: uv, ffmpeg, ffprobe, gs (Ghostscript), qpdf, git, notify-send
- Chosen path from SPIKE.md: not yet applied
- Default trigger key: candidate keys evaluated in Spike A (Ctrl+Alt, Super, Right Alt, Right Ctrl)

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
- VERIFY: `uv run pytest` passes (40 passed), `uv run ruff check .` clean.

## Next
- Synthesize feasibility spike results in `SPIKE.md` (Path A: X11 full vs Path B: Wayland layer-shell vs Path C: palette fallback) to complete Milestone 0.

## Decisions
- (record product decisions here with the date)

## Known issues
- (none yet)
