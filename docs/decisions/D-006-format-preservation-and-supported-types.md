# D-006: Format Preservation and Supported Types

- **Date**: 2026-10
- **Status**: Fixed
- **Canonical Reference**: [DECISIONS.md](../../DECISIONS.md#L12)

## Decision
v1.0 supports:
- **Images**: JPEG, PNG, WebP, HEIC/AVIF (input).
- **Documents**: PDF.

By default, `smol` keeps the original input format (JPEG $\to$ JPEG, PNG $\to$ PNG, WebP $\to$ WebP, PDF $\to$ PDF). HEIC and AVIF decode to JPEG. Format conversion (e.g. PNG $\to$ JPEG) occurs only when explicitly permitted via `--allow-convert` or Settings.

## Why
Third-party upload forms often enforce strict format validators (e.g. "JPG only" or "PNG only"). Silently converting formats would lead to rejected uploads.
