# AG-PROMPTS-FINAL.md — before the audit through v1.0.0

One block = one new Antigravity conversation. Copy the whole block (rules are included), paste, read the plan reply, answer `go`, then run VERIFY yourself in a terminal. 📎 means: bring the result to Claude first.

**Before you start:** put `BACKLOG.md` and `DECISIONS.md` (new) into the smol folder next to the other .md files, and commit them.

**Effort:** 🟡 Medium · 🔴 High

| # | Prompt | Effort | Why now |
|---|---|---|---|
| 1 | Q0 Sync docs | 🟡 | Make the plan files match the approved decisions |
| 2 | A1 Platform seam | 🟡 | Paths become an OS-independent contract |
| 3 | A2 Suggestion engine | 🔴 | Pure logic, both ring modes |
| 4 | A3 Ring, config v1, Custom popup | 🔴 📎 | Config shape freezes at release |
| 5 | A4.1 Drag-data spike | 🟡 📎 | Learn what Nemo gives us before the drop |
| 6 | A4.2 Classification and Unsupported state | 🔴 | New file-reading code, audited next |
| 7 | A5 Wayland guard | 🟡 | No silent failures on Wayland |
| 8 | FREEZE | 🟡 | Clean baseline for the audit |
| 9 | P10.1 Security pass | 🔴 📎 | Audits everything above |
| 10 | P10.2 Install scripts | 🟡 | |
| 11 | ICON Placeholder icon | 🟡 | Needed by both packages |
| 12 | P10.3 AppImage | 🔴 | |
| 13 | P10.3b .deb | 🔴 | Reuses the AppImage build output |
| 14 | P10.4 README | 🟡 | States the X11 requirement |
| 15 | P10.5 CI | 🟡 | |
| 16 | P10.6 Final QA | 🔴 📎 | |
| 17 | P10.7 Release | 🟡 | |

Rescue prompts (STUCK, DRIFT CHECK, CONTEXT RESET) are at the end of this file.

---

## Q0 — Sync the docs with the approved decisions 🟡

```
Read AGENTS.md, PLAN.md, DECISIONS.md and PROGRESS.md only. Do NOT read PROMPTS.md, AG-PROMPTS.md, AG-PROMPTS-FINAL.md or BACKLOG.md.

Rules for this session:
- Do ONLY the task below. Nothing else.
- Never say "this should work." Show real output for every check.
- When done: run VERIFY, git commit, update PROGRESS.md.
- First reply: your plan (files to touch, what you will check). Then STOP and wait for my "go".

TASK: Sync the project docs with the approved decisions. DECISIONS.md and BACKLOG.md are new and already in the folder: read DECISIONS.md, do NOT rewrite either file. Do not change any code.
Update PLAN.md:
(1) Mark M8/M9 (video, audio) as "deferred, see BACKLOG.md"; ffmpeg is no longer a required tool.
(2) Section 9: v1.0 ships Path A only (X11 hold-key + drag). Right-click and the CLI work on any session. Paths B and C are future work.
(3) Section 5: the donut default is the classic fixed ring; the smart ring is an opt-in setting; maximum 8 segments including Custom; favourites and recents live in the Custom popup.
(4) Replace M10 with "Windows 10/11 = v2.0, see BACKLOG.md".
(5) Add the v1.0 sequence: Q0, A1 to A5, freeze, P10.1 security audit, packaging (AppImage + .deb), docs, CI, QA, release.
Update AGENTS.md: file locations come from smol/platform (platformdirs), never hard-coded; add the rule "when inspecting dragged files: regular files only, never open FIFOs or devices, never decode".
Update PROGRESS.md: Done / Next / Decisions.

VERIFY: `git diff --stat` shows only .md files changed; `uv run pytest -q` still passes; PLAN.md mentions classic ring, X11-only and the new sequence.
```


---

## A1 — Platform seam 🟡

