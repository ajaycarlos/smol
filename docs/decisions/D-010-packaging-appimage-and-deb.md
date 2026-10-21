# D-010: Packaging for v1.0: AppImage and .deb

- **Date**: 2026-10-20
- **Status**: Fixed
- **Canonical Reference**: [DECISIONS.md](../../DECISIONS.md#L16)

## Decision
Linux packaging for v1.0 produces two artifacts generated from a unified PyInstaller bundle:
1. Standalone **AppImage** (x86_64).
2. Native **.deb** package for Debian / Ubuntu / Linux Mint.
In addition, `uv tool install .` is officially supported. Sandboxed formats (Flatpak, Snap) are rejected for v1.0.

## Why
Flatpak and Snap sandbox boundaries prevent background daemons from capturing global keystrokes and pointer coordinates on the root display, and block native file manager action integration scripts in user directories.
