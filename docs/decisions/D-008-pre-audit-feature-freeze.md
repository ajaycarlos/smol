# D-008: Pre-Audit Feature Freeze & Configuration Stability

- **Date**: 2026-10-20
- **Status**: Fixed
- **Canonical Reference**: [DECISIONS.md](../../DECISIONS.md#L14)

## Decision
All public configuration schemas (v1 config schema, platform seam, suggestion engine, pre-drop classification, Wayland guard) must be completed and frozen prior to the comprehensive security audit. Post-audit feature additions are prohibited prior to v1.0 release.

## Why
Adding new code after a security audit would result in shipping un-audited code to production. Furthermore, configuration schemas and CLI argument formats represent public user contracts that must remain backwards-compatible once released.
