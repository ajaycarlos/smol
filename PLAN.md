# PLAN.md — smol


## 1. What it is
A desktop tool that shrinks a file to **at most a size you choose**, without opening a browser.
Hold a key, drag a file, a donut of sizes opens at the cursor, drop on a size, done.

Core story: a 1 MB passport photo must go under 100 KB for a website upload form.

## 2. Honest scope
"Any file to any size" is impossible: already-compressed data has a floor. So:
- v1 = **images** (JPEG, PNG, WebP, HEIC) done really well, and **PDF**.
- Video and audio deferred, see `BACKLOG.md`.
- `ffmpeg` is no longer a required tool.
- When a target is impossible, say so and offer the smallest honest size. Never fake success.

## 3. Principles
1. Result is always <= target and as close to it as possible (best quality that fits).
2. Original is never touched.
3. Offline and private. No uploads, no accounts, no telemetry.
4. The engine works from the CLI alone. The donut is a front-end on top of it.
5. Fast: small images finish in under a second.

## 4. User flow
1. User holds the trigger key (customisable).
2. User drags one or more files in the file manager.
3. Donut opens centred on the cursor. Centre shows thumbnail, file name, current size.
4. Segments show target sizes. Segments larger than the file are dimmed and unusable.
5. Hovering a segment expands it and shows a prediction (e.g. "about 96 KB, 600x800").
6. Dropping starts the job. A progress ring fills in the centre.
7. Completion animation, then a toast: "1.02 MB -> 97 KB" with **Open folder**, **Undo** (deletes the output), **Copy path**.

Failure state: ring turns amber, message says what the smallest achievable size is and offers it.

## 5. Donut spec
- The donut default is the **classic fixed ring**; the smart ring is an opt-in setting.
- Maximum 8 segments including Custom.
- Favourites and recents live in the Custom popup.
- Default segments (all editable): 20 KB, 50 KB, 100 KB, 200 KB, 500 KB, 1 MB, 2 MB, **Custom...**
- Custom opens a tiny input at the cursor (number + KB/MB). Remember the last 3 custom values as segments.
- Optional presets that add pixel limits: e.g. "Photo <= 50 KB, 200x230". (v2)
- Multiple files: each file is shrunk to the chosen size separately. Toast summarises.
- Inner radius shows the file; outer ring shows sizes. Labels are readable on any wallpaper (dark glass panel, blur if available).

## 6. Animation spec
- Open: segments fan out with a 120 ms ease-out scale from the centre.
- Hover: segment grows 6%, brightens, prediction label fades in.
- Drop: other segments fade; chosen segment pulses into a ring around the thumbnail.
- Working: ring fills with real progress. Size number counts down from original to final.
- Done: ring snaps shut, soft checkmark burst, 600 ms. Then the toast slides in from the cursor corner.
- A "reduce motion" setting replaces all of this with simple fades.

## 7. Engine spec

### 7.1 Images (M1)
Pipeline:
1. Decode. Apply EXIF rotation. Strip metadata. Convert to sRGB. Flatten alpha onto white for JPEG output.
2. If file is already <= target: tell the user, do nothing (option to force re-encode).
3. **Quality search**: binary search quality between floor (60) and 95. Keep the highest quality that fits.
4. If quality floor at full size still does not fit: estimate scale = sqrt(target / size_at_floor) * 0.98, resize (Lanczos), search quality again in 60–90. Repeat with 0.9 steps if needed.
5. Stop at the minimum dimension. If still too big: fail honestly with the smallest size reached.
6. Verify by reopening the output. Verify size <= target.
Format rules:
- JPEG: optimised, 4:2:0 subsampling, baseline (max site compatibility).
- WebP: same search on quality.
- PNG: no quality knob. Try palette quantisation (256 -> 128 -> 64 colours), then downscale. If still too big and "allow format change" is on, offer JPEG.
- HEIC/AVIF input: output JPEG.
- Setting "keep format" is on by default. Sites that say "JPG only" must get a JPG.
Later: use SSIM to choose between "less quality" and "smaller dimensions" automatically.

### 7.2 PDF (M7)
Ghostscript ladder, stop at the first (best quality) rung that fits:
image DPI 200 -> 150 -> 120 -> 96 -> 72 -> 60, JPEG quality about 80 -> 50. Then `qpdf` object-stream optimisation.
Scanned PDFs shrink well. Text-only PDFs usually do not; report that honestly.

### 7.3 Video and audio (M8 / M9) (deferred, see BACKLOG.md)
Video and audio compression are deferred to post-v1.0 (see `BACKLOG.md`). `ffmpeg` is no longer a required tool for v1.0.

### 7.4 Later
Office docs (recompress images in `word/media`), ZIP re-pack, GIF, SVG minify.

## 8. Architecture
```
 [hold-key daemon] --summons--> [donut UI] --calls--> [core engine] --> output file
        ^                              |                    ^
   key + drag detection            toast / animation        |
                                                      [CLI: smol shrink f --max 100KB]
 [file-manager right-click scripts] -------------------------^
```
The CLI and right-click scripts reuse the same engine, so the product is useful before the donut exists.

