# D-013: Pre-Drop File Inspection Safety

- **Date**: 2026-10-20
- **Status**: Fixed
- **Canonical Reference**: [DECISIONS.md](../../DECISIONS.md#L19)

## Decision
When the user drags files over the donut before dropping:
1. Only regular files (`stat.S_ISREG`) are inspected.
2. FIFOs, character/block devices, and sockets are never opened.
3. Only header sniffing is performed (reading at most the first 32 bytes to identify magic bytes).
4. Full file decoding is strictly prohibited during drag hover.
5. Inspection is capped at 50 files and has a 300 ms hard timeout.

## Why
Security hardening and UI responsiveness: Opening named pipes or special devices can block the process indefinitely, freezing the desktop. Decoding arbitrary large files on drag would cause stutter and potential memory exhaustion.