```
Read AGENTS.md, PLAN.md, DECISIONS.md and PROGRESS.md only. Do NOT read PROMPTS.md, AG-PROMPTS.md, AG-PROMPTS-FINAL.md or BACKLOG.md.

Rules for this session:
- Do ONLY the task below. Nothing else.
- Work test-first: write the test first (expect fail), write the code, run again (expect pass).
- Never weaken, skip or delete a test. If a test is wrong, say why and ask me.
- Never say "this should work." Run it and show me the real output.
- When done: run VERIFY, git commit with a clear message, update PROGRESS.md.
- First reply: 2-sentence understanding, files you will create or change, tests you will write. Then STOP and wait for my "go".

TASK: Create smol/platform/ with a small interface module and a Linux adapter. Use the platformdirs library (add it and say why) for config_dir(), state_dir() and cache_dir(). Add adapter stubs (interfaces only, Linux implementation keeps today's behaviour) for: key_hold, cursor_position, integration, autostart, notifications.
Move every hard-coded ~/.config and ~/.local/state path to the seam. If the new path differs from the old one, migrate once (copy, never delete the old file) and log it.
No Windows code. No behaviour changes.
Tests with mocked platform directories, including the one-time migration.

VERIFY: All tests pass; `uv run smol daemon status` and `uv run smol settings` still work and use the same config as before; `grep -rn "\.config\|\.local/state" smol/` shows hard-coded paths only inside smol/platform.
```


---

## A2 — Size-suggestion engine (pure logic) 🔴

```
Read AGENTS.md, PLAN.md, DECISIONS.md and PROGRESS.md only. Do NOT read PROMPTS.md, AG-PROMPTS.md, AG-PROMPTS-FINAL.md or BACKLOG.md.

Rules for this session:
- Do ONLY the task below. Nothing else.
- Work test-first: write the test first (expect fail), write the code, run again (expect pass).
- Never weaken, skip or delete a test. If a test is wrong, say why and ask me.
- Never say "this should work." Run it and show me the real output.
- When done: run VERIFY, git commit with a clear message, update PROGRESS.md.
- First reply: 2-sentence understanding, files you will create or change, tests you will write. Then STOP and wait for my "go".

TASK: Add smol/core/suggest.py (pure Python, no Qt, no config import).
API: suggest_sizes(original_bytes, floor_bytes, file_type, options) -> list[SizeSuggestion]
options is a plain dataclass SuggestOptions(mode, ladder, pool, pinned, recents, max_segments). Config wiring comes in A3.
SizeSuggestion fields: bytes, label (e.g. "100 KB"), kind (ladder|relative|pinned|recent), eligible (bool), reason (str or None).
Two modes:
CLASSIC (the default): return options.ladder (default 20/50/100/200/500 KB/1 MB/2 MB, 1 KB = 1000 bytes) in ascending order, never reshuffled. eligible=False with reason "larger than the file" when size >= original_bytes; eligible=False with reason "too small for this file (min about X)" when size < floor_bytes. Pinned and recents are NOT part of the ring in this mode.
SMART (opt-in): pool = options.pool (default 20/50/100/200/500 KB/1/2/5 MB). Eligible when floor*1.05 <= size <= 0.9*original. If more than max_segments (default 6) are eligible, keep max_segments spaced roughly evenly on a log scale; prefer the anchors 100 KB, 200 KB, 500 KB, 1 MB, 2 MB on ties; other ties go to the larger value. If fewer than 3 are eligible, add original*0.75, *0.5, *0.25, each rounded DOWN to a nice number (1, 2, 2.5 or 5 times a power of ten) when >= floor*1.05 and not within 5% of an existing entry. Pinned and recents join the pool under the same eligibility rules. If nothing is eligible return an empty list (the caller shows an "Already small" state).
Both modes: dedupe entries within 5% (keep the larger). Deterministic: the same inputs always give the same output.
Also add estimate_floor(src, options) -> FloorEstimate(bytes, source) for images: one fast probe encode (downscale to the minimum side, quality 60), source="predicted". For PDFs return a conservative heuristic with source="estimate".
Tests: 12 KB, 30 KB, 1.2 MB and 40 MB inputs in both modes; floor above every ladder entry; pinned/recent merging; near-duplicates; classic never reshuffles; determinism (run twice, compare).

VERIFY: pytest passes. Ask the agent to print a table of both modes for 8 sample sizes and show it to you; it should match the rules above (for example 1.2 MB in smart mode gives about 50, 100, 200, 500 KB and 1 MB; 12 KB gives no ladder entries).
```


---

## A3 — Donut ring, config schema v1, Custom popup 🔴

