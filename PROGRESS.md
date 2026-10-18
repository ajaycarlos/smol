# PROGRESS.md

Agents: update this after EVERY task. Keep it short and current. New sessions rely on it.

## Current milestone
M0 (Spike A complete). Next prompt in PROMPTS.md: P1.2

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
- VERIFY: `uv run pytest -q` passes (17 passed), `uv run ruff check .` clean,
  `spikes/a_key_hold.py` verified end-to-end.

## Next
- P1.2 — Spike B: mouse drag and cursor position detection (Milestone 0)

## Decisions
- (record product decisions here with the date)

## Known issues
- (none yet)
