# D-004: Trigger Key Selection: Super over Plain Ctrl

- **Date**: 2026-10
- **Status**: Fixed
- **Canonical Reference**: [DECISIONS.md](../../DECISIONS.md#L10)

## Decision
The primary default trigger key is **Super** (Windows/Command key), with `Ctrl+Alt` supported as a secondary preset. Plain `Ctrl` and plain `Alt` are rejected as trigger keys.

## Why
In all major Linux desktop file managers (Nemo, Nautilus, Dolphin, Thunar), dragging a file while holding `Ctrl` is the standard shortcut to "Copy / Duplicate File" rather than moving it. Plain `Alt` is universally reserved by Linux window managers for moving application windows across the desktop. `Super` provides a conflict-free modifier that file managers safely ignore during file drag gestures.