```
Read AGENTS.md, PLAN.md, DECISIONS.md and PROGRESS.md only. Do NOT read PROMPTS.md, AG-PROMPTS.md, AG-PROMPTS-FINAL.md or BACKLOG.md.

Rules for this session:
- Do ONLY the task below. Nothing else.
- Work test-first: write the test first (expect fail), write the code, run again (expect pass).
- Never weaken, skip or delete a test. If a test is wrong, say why and ask me.
- Never say "this should work." Run it and show me the real output.
- When done: run VERIFY, git commit with a clear message, update PROGRESS.md.
- First reply: 2-sentence understanding, files you will create or change, tests you will write. Then STOP and wait for my "go".

TASK: Extend smol/config.py to schema version 1:
config_version = 1; sizes.ladder (default 20/50/100/200/500 KB/1 MB/2 MB, max 7 entries); sizes.pinned (favourites, max 12); sizes.recents (max 5, most recent first, LRU); suggest.mode ("classic" default | "smart"); suggest.pool; suggest.max_segments (default 6).
Migration: keep every existing value, add new fields with defaults, preserve unknown keys, and save a one-time copy of the old file as config.toml.bak before migrating.
Donut: build a SuggestOptions from config and use suggest_sizes. Maximum 8 segments including "Custom..." (always fixed, last). Classic mode looks exactly like today, except ineligible entries are dimmed with their reason. Run estimate_floor in a worker when the donut opens and update the dimming when it finishes (no UI freeze).
Custom popup: lists favourites (sizes.pinned) and recents; arrow keys + Enter to pick, or type a value. Validate typed values against the floor and show: "Smallest I can make this is about 14 KB". Record a used custom size into sizes.recents (dedupe within 5%, drop the oldest beyond 5).
Settings window: ladder editor (max 7), favourites editor (max 12), a mode switch "Classic ring / Smart ring", validation.
Result gets a field size_source (estimate|predicted|verified). Hover predictions show "~96 KB". The finished result and the toast show the exact measured size with a check mark. Add size_source to `smol shrink --json`.
Tests: migration from an old config (including a .bak), caps, dedupe, mode switching, floor validation, recents LRU.

VERIFY: Tests pass; an old config.toml still loads and a .bak appears; take screenshots of the donut for a 1.2 MB, a 12 KB and a 40 MB file in Classic AND Smart mode.
```

📎 Send Claude the six screenshots before continuing.


---

## A4.1 — Spike: what drag data is available before the drop 🟡

```
Read AGENTS.md, PLAN.md, DECISIONS.md and PROGRESS.md only. Do NOT read PROMPTS.md, AG-PROMPTS.md, AG-PROMPTS-FINAL.md or BACKLOG.md.

Rules for this session:
- Do ONLY the task below. Nothing else.
- Work test-first: write the test first (expect fail), write the code, run again (expect pass).
- Never weaken, skip or delete a test. If a test is wrong, say why and ask me.
- Never say "this should work." Run it and show me the real output.
- When done: run VERIFY, git commit with a clear message, update PROGRESS.md.
- First reply: 2-sentence understanding, files you will create or change, tests you will write. Then STOP and wait for my "go".

TASK: Spike only, no product code. Create spikes/d_dragenter_data.py using PySide6: a small always-on-top window that logs, on dragEnterEvent, dragMoveEvent and dropEvent: whether mimeData().hasUrls() is true, the mime formats, the URLs, and the time taken to read them.
I will test six cases and report each: (1) one file from Nemo, (2) several files, (3) a folder, (4) a file from inside an archive opened in the archive manager, (5) a file from a mounted network or phone location (skip if I have none), (6) an image dragged from a web browser.
For each case print: URLs available at ENTER? at MOVE? only at DROP? How many milliseconds?

VERIFY: You run all six cases and paste the output. 📎 Bring that output to Claude before A4.2.
```

📎 Paste the six results to Claude.


---

## A4.2 — Pre-drop classification and the Unsupported state 🔴

