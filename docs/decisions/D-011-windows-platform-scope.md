# D-011: Windows Platform Scope

- **Date**: 2026-10-20
- **Status**: Fixed
- **Canonical Reference**: [DECISIONS.md](../../DECISIONS.md#L17)

## Decision
Windows support is planned for **v2.0** and is strictly limited to **Windows 10 (Build 1809+) and Windows 11**. Legacy Windows versions (Windows 7, 8, 8.1) are rejected.

## Why
PySide6 (Qt 6) dropped official support for Windows 7, 8, and 8.1. Supporting legacy Windows versions would require compiling against outdated, insecure toolchains. Windows 10/11 native drag-drop APIs will be evaluated in a v2.0 feasibility spike.
