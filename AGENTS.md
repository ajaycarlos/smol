# AGENTS.md — rules for every coding session

Project: **smol**. Shrink any file to at most a chosen size.
Hold a key, drag a file, drop it on a size in a donut menu at the cursor.
Linux first. Full spec in `PLAN.md`. Current status in `PROGRESS.md`.

## About the human owner
The owner does NOT write code. They run the commands you give them and report what happened.
- Explain in plain language. Give exact copy-paste commands.
- Never say "this should work". Run it, show the real output, then say it works.
- If something fails, show the full error and fix the root cause. Never hide a failure, stub it out, or delete a test to make it pass.

## Session discipline
1. At the start, read `AGENTS.md`, `PLAN.md`, `PROGRESS.md`. Then restate the task in 2 sentences.
2. Do ONE task per session. Do not touch anything outside the task. No drive-by refactors.
3. Before coding, list the files you will create or change. Wait for approval if the change is large.
4. When done: run the tests, run the task's "Done when" check from `PLAN.md`, `git commit` with a clear message, and update `PROGRESS.md` (done / next / known issues).
5. If you are unsure about a product decision, ask. Do not guess silently.

## Fixed tech stack (do not change without asking)
- Python 3.12, `uv` (or venv), `pytest`, `ruff`
- Images: Pillow (+ pillow-heif). UI: PySide6 (Qt 6)
- External tools called with `subprocess` (list arguments, never shell strings): `ffmpeg`, `ffprobe`, `gs` (Ghostscript), `qpdf`
- No new dependency without saying what it is, why, and its license.

## Layout
```
smol/
  core/          engine. NO UI imports. Must run headless.
  cli/           `smol` command
  ui/            donut overlay, toast, settings (PySide6)
  daemon/        hold-key listener and overlay summoner
  integrations/  file-manager right-click scripts, autostart files
tests/
spikes/          throwaway experiments (M0)
PLAN.md  PROGRESS.md  AGENTS.md  NOTICE
```

## Engine promises (never break these)
1. Output is always <= target bytes. 1 KB = 1000 bytes (safe for sites that use 1024). Aim for 92–99% of the target, not far below it.
2. The original file is never modified or overwritten. Output goes next to it as `<name>_<size>.<ext>`; on collision add `-1`, `-2`.
3. If the target is impossible without ruining the file, return a failure that states the smallest acceptable size and why. Never save a file above the target and call it success.
4. Lower quality down to a floor first, then shrink dimensions. Never go below the minimum dimension (default 200 px short side) unless the user allows it.
5. Keep the file format by default. Strip GPS and camera metadata by default (setting).
6. Core returns a result object: `ok, output_path, original_bytes, final_bytes, width, height, quality, steps, warning, error`.
7. Core functions are testable without a display.

## UI rules
- Engine never runs on the UI thread. Worker thread, emits progress signals.
- Animations target 60 fps and respect a "reduce motion" setting.
- `Esc` always cancels. Everything has a keyboard path.
- The donut must appear within 150 ms of the trigger.

## Safety
- Treat filenames as hostile: spaces, unicode, leading `-`, newlines.
- No network calls anywhere in the app.
- Do not copy code from other projects without recording source and license in `NOTICE`. (Filee is MIT-licensed; study it freely, attribute anything copied.)
- Do not bundle ffmpeg or Ghostscript. Detect them on the system and show a clear message if missing.

## Testing
- Every engine feature gets pytest cases on at least 10 varied sample files.
- Tests assert the real promises: size <= target, output opens, dimensions above floor, original unchanged.
- Test files live in `tests/samples/` (generated or public-domain only; never commit personal photos).

## Skills and tools

Skills are installed globally. Use the `skill` tool to load the matching one BEFORE starting work, then follow it.

| When you are about to... | Load this skill |
|---|---|
| Decide what a milestone item really requires | `spec-driven-development` |
| Split a milestone into small tasks | `planning-and-task-breakdown` |
| Write any feature code | `incremental-implementation`, then `test-driven-development` |
| Work on anything with PySide6/Qt | `pyqt`, plus `pyqt-threading` (workers) or `pyqt-styling` (looks) or `pyqt-testing` |
| Look at the running donut / toast / settings window | `qt-devtools-setup`, then `qt-devtools-app-interaction` |
| Add tray icon, notifications, dialogs, forms | `qt-devtools-desktop-integration`, `qt-devtools-form-and-input` |
| Make anything look good (colours, type, motion) | `frontend-design` (web-flavoured: use the principles, not the CSS) |
| Hit a failing test or unexpected error | `debugging-and-error-recovery` |
| Use a library API you are not 100% sure about | `source-driven-development` and the Context7 tool (say "use context7") |
| Claim a task is finished | `verification-before-completion` |
| Review your own diff | `code-review-and-quality`, `security-and-hardening` |
| Commit | `git-workflow-and-versioning` |
| Prepare a release | `shipping-and-launch` |

Hard rules:
- Never delete, skip, or weaken a test or a check to get to green. If a test is wrong, say why and ask.
- For any Qt/PySide6/Pillow API detail you are unsure of, look it up with Context7. Do not guess.
- Skills describe process; `PLAN.md` and this file decide what to build. If they conflict, this file wins.

## One command, many subcommands
The only console script is `smol`: `smol shrink`, `smol donut`, `smol daemon`, `smol settings`, `smol integrate`, `smol doctor`.
Config lives in `~/.config/smol/config.toml`; logs in `~/.local/state/smol/`.
