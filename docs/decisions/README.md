# Architectural Decision Records (ADRs)

This directory contains short records of settled architectural and product decisions for **smol**.

The canonical, authoritative log of all decisions is maintained in [DECISIONS.md](../../DECISIONS.md). Agents and contributors must treat these decisions as fixed unless superseded by the project owner.

---

## Index of Settled Decisions

| ID | Title | Summary & Context | Status |
|---|---|---|---|
| [**D-001**](D-001-decimal-sizing-and-inviolable-target.md) | Decimal Sizing & Inviolable Target | 1 KB = 1,000 bytes; output disk size is strictly $\le$ target. | **Fixed** |
| [**D-002**](D-002-non-destructive-writes.md) | Non-Destructive Outputs | Original files are never modified; outputs use `<name>_<size>.<ext>` suffixes. | **Fixed** |
| [**D-003**](D-003-x11-hold-key-session-scope.md) | X11-Only Hold-Key Donut for v1.0 | Overlay requires X11 (`python-xlib`); right-click context menus & CLI work everywhere. | **Fixed** |
| [**D-004**](D-004-trigger-key-selection.md) | Trigger Key Choice: Super over Ctrl | `Super` is default; plain `Ctrl` avoided due to file manager "Copy File" collision. | **Fixed** |
| [**D-005**](D-005-scope-defer-video-and-audio.md) | Scope: Defer Video & Audio to v1.1 | v1.0 focuses strictly on image and PDF compression. | **Fixed** |
| [**D-006**](D-006-format-preservation-and-supported-types.md) | Format Preservation & Types | JPEG, PNG, WebP, HEIC (input), and PDF; keeps input format unless conversion requested. | **Fixed** |
| [**D-007**](D-007-classic-ring-default.md) | Classic Fixed Ring Default | 8-segment fixed ring is default to build muscle memory; smart ring is opt-in. | **Fixed** |
| [**D-008**](D-008-pre-audit-feature-freeze.md) | Pre-Audit Sequence & API Stability | Feature freeze before security audit ensures released config schemas are stable contracts. | **Fixed** |
| [**D-009**](D-009-design-track-timing.md) | Design Track Timing | Visual design iterations follow after v1.0; placeholder icon used for initial packaging. | **Fixed** |
| [**D-010**](D-010-packaging-appimage-and-deb.md) | Packaging: AppImage & .deb | Single PyInstaller binary packaged as AppImage and `.deb`; no Flatpak/Snap sandboxes. | **Fixed** |
| [**D-011**](D-011-windows-platform-scope.md) | Windows Platform Scope | Windows 10 & 11 targeted for v2.0; Windows 7/8/8.1 explicitly rejected. | **Fixed** |
| [**D-012**](D-012-result-provenance.md) | Result Provenance Reporting | Results report provenance (`estimate`, `predicted`, `verified`) for transparency. | **Fixed** |
| [**D-013**](D-013-pre-drop-file-inspection-safety.md) | Pre-Drop File Inspection Safety | Dragged file inspection limited to regular files, header sniffing ($\le 32$ B), never decodes. | **Fixed** |
| [**D-014**](D-014-padding-and-range-targets.md) | File Padding & Range Targets | Artificially inflating file sizes deferred to v1.3+; strictly adheres to $\le$ target. | **Fixed** |

---

For full historical rationale, see the root repository document: [DECISIONS.md](../../DECISIONS.md).
