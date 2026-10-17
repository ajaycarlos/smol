# PROMPTS.md — Let's build smol (prompt 0 → v1.0)

## How to use this file
1. Put these files in an empty folder named `smol`: `AGENTS.md`, `PLAN.md`, `PROGRESS.md`, `PROMPTS.md`. Open a terminal there and run `git init` once.
2. Do the prompts **in order**. One prompt = one fresh OpenCode session (`opencode` in the smol folder).
3. In every session: paste the **PREAMBLE** first, then the prompt's TASK block.
4. Model tags: **[U]** = your stronger model (Nemotron 3 Ultra) for hard or design-heavy steps; **[L]** = your faster model (Lightning) for well-specified steps. That split is my assumption, so swap if you find the reverse works better.
5. After the agent says it's done, **you run the VERIFY lines yourself.** Pass → next prompt. Fail → STUCK prompt (end of file).
6. 📎 = bring the result to Claude (this chat) before moving on.

Skills are loaded by the agent from the table in `AGENTS.md`. Each prompt below also names the key ones, because naming them is the most reliable way to make them load.

### PREAMBLE (paste at the top of every session)
```
Read AGENTS.md, PLAN.md and PROGRESS.md. Load every skill from the AGENTS.md skills table that fits this task,
and tell me which ones you loaded. Do ONLY the task below, nothing else.
First reply with: your 2-sentence understanding, the files you will create or change, and the tests you will write.
Then wait for my "go". After "go": work test-first, run everything, show real output, never weaken or delete a test.
When finished: run the VERIFY steps, then git commit with a clear message and update PROGRESS.md (Done / Next / Known issues).
```

### Install two more skills before the phases that need them
```bash
# before Phase 9 (video/audio)
npx skills add addyosmani/agent-skills -g -a opencode -y --skill performance-optimization
# before Phase 10 (release)
npx skills add addyosmani/agent-skills -g -a opencode -y --skill ci-cd-and-automation --skill documentation-and-adrs
```
Restart OpenCode after installing.

---

# PHASE 0 — Setup

### P0.1 — Bootstrap the repository · [L]
Skills: using-agent-skills, git-workflow-and-versioning, pytest
```
TASK: Create the project exactly as in AGENTS.md "Layout": Python 3.12 + uv, pyproject.toml with a console script
`smol` (entry point smol.cli:main), pytest and ruff configured, empty packages smol/core, smol/cli, smol/ui, smol/daemon,
smol/integrations, tests/ with one test that imports smol, a NOTICE file, a .gitignore (include tests/samples/ and .venv),
an MIT LICENSE, and keep the existing AGENTS.md/PLAN.md/PROGRESS.md/PROMPTS.md. `smol --version` must print a version.
Then make the first git commit. No features yet.
```
VERIFY: `uv run pytest -q` passes · `uv run ruff check .` is clean · `uv run smol --version` prints a version · `git log --oneline` shows a commit.

### P0.2 — `smol doctor` (environment check) · [L]
Skills: incremental-implementation, test-driven-development
```
TASK: Add `smol doctor`. It prints a checklist with ✓/✗ and an install hint for each: Python version, uv, ffmpeg, ffprobe,
ghostscript (gs), qpdf, git, session type ($XDG_SESSION_TYPE), desktop ($XDG_CURRENT_DESKTOP), a best guess of the default
file manager (Nautilus/Dolphin/Nemo/Thunar/other), and whether `notify-send` exists. Missing optional tools must not crash it.
Add tests with mocked environment variables and mocked `which`.
```
VERIFY: `uv run smol doctor` runs and prints a table. **Copy that output; you'll paste it into the spike prompts.** Also fill the "Environment" part of PROGRESS.md.

---

# PHASE 1 — Linux feasibility spike (Milestone 0)
The riskiest part of smol is whether Linux lets us (a) see a key being held, (b) notice a drag and the cursor position, and (c) show a window under the cursor that receives the dropped file. Do not skip this.

