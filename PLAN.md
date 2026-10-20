# PLAN.md — smol


## 1. What it is
A desktop tool that shrinks a file to **at most a size you choose**, without opening a browser.
Hold a key, drag a file, a donut of sizes opens at the cursor, drop on a size, done.

Core story: a 1 MB passport photo must go under 100 KB for a website upload form.

## 2. Honest scope
"Any file to any size" is impossible: already-compressed data has a floor. So:
- v1 = **images** (JPEG, PNG, WebP, HEIC) done really well, and **PDF**.
- Video and audio deferred to v1.1.
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

### 7.3 Video and audio (M8) (deferred to v1.1)
- Read duration with `ffprobe`.
- Total bits = target * 8 * 0.92 (safety margin). Audio 64 kbps. Video bitrate = remainder.
- If bits-per-pixel is too low, step the resolution down (1080 -> 720 -> 480 -> 360).
- Two-pass x264. Verify. If over target, cut bitrate 5% and retry (max 3).
- Audio only: bitrate from the same formula, floor 24 kbps, else fail.

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

## 9. Linux desktop reality (M0 spike verdict: Path A chosen)
How a key hold, a drag in another app, and an overlay under the cursor work depends on the **display server**:
- **X11 (Target Environment - VERIFIED)**: Everything is possible and tested on this machine (Linux / Cinnamon / Nemo). Spikes A, B, and C confirmed **Path A (full Filee-like experience)**:
  - Global key hold detection via `python-xlib` (`Super` primary, `Ctrl+Alt` secondary; plain `Ctrl` avoided because `Ctrl`+drag triggers "Copy" in Linux file managers).
  - Global cursor tracking via `XQueryPointer` on root window.
  - PySide6 frameless translucent overlay summons under the cursor in 0.86–3.16 ms (< 150 ms target) without breaking the active file manager DnD grab (`WA_ShowWithoutActivating`).
- **Wayland (KDE, Sway, Hyprland)**: Path B (layer-shell overlays and portals) remains a future option.
- **Wayland (GNOME)**: Path C (holding key opens a centred drop-palette donut) remains the architectural fallback where global cursor position is isolated.

Milestone 0 is complete with full evidence documented in `SPIKE.md`.

## 10. Settings (M6)
Trigger key (capture box) · size list editor · output folder (next to original / fixed folder) · naming pattern · keep format · strip metadata · minimum dimension · reduce motion · theme · start at login · language.

## 11. Milestones
Each milestone ends with a "Done when" check the owner can run.

**M0 — Feasibility spike** (do first)
- Write `spikes/a_key_hold.py`, `b_drag_and_cursor.py`, `c_overlay_drop.py`, and `SPIKE.md` with results.
- A: detect a key being held and released globally.
- B: detect a mouse drag in another app and read the cursor position.
- C: show a transparent frameless always-on-top window under the cursor during a drag and receive the dropped file path (`text/uri-list`).
- Done when: `SPIKE.md` states for this machine which of Path A (X11 full), B (Wayland + layer-shell), C (centred palette) is viable, with evidence.

**M1 — Image engine + CLI**
- `smol shrink photo.jpg --max 100KB` (also `--json`, `--dry-run`, `--keep-format/--allow-convert`).
- Done when: output is between 90,000 and 100,000 bytes for the standard test photo, original unchanged, `pytest` green on 15+ samples (portrait, landscape, screenshot PNG, HEIC, tiny, already-small, 40 MP, grayscale, alpha PNG, CMYK JPEG, EXIF-rotated, impossible target).

**M2 — Right-click integration + notifications** (first usable release)
- Submenu "Shrink to..." in the owner's file manager (Nautilus scripts / Nemo actions / Dolphin service menu / Thunar custom action) plus desktop notification.
- Done when: right-click a photo, choose 100 KB, new file appears, notification shows before/after size.

**M3 — Donut UI, standalone**
- `smol donut --files a.jpg b.jpg` opens the donut at the cursor, with hover, prediction, drop, custom size, Esc to cancel.
- Done when: matches section 4–5 for one and many files, engine runs off the UI thread.

**M4 — Hold-key daemon** (Path A: X11 full Filee-like)
- Background service (systemd user unit or autostart) using `python-xlib` for global key hold detection and `XQueryPointer` for cursor tracking.
- Trigger key: `Super` (primary default) or `Ctrl+Alt` (secondary), preventing file manager `Ctrl`+drag copy conflict.
- Hold trigger key + drag file out of Nemo/file manager summons PySide6 translucent donut under the cursor (`WA_ShowWithoutActivating`).
- Done when: hold key, drag a file out of the file manager, donut appears in under 150 ms (spikes verified ~1–3 ms), drop produces the shrunk file; idle CPU about 0%.

**M5 — Animation and polish**
- Section 6 in full, toast with Open folder / Undo / Copy path, sounds optional.
- Done when: owner records a 15-second screen capture they are happy to post.

**M6 — Settings window.** Section 10.

**M7 — PDF engine.** Section 7.2. Done when a 5 MB scanned PDF goes under 1 MB and still reads clearly.

**M8 — Video/audio engine (deferred to v1.1)**
Section 7.3. Done when a 30 s phone clip lands at 90–100% of an 8 MB target.

**M9 — Packaging and release (deferred to v1.1)**
- AppImage and/or `.deb`, README with a demo GIF, LICENSE (MIT), CI that runs tests, GitHub release.
- Do not bundle ffmpeg/Ghostscript (licensing); detect and guide.

**M10 — Windows/macOS ports** (only after Linux is solid; Qt UI and engine carry over, the key/drag hooks do not).

## 12. Risks
| Risk | Mitigation |
|---|---|
| Wayland blocks cursor/drag access | M0 spike first; fallback palette; right-click path always works |
| Output looks bad at tiny targets | Quality floor, dimension floor, honest failure, before/after compare later |
| Ghostscript is AGPL, ffmpeg varies | Call as external programs, don't bundle |
| AI agents drift or break earlier work | Small tasks, tests, git commit per task, PROGRESS.md |
| Key conflicts with file manager shortcuts | Configurable key, test candidates in M0 |
| Flatpak sandbox blocks global shortcuts | Ship AppImage/.deb first |

## 13. Later ideas
Presets with pixel size plus KB (exam and government forms) · side-by-side before/after · watch folder · convert format while shrinking · "shrink to fit this email limit" for multiple files together.