## 9. Linux desktop reality (v1.0: X11-only for hold-key donut)
How a key hold, a drag in another app, and an overlay under the cursor work depends on the **display server**:
- **v1.0 ships Path A only (X11 hold-key + drag)**: Confirmed on X11 (Linux / Cinnamon / Nemo).
  - Global key hold detection via `python-xlib` (`Super` primary, `Ctrl+Alt` secondary; plain `Ctrl` avoided because `Ctrl`+drag triggers "Copy" in Linux file managers).
  - Global cursor tracking via `XQueryPointer` on root window.
  - PySide6 frameless translucent overlay summons under the cursor in 0.86–3.16 ms (< 150 ms target) without breaking the active file manager DnD grab (`WA_ShowWithoutActivating`).
- **Right-click and the CLI work on any session** (X11 or Wayland).
- **Paths B and C are future work** (Wayland layer-shell portals and centred drop-palette).

Milestone 0 is complete with full evidence documented in `SPIKE.md`.

## 10. Settings (M6)
Trigger key (capture box) · size list editor · output folder (next to original / fixed folder) · naming pattern · keep format · strip metadata · minimum dimension · reduce motion · theme · start at login · language.

## 11. Milestones

**M0 — Feasibility spike** (do first - COMPLETE)
- Write `spikes/a_key_hold.py`, `b_drag_and_cursor.py`, `c_overlay_drop.py`, and `SPIKE.md` with results.
- Done when: `SPIKE.md` states for this machine which of Path A (X11 full), B (Wayland + layer-shell), C (centred palette) is viable, with evidence.

**M1 — Image engine + CLI** (COMPLETE)
- `smol shrink photo.jpg --max 100KB` (also `--json`, `--dry-run`, `--keep-format/--allow-convert`).
- Done when: output is between 90,000 and 100,000 bytes for the standard test photo, original unchanged, `pytest` green on 15+ samples.

**M2 — Right-click integration + notifications** (COMPLETE)
- Submenu "Shrink to..." in the owner's file manager plus desktop notification.
- Done when: right-click a photo, choose 100 KB, new file appears, notification shows before/after size.

**M3 — Donut UI, standalone** (COMPLETE)
- `smol donut --files a.jpg b.jpg` opens the donut at the cursor, with hover, prediction, drop, custom size, Esc to cancel.
- Done when: matches section 4–5 for one and many files, engine runs off the UI thread.

**M4 — Hold-key daemon** (Path A: X11 full Filee-like - COMPLETE)
- Background service using `python-xlib` for global key hold detection and `XQueryPointer` for cursor tracking.
- Done when: hold key, drag a file out of the file manager, donut appears in under 150 ms, drop produces the shrunk file; idle CPU about 0%.

**M5 — Animation and polish** (COMPLETE)
- Section 6 in full, toast with Open folder / Undo / Copy path.

**M6 — Settings window** (COMPLETE)
- Section 10 in full.

**M7 — PDF engine** (COMPLETE)
- Section 7.2. Done when a 5 MB scanned PDF goes under 1 MB and still reads clearly.

**M8 — Video engine (deferred, see BACKLOG.md)**
`ffmpeg` is no longer a required tool.

**M9 — Audio engine (deferred, see BACKLOG.md)**
`ffmpeg` is no longer a required tool.

**M10 — Windows 10/11 = v2.0, see BACKLOG.md**

### v1.0 sequence
Before the v1.0 release, execute the following sequence:
1. **Q0** — Platform seam & Wayland guard (fail fast with helpful message on Wayland hold-key attempt - COMPLETE)
2. **A1** — Classic ring default (classic fixed ring default, max 8 segments including Custom, favourites & recents in Custom popup - COMPLETE)
3. **A2** — Drag inspection safety (regular files only, header sniffing max 32B, no FIFOs/devices, no decode - COMPLETE)
4. **A3** — Suggestion engine & config schema v1 (COMPLETE)
5. **A4** — Result provenance (`estimate`, `predicted`, `verified` - COMPLETE)
6. **A5** — Settings UI alignment (COMPLETE)
7. **Freeze** — Feature freeze for v1.0 (v0.9.0 pre-audit baseline tagged - COMPLETE)
8. **P10.1 security audit** — Comprehensive security and hardening audit
9. **Packaging (AppImage + .deb)** — AppImage and `.deb` packaging via PyInstaller, plus `uv tool install`
10. **Docs** — Documentation, man pages, user guide
11. **CI** — Continuous integration test & build pipeline
12. **QA** — Final manual QA checklist and regression test pass
13. **Release** — v1.0 release

## 12. Risks
| Risk | Mitigation |
|---|---|
| Wayland blocks cursor/drag access | v1.0 ships Path A only (X11-only); Wayland guard informs user; right-click path and CLI work on any session |
| Output looks bad at tiny targets | Quality floor, dimension floor, honest failure, before/after compare later |
| Ghostscript is AGPL | Call as external program, don't bundle |
| AI agents drift or break earlier work | Small tasks, tests, git commit per task, PROGRESS.md |
| Key conflicts with file manager shortcuts | Configurable key (Super / Ctrl+Alt), tested in M0 |
| Flatpak sandbox blocks global shortcuts | Ship AppImage/.deb first |

## 13. Later ideas
Presets with pixel size plus KB (exam and government forms) · side-by-side before/after · watch folder · convert format while shrinking · "shrink to fit this email limit" for multiple files together.