### P1.1 — Spike A: global key hold · [U]
Skills: spec-driven-development, source-driven-development, debugging-and-error-recovery
```
TASK: Spike only, no product code. Create spikes/a_key_hold.py.
My environment (from smol doctor): <PASTE smol doctor OUTPUT>.
Goal: detect globally (while ANOTHER app has focus) when I press and release these candidate trigger keys:
Ctrl+Alt (both held), Super, Right Alt, Right Ctrl, CapsLock.
First research the right method for my session type using Context7 and grep.app, and list the options with trade-offs
(X11: XInput2/Xlib; Wayland: xdg-desktop-portal GlobalShortcuts, or evdev). Pick one and explain why.
Print lines like `PRESS <key>` and `RELEASE <key> held=<ms>`, and end with a clear PASS or FAIL for each candidate key.
Tell me exactly how to test it (e.g. click into my file manager first, then hold the key). Tell me about any permission
it needs (like the `input` group) and do NOT change system settings without asking me.
```
VERIFY: you run it, test each key with another app focused, and report PASS/FAIL per key.

### P1.2 — Spike B: drag start and cursor position · [U]
Skills: source-driven-development, debugging-and-error-recovery
```
TASK: Spike only. Create spikes/b_drag_and_cursor.py. Goal: while a trigger key from Spike A is held, detect that I start
dragging a file in my file manager (mouse button down + movement) and read the global cursor position in screen coordinates
at that moment. Print `DRAG_START x=<..> y=<..>` and PASS/FAIL. Research what is possible on my session type first.
If something is impossible on my session (for example reading the cursor outside our own window on GNOME Wayland),
say so plainly with evidence, and print the best available fallback (e.g. screen center) instead of faking it.
```
VERIFY: you drag a file out of your file manager with the key held and report what it printed.

### P1.3 — Spike C: overlay that receives a drop · [U]
Skills: pyqt, qt-devtools-setup, source-driven-development
```
TASK: Spike only. Create spikes/c_overlay_drop.py using PySide6. Show a 300x300 translucent round window at the cursor
(or screen center if the cursor position is unknown), frameless, always on top, not stealing keyboard focus, accepting drops.
When I drop a file on it, print the file path(s) read from the text/uri-list mime data.
Test two variants and print PASS/FAIL for each:
 (1) the window is already visible BEFORE I start dragging;
 (2) the window appears DURING an active drag (show it from a timer 3 seconds after I start dragging, or when the trigger key is pressed).
Also report: does the window appear instantly, and does it block the file manager from starting the drag?
```
VERIFY: you run both variants with a real file from your file manager and report the output.

### P1.4 — Verdict · [U]
Skills: spec-driven-development, documentation-and-adrs (if installed), context-engineering
```
TASK: Write SPIKE.md from the three spikes' results (I will paste them: <PASTE RESULTS>). Include a table of what works on this
machine, and a verdict: Path A (full Filee-like experience), Path B (reduced), or Path C (centered drop palette: hold key,
donut appears at screen center, drag files onto it). Recommend one default trigger key and explain why (remember Ctrl+drag means
"copy" in most file managers). Update PLAN.md section 9 and Milestone M4 to the chosen path, and PROGRESS.md "Environment".
No product code.
```
VERIFY: SPIKE.md exists and names a path.
📎 **Bring SPIKE.md to Claude** before Phase 2. The path decides how Phase 5 is written; I'll adjust it if needed.

---

# PHASE 2 — Image engine and CLI (Milestone 1)
Core promise: output ≤ target, original untouched, honest failures.

### P2.1 — Sample files generator · [L]
Skills: test-driven-development, pytest
```
TASK: Add tests/make_samples.py and a pytest fixture that generate (into git-ignored tests/samples/) these images with Pillow:
portrait photo-like (gradient + noise, about 1.2 MB JPEG), landscape photo-like, screenshot-like PNG (flat colors and text),
tiny image, already-small JPEG (30 KB), huge image (about 40 megapixels, marked slow), grayscale JPEG, PNG with transparency,
CMYK JPEG, EXIF-rotated JPEG (orientation tag 6), HEIC sample (via pillow-heif), WebP photo, and a noise image that cannot
reasonably go below 5 KB. Add pillow and pillow-heif as dependencies and say why. Fixtures are generated on demand.
```
VERIFY: `uv run pytest -q` still passes and `ls tests/samples` shows about 12 files after a run.

