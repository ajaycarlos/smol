# D-014: Padding and Range Targets

- **Date**: 2026-10-20
- **Status**: Fixed
- **Canonical Reference**: [DECISIONS.md](../../DECISIONS.md#L20)

## Decision
Artificially inflating file sizes (padding bytes with zero-byte comments or metadata) and supporting strict range targets (e.g. "between 40 KB and 50 KB") are deferred to v1.3+ and are excluded from v1.0. When added, any padding method must be explicitly labelled in the result object.

## Why
Adding artificial padding would alter Engine Promise #1 ("output is always <= target and close to it without adding unnecessary fluff"). It requires careful specification changes so users understand that extra bytes were artificially added rather than containing image data.
