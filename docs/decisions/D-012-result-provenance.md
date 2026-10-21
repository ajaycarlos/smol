# D-012: Result Provenance Reporting

- **Date**: 2026-10-20
- **Status**: Fixed
- **Canonical Reference**: [DECISIONS.md](../../DECISIONS.md#L18)

## Decision
All compression result objects and `--json` outputs explicitly record the provenance of their size metrics via a `method` / provenance field:
- `estimate`: Mathematical approximation (e.g. initial downscale heuristics).
- `predicted`: Real in-memory compression trial (e.g. hover preview).
- `verified`: Physically measured from disk after the file was written and closed.

## Why
Honest UI and API contracts prevent misleading users into believing a fast mathematical guess is a verified disk write. The primary user-facing promise remains guaranteed `<= target bytes`.