### P2.2 — Size parsing, result object, output naming · [L]
Skills: incremental-implementation, test-driven-development
```
TASK: In smol/core: (1) parse_size("100KB"|"1.5MB"|"250000"|"100 kb") -> bytes using 1 KB = 1000 bytes, with clear errors;
(2) a Result dataclass with the fields listed in AGENTS.md "Engine promises" #6; (3) output_path(src, target_bytes) giving
`<name>_100KB.<ext>` next to the original with -1, -2 on collision, never overwriting anything. Unit tests including weird
filenames (spaces, unicode, leading dash, no extension, uppercase extension).
```
VERIFY: `uv run pytest -q tests/core` passes.

### P2.3 — JPEG quality search · [L]
Skills: incremental-implementation, test-driven-development
```
TASK: Implement smol/core/image.py: shrink_image(src, target_bytes, options) -> Result, JPEG only, following PLAN.md 7.1
steps 1 to 3: decode, apply EXIF rotation, strip metadata, convert to sRGB, binary-search quality between 60 and 95
(optimize on, 4:2:0, baseline), keep the highest quality that fits, verify by reopening, write atomically (temp file then rename).
If the file is already <= target, return ok with a "already small enough" note and copy nothing.
Tests on the portrait and landscape samples: result <= target and >= 90% of target for 100KB and 200KB targets; original unchanged.
No CLI yet. No downscaling yet (if it does not fit, return a clean failure for now).
```
VERIFY: `uv run pytest -q tests/core/test_image.py` passes.

### P2.4 — Downscale loop and honest failure · [U]
Skills: spec-driven-development, test-driven-development, debugging-and-error-recovery
```
TASK: Extend shrink_image with PLAN.md 7.1 step 4 and 5: if quality 60 at full size does not fit, estimate
scale = sqrt(target/size_at_floor) * 0.98, resize with Lanczos, search quality again between 60 and 90, repeat with 0.9 steps.
Respect the minimum short-side (default 200 px). If still too large, return ok=False with the smallest size achieved and a
human message like "Smallest I can make this is about 14 KB at 200 px; try a larger target". Add the 40-megapixel and the
"cannot go below 5 KB" samples to the tests. The result must record scale, quality, and number of encode attempts.
Keep total time for the 40 MP sample reasonable (explain what you did if it takes more than 10 seconds).
```
VERIFY: tests pass, including the 1 MB portrait → 100 KB case landing between 90,000 and 100,000 bytes.

### P2.5 — Metadata, color, alpha, orientation · [L]
Skills: test-driven-development, security-and-hardening
```
TASK: Handle: GPS/camera metadata stripped by default (option to keep), EXIF rotation baked into pixels, CMYK and grayscale
inputs, PNG with transparency flattened onto white when output is JPEG, ICC profile converted to sRGB. Add tests that
read the output with Pillow and assert: no GPS tags, correct orientation (width/height swapped for the rotated sample),
no alpha channel in JPEG output. Add a guard against decompression bombs (reasonable pixel limit with a clear error).
```
VERIFY: tests pass.

### P2.6 — PNG, WebP, HEIC · [U]
Skills: spec-driven-development, test-driven-development, source-driven-development
```
TASK: Add format handling per PLAN.md 7.1: WebP uses the same quality search; PNG has no quality knob so try palette
quantization 256 → 128 → 64 colors, then downscale; if still too big and options.allow_convert is true, produce a JPEG
instead and set a warning; if allow_convert is false, fail with a message suggesting it. HEIC/AVIF input produces JPEG.
Format is kept by default. Tests for each sample.
```
VERIFY: tests pass; PNG screenshot sample reaches 100 KB without changing format.

### P2.7 — The `smol shrink` command · [L]
Skills: incremental-implementation, test-driven-development
```
TASK: Add `smol shrink FILE... --max 100KB` with options --json (machine-readable results), --dry-run (predict size and
dimensions without writing), --out-dir, --allow-convert, --keep-metadata, --min-side. Several files at once. Friendly human
output (e.g. "photo.jpg 1.02 MB → 97 KB (600x800, quality 71)"), clear error messages, proper exit codes (0 ok, 1 some failed,
2 bad usage). Tests for argument parsing, --json shape, and the impossible-target message.
```
VERIFY: `uv run smol shrink tests/samples/portrait.jpg --max 100KB` and `--dry-run` and `--json` behave as described; `ls` shows the new file next to the original.