```
Read AGENTS.md, PLAN.md, DECISIONS.md and PROGRESS.md only. Do NOT read PROMPTS.md, AG-PROMPTS.md, AG-PROMPTS-FINAL.md or BACKLOG.md.

Rules for this session:
- Do ONLY the task below. Nothing else.
- Work test-first: write the test first (expect fail), write the code, run again (expect pass).
- Never weaken, skip or delete a test. If a test is wrong, say why and ask me.
- Never say "this should work." Run it and show me the real output.
- When done: run VERIFY, git commit with a clear message, update PROGRESS.md.
- First reply: 2-sentence understanding, files you will create or change, tests you will write. Then STOP and wait for my "go".

TASK: Implement pre-drop classification using the A4.1 results (paste its summary here: <PASTE A4.1 RESULTS>).
(1) smol/core/classify.py: classify(path) -> Classification(kind: jpeg|png|webp|heic|pdf|folder|unsupported|unreadable|remote, reason, mismatch_note). Sniff the header first (read at most 32 bytes), the extension second; if they disagree trust the header and set mismatch_note. Regular files only: os.stat first; refuse FIFOs, sockets and device files WITHOUT opening them; do not follow symlinks to non-regular files. Ignore non-file:// URIs with reason "remote". Folders: "folder, not supported". Classify at most 50 files; the rest count as "+N more" and are treated as unknown. Never decode images during classification.
(2) Donut: on drag-enter, classify in a worker thread with a 300 ms overall timeout. States: all supported, none supported, mixed, unknown ("Checking..."). None supported: the centre shows "Unsupported file type (.docx)", all segments dim and drops are rejected (not-allowed cursor over segments). Mixed: "2 of 3 supported, 1 will be skipped". A drop processes only the supported files and the final toast lists the skipped ones by name. If the A4.1 spike shows that URLs are only available at drop time, show the neutral "Checking..." state and classify at drop, and tell me.
Tests: header sniffing on generated samples, a mismatched extension, a FIFO (os.mkfifo in a temp dir), a broken symlink, a folder, 60 files, and timeout behaviour with a stub that sleeps.

VERIFY: Tests pass. Drag an image, a .docx, a mixed pair, a folder and a PDF renamed to .jpg onto the donut: each shows the right state BEFORE you drop.
```


---

## A5 — Wayland guard 🟡

```
Read AGENTS.md, PLAN.md, DECISIONS.md and PROGRESS.md only. Do NOT read PROMPTS.md, AG-PROMPTS.md, AG-PROMPTS-FINAL.md or BACKLOG.md.

Rules for this session:
- Do ONLY the task below. Nothing else.
- Work test-first: write the test first (expect fail), write the code, run again (expect pass).
- Never weaken, skip or delete a test. If a test is wrong, say why and ask me.
- Never say "this should work." Run it and show me the real output.
- When done: run VERIFY, git commit with a clear message, update PROGRESS.md.
- First reply: 2-sentence understanding, files you will create or change, tests you will write. Then STOP and wait for my "go".

TASK: `smol daemon start` and `smol daemon run` must detect XDG_SESSION_TYPE=wayland and refuse with a clear message, exit code 3: "smol's hold-key donut needs an X11 session. Right-click integration and the smol CLI still work. Log out and choose an X11/Xorg session at the login screen, or use right-click." Refuse even when DISPLAY exists (XWayland): global key capture is not reliable there. `smol doctor` shows a warning row for Wayland sessions. The autostart entry may stay; the check lives in the command.
Tests with mocked environment variables.

VERIFY: With XDG_SESSION_TYPE=wayland set, `uv run smol daemon start` prints the message and exits with code 3 (`echo $?`); on your real X11 session the daemon starts normally.
```


---

## FREEZE — Pre-audit freeze 🟡

```
Read AGENTS.md, PLAN.md, DECISIONS.md and PROGRESS.md only. Do NOT read PROMPTS.md, AG-PROMPTS.md, AG-PROMPTS-FINAL.md or BACKLOG.md.

Rules for this session:
- Do ONLY the task below. Nothing else.
- Never say "this should work." Show real output for every check.
- When done: run VERIFY, git commit, update PROGRESS.md.
- First reply: your plan (files to touch, what you will check). Then STOP and wait for my "go".

TASK: Pre-audit freeze. No new features.
(1) Run ruff and the full pytest suite. Fix failures without weakening any test.
(2) DRIFT CHECK: compare the code with PLAN.md, AGENTS.md and DECISIONS.md. Report every contradiction, dead code, TODO, skipped or weakened test to me FIRST. Fix only what I approve.
(3) Make sure PLAN.md and PROGRESS.md reflect Q0 to A5.
(4) Tag v0.9.0 as the audit baseline.

VERIFY: Ruff clean, tests green, tag v0.9.0 exists (`git tag`), and you received a drift report.
```


---

## P10.1 — Security pass (widened scope) 🔴

