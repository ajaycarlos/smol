# D-002: Non-Destructive Outputs

- **Date**: 2026-10
- **Status**: Fixed
- **Canonical Reference**: [DECISIONS.md](../../DECISIONS.md#L8)

## Decision
The original input file is strictly immutable and is never modified or overwritten. Shrunk outputs are saved adjacent to the input file using the naming pattern `<name>_<size>.<ext>` (e.g. `sample_100KB.jpg`). If a destination file already exists, numerical collision suffixes (`-1`, `-2`) are appended.

## Why
Users must never lose high-resolution original source photos or documents due to accidental compression mistakes. Undo actions safely delete only the newly generated compressed file.