### P2.8 — Quality gate with your real photo · [U]
Skills: code-review-and-quality, security-and-hardening, verification-before-completion
```
TASK: Review the whole engine against AGENTS.md "Engine promises" and report problems by severity; fix anything that
breaks a promise. Add tests for any gap you find. Then give me a one-paragraph summary of known limits.
```
Do this yourself: put a real photo at `~/smol-private/passport.jpg` (outside the repo, never committed) and run
`uv run smol shrink ~/smol-private/passport.jpg --max 100KB`, then open both images and compare.
VERIFY: result ≤ 100 KB, faces look fine, original untouched. Then run `git tag v0.1.0-engine`.
📎 If the photo looks bad, describe it to Claude with the numbers (quality, scale) and we'll tune the strategy.

---

# PHASE 3 — Right-click integration (Milestone 2): first usable smol

### P3.1 — File-manager menu · [U]
Skills: spec-driven-development, source-driven-development, security-and-hardening
```
TASK: Add `smol integrate install|uninstall|status`. Implement ONLY for my file manager (from PROGRESS.md "Environment"),
with a submenu "Shrink to..." offering 20 KB, 50 KB, 100 KB, 200 KB, 500 KB, 1 MB, 2 MB. Use the correct mechanism for it:
Nautilus scripts in subfolders, a Nemo .nemo_action per size, a Dolphin service menu with a submenu, or Thunar custom actions.
Research the exact file locations and syntax first with Context7/grep.app. Installation must be reversible, must never
overwrite my existing entries, and must quote filenames safely (spaces, unicode, leading dash). For other file managers, print
manual instructions. `status` shows what is installed.
```
VERIFY: `uv run smol integrate install`, right-click a photo → Shrink to… 100 KB works. Then `uninstall` removes everything.

### P3.2 — Notifications · [L]
Skills: incremental-implementation, qt-devtools-desktop-integration
```
TASK: After a right-click job finishes, show a desktop notification via notify-send (fallback: print): success shows
"photo.jpg: 1.02 MB → 97 KB"; failure shows the honest message; batches show a summary. Add a short "working…" notification
for jobs that take longer than 1.5 s. Tests with a mocked notifier.
```
VERIFY: right-click shrink shows a notification with before/after sizes.

### P3.3 — Release gate · [L]
Skills: git-workflow-and-versioning, verification-before-completion
```
TASK: Run the full test suite and ruff, fix anything failing, write a short "Try it" section into README.md (install, right-click
install, `smol shrink` examples), update PROGRESS.md, and tag v0.2.0.
```
VERIFY: you use smol from the right-click menu on three real files. **You now have a usable tool.**

---

# PHASE 4 — The donut (Milestone 3)

### P4.1 — Donut geometry (pure math) · [L]
Skills: test-driven-development, incremental-implementation
```
TASK: In smol/ui/donut_geometry.py (NO Qt imports): given N segments, inner radius, outer radius and a gap angle, compute
each segment's start/end angle (first segment at the top, clockwise), a function segment_at(dx, dy) that returns the segment
index or None (center or outside), and label anchor points. Tests: boundaries, exactly on a gap, center, outside, N from 1 to 12.
```
VERIFY: `uv run pytest -q tests/ui` passes.

### P4.2 — Static donut window · [U]
Skills: pyqt, pyqt-styling, qt-devtools-setup, qt-devtools-app-interaction, frontend-design
```
TASK: Add `smol donut --files FILE...`: a frameless, translucent, always-on-top PySide6 window centered on the cursor, painted
with QPainter using donut_geometry. Segments: the size list from PLAN.md section 5, plus a "Custom..." segment. Centre shows the
file's thumbnail, name and current size. Segments larger than the file are dimmed and not clickable. Dark glass look, readable on
any wallpaper. Esc and clicking outside close it. For now clicking a segment prints the chosen size and exits (no engine yet).
Use the qt-devtools skills to screenshot the running window and show me the picture, then fix any visual issues you see.
```
VERIFY: `uv run smol donut --files tests/samples/portrait.jpg` shows the donut; you can hover and click; Esc closes.

