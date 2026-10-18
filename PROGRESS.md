# PROGRESS.md

Agents: update this after EVERY task. Keep it short and current. New sessions rely on it.

## Current milestone
M0 (bootstrap complete). Next prompt in PROMPTS.md: P1.1

## Environment
- Distro / desktop / session type: Linux / X-Cinnamon / x11
- File manager: nemo (installed)
- Python: 3.12.3
- Optional & required tools: uv, ffmpeg, ffprobe, gs (Ghostscript), qpdf, git, notify-send
- Chosen path from SPIKE.md: not yet applied
- Default trigger key: not yet determined

## Done
- Bootstrap repository structure (P0.1): pyproject.toml, package init files,
  tests/gitignore/license, `smol --version` support
- Add `smol doctor` subcommand (P0.2): checklist table with ✓/✗ and install hints
  for Python 3.12+, external tools, desktop environment, and file manager detection.
  Unit tests covering present, missing, and mock conditions.
- VERIFY: `uv run pytest -q` passes (9 passed), `uv run ruff check .` clean,
  `uv run smol doctor` runs cleanly and detects environment.

## Next
- P1.1 — Spike A: global key hold (Milestone 0)

## Decisions
- (record product decisions here with the date)

## Known issues
- (none yet)
