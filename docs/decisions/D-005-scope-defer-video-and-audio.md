# D-005: Scope: Defer Video & Audio to v1.1

- **Date**: 2026-10
- **Status**: Fixed
- **Canonical Reference**: [DECISIONS.md](../../DECISIONS.md#L11)

## Decision
Video and audio compression pipelines are removed from the v1.0 release scope and deferred to v1.1 in [BACKLOG.md](../../BACKLOG.md). `ffmpeg` is not a required dependency for v1.0.

## Why
Video compression is fundamentally slow (often requiring seconds or minutes), requiring distinct UX expectations, progress management, and heavyweight dependencies (`ffmpeg`, `ffprobe`). Removing it allows v1.0 to ship a rock-solid, lightning-fast experience focusing on images and PDFs.