```
Read AGENTS.md, PLAN.md, DECISIONS.md and PROGRESS.md only. Do NOT read PROMPTS.md, AG-PROMPTS.md, AG-PROMPTS-FINAL.md or BACKLOG.md.

Rules for this session:
- Do ONLY the task below. Nothing else.
- Work test-first: write the test first (expect fail), write the code, run again (expect pass).
- Never weaken, skip or delete a test. If a test is wrong, say why and ask me.
- Never say "this should work." Run it and show me the real output.
- When done: run VERIFY, git commit with a clear message, update PROGRESS.md.
- First reply: 2-sentence understanding, files you will create or change, tests you will write. Then STOP and wait for my "go".

TASK: Audit the entire project for security and robustness. First reply with the full audit plan. Cover:
- subprocess calls: list arguments only, never shell=True or a string; filenames that begin with a dash get "--" or an absolute path
- filename handling: spaces, unicode, leading dash, newlines and control characters, symlinks, path traversal
- NEW code: smol/core/classify.py (FIFOs, devices, broken symlinks, huge file counts, timeouts), config migration (.bak handling, malformed or hostile TOML, huge values), favourites and recents (injection, length limits), the Wayland guard
- text injection: file names shown in the donut, toasts and notifications must be rendered as PLAIN text (no Qt rich-text interpretation); notify-send arguments must be escaped and use "--"; log lines must neutralise newlines and control characters in filenames
- temp files: unpredictable names, private permissions, cleanup on failure and cancel; atomic writes; no partial files visible to the user
- permissions on logs and config; behaviour when the disk is full or the output folder is read-only
- daemon: X11 key and pointer grabs released on crash or exit; single-instance lock; crash recovery
- integration scripts (Nemo action, autostart): quoting, reversibility, never overwriting existing entries
- decompression bombs and pixel limits; PDF handling (Ghostscript -dSAFER, no external file access)
- leftover video or audio code or references
Report findings by severity. Fix all of them with tests. Write SECURITY.md (threat model in one page, what we do and do not protect against).

VERIFY: All tests pass. Try dropping a file named `-rf weird 'name".jpg` (and one containing a newline) and confirm it works, and that the toast, the notification and the daemon log show the name as plain text.
```

📎 Send Claude the findings list (severity and one line each) when it is done.


---

## P10.2 — Installable package 🟡

```
Read AGENTS.md, PLAN.md, DECISIONS.md and PROGRESS.md only. Do NOT read PROMPTS.md, AG-PROMPTS.md, AG-PROMPTS-FINAL.md or BACKLOG.md.

Rules for this session:
- Do ONLY the task below. Nothing else.
- Never say "this should work." Show real output for every check.
- When done: run VERIFY, git commit, update PROGRESS.md.
- First reply: your plan (files to touch, what you will check). Then STOP and wait for my "go".

TASK: Make `uv tool install .` install smol cleanly on a clean virtual environment. Add install.sh that installs the tool, runs `smol doctor`, offers right-click integration and autostart (autostart only on X11 sessions), and explains how to uninstall. Add uninstall.sh that removes integration and autostart and keeps the config unless --purge is passed.
Do NOT bundle Ghostscript or qpdf: print clear install instructions if they are missing (Debian/Ubuntu/Mint: sudo apt install ghostscript qpdf libxcb-cursor0).

VERIFY: On a clean venv the install works; `smol doctor` is green or shows clear hints; `uninstall.sh` leaves nothing behind except the config.
```


---

## ICON — Placeholder icon and desktop entry 🟡

```
Read AGENTS.md, PLAN.md, DECISIONS.md and PROGRESS.md only. Do NOT read PROMPTS.md, AG-PROMPTS.md, AG-PROMPTS-FINAL.md or BACKLOG.md.

Rules for this session:
- Do ONLY the task below. Nothing else.
- Never say "this should work." Show real output for every check.
- When done: run VERIFY, git commit, update PROGRESS.md.
- First reply: your plan (files to touch, what you will check). Then STOP and wait for my "go".

TASK: Create a simple placeholder icon: assets/icon/smol.svg, a ring (donut) with a small inward pinch, flat, two colours (dark graphite and one accent), readable at 16 px. Generate PNGs at 16, 24, 32, 48, 64, 128, 256, 512 into assets/icon/hicolor/<size>x<size>/apps/smol.png using rsvg-convert or Inkscape (tell me which is installed, or what to install). Also produce a monochrome tray variant. Create packaging/smol.desktop (Name=smol, Exec=smol donut, Icon=smol, Categories=Utility;Graphics;, Comment, StartupNotify=false). Validate it with desktop-file-validate if available. State clearly that this is a placeholder and real branding comes after v1.0.