### P4.3 — Hover prediction · [L]
Skills: pyqt, pyqt-threading, incremental-implementation
```
TASK: Hovering a segment highlights it and, after a 150 ms debounce, shows a prediction under the centre ("about 96 KB, 600x800")
computed with shrink_image(dry_run=True) in a worker thread (never on the UI thread). Cancel stale predictions when the
pointer moves on. Cache predictions per (file, size). Tests for the debounce/cache logic without a display.
```
VERIFY: hovering shows the prediction within about a second, and the window never freezes.

### P4.4 — Run the engine from the donut · [U]
Skills: pyqt-threading, test-driven-development, debugging-and-error-recovery
```
TASK: Clicking (or dropping onto) a segment runs the engine in a worker thread and emits progress and result signals.
Show a simple "working" state in the centre and a plain result message (animations come in Phase 6). The donut must also
ACCEPT file drops (text/uri-list) onto a segment so Phase 5 can reuse it. Handle failure with the honest message and an
option to retry at the smallest achievable size.
```
VERIFY: click 100 KB on the portrait sample: output file appears, UI never froze, the failure case shows the honest message.

### P4.5 — Custom size · [L]
Skills: pyqt, pyqt-dialogs (if installed), qt-devtools-form-and-input
```
TASK: The Custom segment opens a tiny input near the cursor: number plus KB/MB toggle, Enter to confirm, Esc to cancel, with
validation. Remember the last 3 custom values as extra segments.
```
VERIFY: type 75 KB → output ≤ 75,000 bytes; reopen the donut → 75 KB is a segment.

### P4.6 — Many files and edge states · [L]
Skills: test-driven-development, pyqt-threading
```
TASK: Support multiple files (each shrunk separately; centre shows "3 files"), mixed types (unsupported types show a clear
message and are skipped), already-small files, and read-only folders (suggest another output folder). A final summary line.
```
VERIFY: `smol donut --files a.jpg b.png c.txt` handles all three sensibly.

### P4.7 — UX review · [U]
Skills: frontend-design, qt-devtools-app-interaction, code-review-and-quality
```
TASK: Take screenshots of the donut in 5 states (idle, hover, long filename, tiny screen, many segments dimmed) and critique
the design honestly: readability, spacing, hit areas, contrast. Fix the top 5 issues.
```
📎 **Send Claude one screenshot of the donut**; I'll give design feedback before you invest in animation.
Then tag `v0.3.0`.

---

# PHASE 5 — Hold-key daemon (Milestone 4)
Implement the Path chosen in SPIKE.md. If SPIKE.md says Path C, "drag detection" becomes "hold key opens the centered donut palette".

### P5.1 — Daemon skeleton · [U]
Skills: spec-driven-development, security-and-hardening, debugging-and-error-recovery
```
TASK: Add `smol daemon start|stop|status|run`. Single instance (lock or socket), logs to ~/.local/state/smol/daemon.log with
rotation, clean shutdown on SIGTERM, and it reads config (trigger key, sizes) from ~/.config/smol/config.toml with defaults
if missing (use SPIKE.md's recommended key). No key handling yet. Tests for single-instance and shutdown behaviour.
```
VERIFY: `smol daemon start` twice → second says already running; `status` and `stop` work.

### P5.2 — Key hold plus drag → donut · [U]
Skills: source-driven-development, pyqt, debugging-and-error-recovery
```
TASK: Implement the chosen path from SPIKE.md: when the trigger key is held and (path A/B) a drag begins, show the donut at
the cursor position, or (path C) when the key is held show the donut at the screen center. Reuse the donut from Phase 4 and its
drop handling. Hide the donut on key release when nothing is dropped, or on Esc. Never leave the keyboard or mouse grabbed
if something crashes. Log every step so we can debug.
```
VERIFY: hold the key, drag a file out of your file manager, the donut appears, drop on 100 KB → file appears next to the original.

### P5.3 — Real drops end to end · [U]
Skills: debugging-and-error-recovery, test-driven-development
```
TASK: Make the full flow robust: multiple files dragged at once, files from different folders, file names with spaces and
unicode, dropping while the previous job is running, drag cancelled midway, key released early. Add a log summary command
`smol daemon logs`. Fix every issue found; add tests for the pure parts (URI decoding, queueing).
```
VERIFY: 10 consecutive real drags with no stuck overlay, no crash.

