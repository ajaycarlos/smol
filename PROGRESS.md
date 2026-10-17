# PROGRESS.md

Agents: update this after EVERY task. Keep it short and current. New sessions rely on it.

## Current milestone
M0 (bootstrap complete). Next prompt in PROMPTS.md: P1.1

## Environment
- Distro / desktop / session type: Linux (externally managed)
- File manager: not yet determined
- Chosen path from SPIKE.md: not yet applied
- Default trigger key: not yet determined

## Done
- Bootstrap repository structure (P0.1): pyproject.toml, package init files,
  tests/gitignore/license, `smol --version` support
- VERIFY: `uv run pytest -q` passes, `uv run ruff check .` clean,
  `uv run smol --version` prints "smol 0.1.0"

## Next
- P1.1 — Spike A: global key hold (Milestone 0)

## Decisions
- (record product decisions here with the date)

## Known issues
- (none yet)
