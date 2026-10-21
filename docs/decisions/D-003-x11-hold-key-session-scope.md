# D-003: X11-Only Hold-Key Donut for v1.0

- **Date**: 2026-10
- **Status**: Fixed
- **Canonical Reference**: [DECISIONS.md](../../DECISIONS.md#L9)

## Decision
For v1.0, the hold-key summoning daemon and cursor drag-and-drop overlay run on **X11 desktop sessions only** (Path A, using `python-xlib` and `XQueryPointer`). File manager right-click context menu integration and CLI commands run on **any session** (X11 or Wayland).

## Why
Security architecture under Wayland intentionally restricts unprivileged background processes from listening to global keystrokes and querying global cursor coordinates across other applications. Attempting to support native Wayland overlays without unstable compositor-specific hacks would jeopardize stability. X11 provides full Filee-like performance (< 25 ms summon latency). A runtime Wayland guard alerts users gracefully.
