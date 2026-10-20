# DECISIONS.md — smol

Short records of choices that are settled. Agents: treat these as fixed unless the owner changes them. Add new entries at the bottom; never rewrite history, supersede instead.

| ID | Date | Decision | Why |
|---|---|---|---|
| D-001 | 2026-10 | 1 KB = 1000 bytes; output is always <= the target. | Safe for sites that use either definition. |
| D-002 | 2026-10 | The original file is never modified. Outputs go next to it with a size suffix. | Core promise. |
| D-003 | 2026-10 | v1.0 hold-key donut runs on **X11 only** (Path A, `python-xlib`). Right-click and the CLI work on any session. | M0 spike passed on X11 (Cinnamon, Nemo). Wayland restricts global key and cursor access. |
| D-004 | 2026-10 | Default trigger key is **Super**; Ctrl+Alt is the alternative. Plain Ctrl and plain Alt are rejected. | Ctrl+drag means "copy" in file managers; Alt+drag moves windows. |
| D-005 | 2026-10 | Video and audio are removed from v1.0. | Unreliable and a different UX (long jobs). Deferred in BACKLOG. |
| D-006 | 2026-10 | v1.0 formats: JPEG, PNG, WebP, HEIC (input), PDF. Output keeps the input format unless the user allows conversion. | Sites that say "JPG only" must get a JPG. |
| D-007 | 2026-10-20 | The **classic fixed ring is the default**. The smart ring is an opt-in Settings choice. Max 8 segments including Custom. | Stable positions build muscle memory. |
| D-008 | 2026-10-20 | Before the security audit (P10.1) we build only: platform seam, suggestion engine, ring and config schema v1, pre-drop classification, Wayland guard. Everything else waits for after v1.0. | New code after the audit would be unaudited; config shape is a public contract once released. |
| D-009 | 2026-10-20 | Design track (brand, mockups, motion) happens after v1.0, not in parallel. A placeholder icon is made for packaging. | Owner's call; keeps v1.0 focused. |
| D-010 | 2026-10-20 | Packaging for v1.0: AppImage and `.deb` from the same PyInstaller output, plus `uv tool install`. No Flatpak or Snap. | Sandboxes conflict with global key capture and file-manager integration. |
| D-011 | 2026-10-20 | Windows: 10 and 11 only, as v2.0 after a spike. Windows 7, 8, 8.1 are rejected. | Qt 6 supports Windows 10 1809+ and 11; older versions would need an unsupported legacy stack. |
| D-012 | 2026-10-20 | Results state their source: `estimate`, `predicted` (real in-memory encode) or `verified` (measured on the written file). The promise shown to users is "<= target". | Honest UI; stable `--json`. |
| D-013 | 2026-10-20 | Inspecting dragged files before the drop: regular files only, header sniffing only (max 32 bytes), never decode, never open FIFOs or devices, cap 50 files, 300 ms timeout. | Security and responsiveness. |
| D-014 | 2026-10-20 | File-size expansion/padding and range targets are later (v1.3+) and must be labelled in the result (`method`). | Changes engine promise #1; needs a spec edit. |