### P5.4 — Autostart · [L]
Skills: incremental-implementation, security-and-hardening
```
TASK: Add `smol integrate autostart install|uninstall` using an XDG autostart .desktop entry (or a systemd --user unit if
you can justify it for my desktop). Reversible, idempotent.
```
VERIFY: log out and in; `smol daemon status` says running.

### P5.5 — Performance gate · [U]
Skills: performance-optimization (if installed), verification-before-completion
```
TASK: Measure and report: time from trigger to donut visible (target < 150 ms), idle CPU of the daemon (target ~0%), idle memory,
and time-to-first-pixel on the first-ever use. Fix anything over target (for example prebuild the window hidden and just show it).
Show the measurements before and after.
```
VERIFY: numbers meet targets. Tag `v0.4.0`.
📎 **Tell Claude how the daemon behaves on your real desktop**; the Linux input details are the most fragile part.

---

# PHASE 6 — Animation and polish (Milestone 5)
Use QPropertyAnimation (non-blocking, parented to the window, custom Qt Property values for scale/progress). Honor "reduce motion".

### P6.1 — Open and hover motion · [U]
Skills: frontend-design, pyqt-styling, qt-devtools-app-interaction
```
TASK: Implement PLAN.md section 6 "Open" and "Hover": segments fan out with a 120 ms OutCubic scale from the centre; hovered
segment grows 6% and brightens; the prediction label fades in. Use QPropertyAnimation with custom Property values. Keep 60 fps.
Add a global animation switch that honors a `reduce_motion` setting (instant changes plus simple fades).
```
VERIFY: open and hover feel smooth; with reduce_motion on, no scaling.

### P6.2 — Working state: ring and countdown · [U]
Skills: pyqt, pyqt-threading, frontend-design
```
TASK: On drop: other segments fade, the chosen one pulses into a ring around the thumbnail. The ring fills with REAL progress
(engine steps for images; stub for now with a note for PDF/video). A size number counts down from original to final size as the
result arrives. Never fake long progress; if the job takes under 300 ms, skip straight to done.
```
VERIFY: shrinking the 40 MP sample shows a believable progress ring and countdown.

### P6.3 — Completion and toast · [U]
Skills: frontend-design, pyqt, code-review-and-quality
```
TASK: Completion: ring snaps shut, soft checkmark burst (about 600 ms), then a toast slides in near the cursor/corner:
"photo.jpg 1.02 MB → 97 KB" with buttons Open folder, Undo (deletes the output file safely, only the one we created),
Copy path. Failure state: amber ring and the honest message with "Use smallest possible" button. Toast auto-hides after 6 s
but stays while hovered.
```
VERIFY: success, failure and undo all work; Undo never deletes the original.

### P6.4 — Demo capture · [L]
```
TASK: Add `smol donut --demo` that runs the donut over a sample photo so I can screen-record a 15-second demo. Nothing else.
```
VERIFY: you record a short clip you're happy with. 📎 Send Claude a description or screenshot for feedback. Tag `v0.5.0`.

---

# PHASE 7 — Settings (Milestone 6)

### P7.1 — Config model · [L]
Skills: spec-driven-development, test-driven-development
```
TASK: Create smol/config.py: load/save ~/.config/smol/config.toml with defaults and validation. Fields: trigger_key, sizes,
output_mode (next to original or fixed folder), output_folder, naming_pattern, keep_format, allow_convert, strip_metadata,
min_side, reduce_motion, theme, autostart. Reading uses tomllib; for writing add tomli-w and say why. Bad values fall back to
defaults with a warning, never crash. Tests including a corrupted file.
```
VERIFY: tests pass; deleting the config file still works.

### P7.2 — Settings window · [U]
Skills: pyqt, qt-devtools-form-and-input, frontend-design, qt-devtools-app-interaction
```
TASK: `smol settings` opens a clean window: a "press the key you want" capture box for the trigger key (warn when it conflicts
with common file-manager shortcuts), a size list editor (add, remove, reorder), output rules, toggles, and a Save button that
validates. Screenshot it with the qt-devtools skills and fix any layout issues.
```
VERIFY: change the trigger key and sizes, save, restart the daemon, and the new values take effect.

### P7.3 — Wire config everywhere · [L]
Skills: incremental-implementation, test-driven-development
```
TASK: Make engine, CLI, donut, daemon and integrations read the config, with hot-reload for the daemon (or a clear
"restart needed" message). Remove hard-coded values. Tests for precedence: CLI flag > config file > default.
```
VERIFY: settings changes apply. Tag `v0.6.0`.