VERIFY: The PNG files exist at all sizes, the SVG opens in an image viewer, and `desktop-file-validate packaging/smol.desktop` reports no errors.
```


---

## P10.3 — AppImage 🔴

```
Read AGENTS.md, PLAN.md, DECISIONS.md and PROGRESS.md only. Do NOT read PROMPTS.md, AG-PROMPTS.md, AG-PROMPTS-FINAL.md or BACKLOG.md.

Rules for this session:
- Do ONLY the task below. Nothing else.
- Never say "this should work." Show real output for every check.
- When done: run VERIFY, git commit, update PROGRESS.md.
- First reply: your plan (files to touch, what you will check). Then STOP and wait for my "go".

TASK: Produce a single-file AppImage using PyInstaller (onedir output) plus appimagetool, with the icon and packaging/smol.desktop from the ICON step. Keep the PyInstaller onedir output in a stable path (dist/smol/) because the .deb step will reuse it. State the final size honestly. Test that it runs `smol --version` and opens the donut with no Python or smol installed (use a clean venv or a clean user account). Document the libfuse2 requirement on Ubuntu 22.04+ and the --appimage-extract-and-run fallback. Ghostscript and qpdf are NOT bundled: `smol doctor` must guide users. If AppImage proves impractical for PySide6 on this machine, explain exactly why and propose the best alternative.

VERIFY: The AppImage runs `./smol-*.AppImage --version` and opens the donut; the size is reported; no bundled Ghostscript or qpdf.
```


---

## P10.3b — .deb package 🔴

```
Read AGENTS.md, PLAN.md, DECISIONS.md and PROGRESS.md only. Do NOT read PROMPTS.md, AG-PROMPTS.md, AG-PROMPTS-FINAL.md or BACKLOG.md.

Rules for this session:
- Do ONLY the task below. Nothing else.
- Never say "this should work." Show real output for every check.
- When done: run VERIFY, git commit, update PROGRESS.md.
- First reply: your plan (files to touch, what you will check). Then STOP and wait for my "go".

