# BACKLOG.md — smol feature intake

Three different things, never mixed:
- **Idea**: someone had a thought. Not a promise.
- **Approved**: the owner said yes and assigned a version. This is the real scope.
- **Implemented**: built, tested, and verified by the owner running the VERIFY step.

Agents: do NOT build anything from this file unless a prompt names the item and its status is Approved.

## Status flow
Idea → Triaged → Approved (vX.Y) → In progress → Implemented (verified) · or → Rejected (reason) · or → Later

## Buckets
| Bucket | Meaning |
|---|---|
| v1.0 blocker | Breaks a core promise, risks data loss or security, or blocks installation. Nothing else qualifies. |
| v1.x | Valuable and bounded. Gets a target version. |
| Later | Depends on a platform, design or spec decision not yet made. |
| Reject | Contradicts a principle (offline and private, honest results, original never touched) or the cost is not worth it. |

## Scoring (0 = bad, 2 = good; write one line of reasoning per criterion)
User value · Feasibility · Platform fit (Linux/X11 now, Windows later) · Security impact (2 = none added) · Complexity (2 = small) · Dependencies and release impact (2 = none).
Total 10–12: schedule it. 6–9: Later or needs a spike. 0–5: reject or rethink.

## Limits (to keep v1.0 shippable)
- One feature in progress at a time.
- At most three Approved items per minor release.
- Anything that adds a new file parser or reads user files in a new way needs its own security check.

## Intake template
```
ID: IDEA-0xx
Idea:
Who needs it and why:
Scores: value _ · feasibility _ · platform _ · security _ · complexity _ · deps _
Bucket / target version:
Contradicts the plan? (which section):
Status:
```

## Current items (2026-10-20)
| ID | Idea | Status | Target | Notes |
|---|---|---|---|---|
| IDEA-001 | Smart size suggestions (opt-in ring) | Approved | v1.0 | **Classic fixed ring stays the default.** Smart is a Settings option. |
| IDEA-002 | Segment cap (8), favourites and recents in the Custom popup | Approved | v1.0 | Keeps the donut tidy. |
| IDEA-003 | "Unsupported file type" shown before the drop; mixed batches | Approved | v1.0 | Header sniffing only, regular files only. Spike A4.1 first. |
| IDEA-004 | Platform seam (paths and adapter interfaces) | Approved | v1.0 | Internal. No Windows code yet. |
| IDEA-005 | Result fields `size_source` (estimate/predicted/verified) | Approved | v1.0 | Stable `--json` shape. |
| IDEA-006 | Wayland guard (clear message, no silent failure) | Approved | v1.0 | v1.0 hold-key donut is X11 only. |
| IDEA-007 | `.deb` plus AppImage packaging | Approved | v1.0 | Same PyInstaller output feeds both. |
| IDEA-008 | Placeholder icon | Approved | v1.0 | Needed for packaging; real branding later. |
| IDEA-009 | Video and audio shrinking | Deferred | v1.x | Removed from v1.0 (unreliable). Revisit later. |
| IDEA-010 | TIFF, BMP, static GIF, AVIF | Triaged | v1.1 | Pillow plus `pillow-avif-plugin`. Output stays a format upload forms accept. |
| IDEA-011 | Animated GIF | Later | v1.3+ | Until then: refuse with a clear message. Never flatten silently. |
| IDEA-012 | DOCX, PPTX, XLSX (and ODF, EPUB) by recompressing embedded images | Triaged | v1.2 | Needs its own security pass (zip-slip, decompression bombs). |
| IDEA-013 | Range targets (min to max) and padding/expansion | Later | v1.3+ | Changes engine promise #1; needs a spec edit and honest labelling (`method`). |
| IDEA-014 | Design track: brand, mockups, motion spec | Triaged | v1.1 | Owner decided: after v1.0, not in parallel. |
| IDEA-015 | Windows 10 and 11 | Triaged | v2.0 | Spike first. Open question: PDF engine without bundled Ghostscript. |
| IDEA-016 | Windows 7, 8, 8.1 | Rejected | n/a | Needs Python 3.8 and Qt 5: unsupported, insecure stack. |
| IDEA-017 | Wayland hold-key path | Later | n/a | GNOME restricts global cursor and key access. Needs a spike. |
| IDEA-018 | Flatpak, Snap | Later | n/a | Sandbox conflicts with global key capture and file-manager integration. |
| IDEA-019 | RPM, AUR | Later | n/a | Low effort once demand exists. |
| IDEA-020 | RAW, SVG, JPEG XL, generic ZIP | Rejected | n/a | Not what upload forms ask for. |
| IDEA-021 | Self-hosted APT repository | Later | n/a | Ongoing maintenance burden. |
| IDEA-022 | Pixel-size presets (e.g. "photo 50 KB, 200x230") | Idea | n/a | From the original plan. |
| IDEA-023 | Before/after compare view | Idea | n/a | |
| IDEA-024 | Watch folder | Idea | n/a | |