---

# PHASE 8 — PDF (Milestone 7)

### P8.1 — Ghostscript ladder · [U]
Skills: spec-driven-development, source-driven-development, security-and-hardening
```
TASK: Implement smol/core/pdf.py per PLAN.md 7.2: run Ghostscript (list args only, never a shell string) at decreasing image
DPI (200 → 150 → 120 → 96 → 72 → 60) with JPEG quality about 80 → 50, stop at the first rung whose output fits, then run qpdf
object-stream optimisation. Write atomically, verify the result opens (qpdf --check). Honest failure when impossible,
with the smallest size reached. Generate test PDFs with Pillow (scanned-like multi-page images) and one text-only PDF.
Time limit and temp-file cleanup on failure.
```
VERIFY: a ~5 MB scanned-like PDF goes under 1 MB; the text-only PDF fails honestly or stays as is.

### P8.2 — Wire PDF into everything · [L]
Skills: incremental-implementation, pyqt-threading
```
TASK: Route by file type in the engine: images → image engine, PDFs → pdf engine. Make `smol shrink`, the donut, the
right-click menu and the daemon all work with PDFs. Show PDF progress from the rung number. Tests for routing.
```
VERIFY: drag a real PDF onto the donut and shrink it; check it opens and reads clearly. Tag `v0.7.0`.

---

# PHASE 9 — Video and audio (Milestone 8)
(Install the performance-optimization skill first; see the top of this file.)

### P9.1 — Probe and bitrate math · [L]
Skills: test-driven-development, incremental-implementation
```
TASK: In smol/core/media_math.py (pure functions, no ffmpeg calls): given duration, target bytes, audio bitrate and a safety
factor 0.92, compute the video bitrate; decide the resolution step-down (1080 → 720 → 480 → 360) from bits-per-pixel; compute
audio-only bitrate with a 24 kbps floor. Add an ffprobe wrapper returning duration, resolution, fps, audio presence. Tests
with many edge cases (very short clip, huge target, impossible target).
```
VERIFY: tests pass.

### P9.2 — Two-pass video · [U]
Skills: source-driven-development, security-and-hardening, debugging-and-error-recovery
```
TASK: Implement video shrinking with two-pass x264 via ffmpeg (list args), using the math above. Verify the output size;
if over target, cut the bitrate 5% and retry (max 3). Clean up pass-log temp files always. Honest failure when impossible.
Generate test clips with ffmpeg's lavfi testsrc (no real footage in the repo).
```
VERIFY: a 30 s test clip lands at 90–100% of an 8 MB target and plays.

### P9.3 — Audio · [L]
Skills: incremental-implementation, test-driven-development
```
TASK: Implement audio shrinking: choose a codec that matches the input family (mp3/aac/opus), compute bitrate from the target,
honor the 24 kbps floor, verify size. Tests with generated tones.
```
VERIFY: a 3-minute test tone shrinks to the target and plays.

### P9.4 — Real progress for media · [U]
Skills: pyqt-threading, debugging-and-error-recovery
```
TASK: Parse ffmpeg `-progress pipe:1` output into progress events so the donut's ring and size countdown show real progress,
and support cancel (Esc kills ffmpeg and deletes partial output). Wire video/audio into CLI, donut, right-click and daemon.
```
VERIFY: shrinking a video from the donut shows moving progress; Esc cancels cleanly. Tag `v0.8.0`.

---

# PHASE 10 — Hardening, packaging, release (Milestone 9)
(Install ci-cd-and-automation and documentation-and-adrs first.)

### P10.1 — Security and robustness pass · [U]
Skills: security-and-hardening, code-review-and-quality, verification-before-completion
```
TASK: Audit the whole project: subprocess calls, filename handling, temp files and cleanup on failure/cancel, symlinks and
path tricks, decompression bombs, atomic writes, permissions on logs/config, what happens when disk is full or the output
folder is read-only, daemon crash recovery. Report findings by severity, fix them all with tests, and add a short SECURITY.md.
```
VERIFY: tests pass; you try dropping a file with a name like `-rf weird 'name".jpg` and it just works.