TASK: Build a .deb from the same PyInstaller onedir output as the AppImage. Use dpkg-deb with a hand-written control file (no extra build tools). Layout: files in /opt/smol/, symlink /usr/bin/smol, /usr/share/applications/smol.desktop, icons in /usr/share/icons/hicolor/*/apps/. Control file: Package smol; Depends ghostscript, qpdf, libxcb-cursor0 (and the other Qt xcb runtime libraries the PyInstaller output needs: find them with ldd and list the Debian package names); Recommends libnotify-bin; Architecture amd64; Section utils. Add postinst/postrm that refresh the desktop and icon caches and never touch user config. Write packaging/build_deb.sh. Check with `lintian` if it is installed and `dpkg-deb -I` / `-c`. Ask me before running any sudo command, then test `sudo dpkg -i`, `smol --version`, and `sudo apt remove smol` on this machine. Note which Ubuntu version the release build must use (oldest supported, for glibc compatibility).

VERIFY: `dpkg-deb -I` and `-c` look right; install, `smol --version`, the menu entry with the icon, and removal all work on this machine.
```


---

## P10.4 — README and docs 🟡

```
Read AGENTS.md, PLAN.md, DECISIONS.md and PROGRESS.md only. Do NOT read PROMPTS.md, AG-PROMPTS.md, AG-PROMPTS-FINAL.md or BACKLOG.md.

Rules for this session:
- Do ONLY the task below. Nothing else.
- Never say "this should work." Show real output for every check.
- When done: run VERIFY, git commit, update PROGRESS.md.
- First reply: your plan (files to touch, what you will check). Then STOP and wait for my "go".

TASK: Write README.md covering: what smol is; a demo GIF placeholder; **a clear "Requirements" box: the hold-key donut needs an X11 session (e.g. Cinnamon, MATE, Xfce, or choose an X11/Xorg session at login); right-click integration and the CLI work on any session**; install options (AppImage, .deb, uv tool install) with the dependencies (ghostscript, qpdf, libxcb-cursor0, libfuse2 for AppImage on Ubuntu 22.04+); usage; the default trigger key Super and why plain Ctrl is not used; classic ring versus smart ring; settings; supported formats (JPEG, PNG, WebP, HEIC input, PDF) and honest limits (a target can be impossible; the smallest achievable size is reported); troubleshooting; uninstall; "Not supported yet": video, audio, Office documents, Windows (see BACKLOG.md for plans).
Add docs/ARCHITECTURE.md (one page, text diagram) and docs/decisions/ with short records (point to DECISIONS.md).

VERIFY: A person who has never seen the project can follow the README on a clean X11 desktop and succeed.
```


---

## P10.5 — CI and release builds 🟡

```
Read AGENTS.md, PLAN.md, DECISIONS.md and PROGRESS.md only. Do NOT read PROMPTS.md, AG-PROMPTS.md, AG-PROMPTS-FINAL.md or BACKLOG.md.

Rules for this session:
- Do ONLY the task below. Nothing else.
- Never say "this should work." Show real output for every check.
- When done: run VERIFY, git commit, update PROGRESS.md.
- First reply: your plan (files to touch, what you will check). Then STOP and wait for my "go".

TASK: Add GitHub Actions workflows:
(1) On every push and pull request: ruff check and pytest (Python 3.12; Qt tests with QT_QPA_PLATFORM=offscreen; mark display-dependent tests so CI skips them).
(2) On version tags: build the AppImage AND the .deb on the oldest supported Ubuntu runner (for glibc compatibility), generate SHA256SUMS, and attach all three to the GitHub release as a draft.
Do not publish anything.

VERIFY: Push to GitHub: the first workflow goes green. The release workflow is only tested later, on the v1.0.0 tag.
```


---

## P10.6 — Final QA 🔴

```
Read AGENTS.md, PLAN.md, DECISIONS.md and PROGRESS.md only. Do NOT read PROMPTS.md, AG-PROMPTS.md, AG-PROMPTS-FINAL.md or BACKLOG.md.

Rules for this session:
- Do ONLY the task below. Nothing else.
- Never say "this should work." Show real output for every check.
- When done: run VERIFY, git commit, update PROGRESS.md.
- First reply: your plan (files to touch, what you will check). Then STOP and wait for my "go".

TASK: Run the full QA checklist against every "Done when" in PLAN.md AND the approved v1.0 items in BACKLOG.md (IDEA-001 to IDEA-008). For each item: command, expected, actual. Include: classic ring on 1.2 MB, 12 KB and 40 MB files; smart ring opt-in; pre-drop Unsupported and mixed states; Wayland guard message; config migration from an old file; right-click on Nemo; AppImage and .deb install and removal; uninstall.sh.
Check that no test was weakened during the whole build (review git history for deleted, skipped or loosened tests). Fix blockers; list the rest under "Known limitations" in the README.

VERIFY: The QA report is all green, or every red item has a workaround or a known-issue note.
```

📎 Send Claude the QA report before the release.


---

## P10.7 — Release v1.0.0 🟡

```
Read AGENTS.md, PLAN.md, DECISIONS.md and PROGRESS.md only. Do NOT read PROMPTS.md, AG-PROMPTS.md, AG-PROMPTS-FINAL.md or BACKLOG.md.

Rules for this session:
- Do ONLY the task below. Nothing else.
- Never say "this should work." Show real output for every check.
- When done: run VERIFY, git commit, update PROGRESS.md.
- First reply: your plan (files to touch, what you will check). Then STOP and wait for my "go".

TASK: Bump the version to 1.0.0, update CHANGELOG.md, prepare release notes (what smol does, the X11 requirement stated in the first lines, install options, supported formats, known limitations). Tag v1.0.0 locally. Give me the exact commands to push the tag and publish the release. Do NOT push or publish anything without my explicit approval.

VERIFY: Release page ready; AppImage, .deb and SHA256SUMS attached; install instructions tested from scratch on a clean machine or venv.
```


---

## Rescue prompts

### STUCK (after 2 failed attempts)
```
Stop trying new fixes.
Tell me: what we expected, what happened (paste the full error), what you already tried, and your top 3 hypotheses ranked by likelihood.
Then propose ONE small experiment that tells the hypotheses apart. No code yet.
```

### DRIFT CHECK (every 3 to 4 prompts)
```
Compare the current code to PLAN.md, AGENTS.md and DECISIONS.md.
List: anything that contradicts them, dead code, TODOs, weakened or skipped tests.
Report only. Change nothing.
```

### CONTEXT RESET (when the session gets long or confused)
```
Write the current state into PROGRESS.md: what is done, what is half-done, the exact next step, known issues, and any decision made this session.
Then stop. I will start a fresh session.
```
