# D-001: Decimal Sizing & Inviolable Target

- **Date**: 2026-10
- **Status**: Fixed
- **Canonical Reference**: [DECISIONS.md](../../DECISIONS.md#L7)

## Decision
1. Standardize on **decimal byte sizing**: 1 KB = 1,000 bytes, 1 MB = 1,000,000 bytes.
2. The core compression engine guarantees that output file size is strictly **less than or equal to** (`<=`) target bytes.

## Why
- Many websites, examination portals, and government upload forms use decimal (1,000) or binary (1,024) definitions inconsistently. Sizing down to decimal 1,000 bytes ensures safety under both definitions (a 100,000-byte file is safely under 100 KB in decimal and 97.6 KiB in binary).
- Output byte sizes are verified directly from disk after writing; any candidate output exceeding target bytes is rejected.