### P10.2 — Installable package · [U]
Skills: shipping-and-launch, git-workflow-and-versioning
```
TASK: Make `uv tool install .` (or pipx) install smol cleanly, and add install.sh that installs the tool, runs
`smol doctor`, offers to install right-click integration and autostart, and tells the user how to uninstall (`uninstall.sh`).
Test on a clean virtual environment. Do not bundle ffmpeg or Ghostscript; print clear instructions if missing.
```
VERIFY: on a clean user (or fresh venv) install works, `smol doctor` is happy.

### P10.3 — AppImage · [U]
Skills: shipping-and-launch, debugging-and-error-recovery
```
TASK: Produce a single-file AppImage (PyInstaller plus appimagetool, or the best-supported route for PySide6) with the .desktop
file and icon. State the final size honestly. If AppImage proves impractical, explain why and propose the alternative.
```
VERIFY: the AppImage runs `smol --version` and opens the donut on your machine.

### P10.4 — README, docs, demo GIF · [L]
Skills: documentation-and-adrs, frontend-design
```
TASK: Write a clear README.md: what smol is, a demo GIF placeholder, install steps, usage, the trigger key per desktop
(X11 / Wayland notes from SPIKE.md), settings, troubleshooting, supported formats and honest limits, how to uninstall.
Add docs/ARCHITECTURE.md (one page) and docs/decisions/ with short records of the major choices.
```
VERIFY: a friend can follow the README and succeed. Add your demo GIF from P6.4.

### P10.5 — CI · [L]
Skills: ci-cd-and-automation, pytest, pyqt-testing
```
TASK: Add GitHub Actions: ruff, pytest (Qt tests with QT_QPA_PLATFORM=offscreen; mark display-dependent tests so CI skips them),
on every push and pull request, Python 3.12. A second job builds the AppImage on tagged releases.
```
VERIFY: push to GitHub; the checks go green.

### P10.6 — Final QA · [U]
Skills: code-review-and-quality, verification-before-completion, constraint-driven-development
```
TASK: Run the full QA checklist against PLAN.md "Done when" for every milestone. For each: command, expected, actual.
List anything that doesn't pass. Check no test was weakened (compare git history for deleted or skipped tests). Fix the
blockers; list the rest as known issues in README.
```
VERIFY: the report is all green or honestly annotated.
📎 **Send Claude the QA report and a short screen recording description** for a final review.

### P10.7 — Release v1.0.0 · [L]
Skills: shipping-and-launch, git-workflow-and-versioning
```
TASK: Bump to 1.0.0, update CHANGELOG.md, tag v1.0.0, and prepare the GitHub release notes and the AppImage upload steps
(give me the exact commands or clicks; do not push anything without my approval).
```
VERIFY: release page live, install instructions tested from scratch. 🎉

---

# Reusable prompts

### STUCK (after 2 failed attempts)
```
Stop trying new fixes. Summarise: what we expected, what happened (full error), what you already tried, and your top three
hypotheses ranked. Load debugging-and-error-recovery. Propose ONE small experiment that tells the hypotheses apart.
```

### REVIEW (before committing any big change)
```
Load code-review-and-quality and security-and-hardening. Review the uncommitted changes (git diff) against AGENTS.md. List
problems by severity: broken engine promises, UI-thread blocking, unsafe filenames, tests that don't truly assert behavior,
anything outside the task's scope. Do not change anything yet.
```

### DRIFT CHECK (every 3–4 tasks)
```
Compare the code with PLAN.md. List contradictions, dead code, TODOs, skipped or weakened tests, and anything undocumented.
Report only; change nothing.
```

### CONTEXT RESET (session getting long or the model gets confused)
```
Write the current state into PROGRESS.md: what is done, what is half-done, exact next step, known issues, and any decision
we made in this session. Then stop. I will start a fresh session.
```

### CLAUDE HANDOFF (to get my help here)
```
Produce a short report for another engineer: goal of this task, what you changed (files), the exact commands I ran with
their real output, what's failing, and what you've tried. No guesses presented as facts.
```

---

## After v1.0 (ideas)
Preset bundles with pixel size plus KB (exam and government forms) · side-by-side before/after · watch folders · Windows and macOS ports ·
Office documents (recompress embedded images) · SSIM-guided quality choice · localisation.
