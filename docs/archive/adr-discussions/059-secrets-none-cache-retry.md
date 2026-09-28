# Discussion: Issue #59 — config/secrets.py cachea valores None permanentemente

**Date**: 2026-05-24
**Issue**: https://github.com/Dkalds/Licitaciones_sap_SP/issues/59
**RFC**: docs/rfc/059-secrets-none-cache-retry.md

## Summary

Bug fix: `get_secret()` cached `None` results permanently, preventing retry on transient backend failures. Fix: only cache non-None results.

## Decision

Option A (simplest): skip caching when `result is None`. No TTL complexity needed.

## Review Notes

- **Reviewer**: Change is minimal (3 lines added, 1 removed). No invariants affected. Typing strict maintained in `config/`. No security implications.
- **Security triage**: No secrets exposed, no auth changes, no new attack surface. LGTM.

## Tests Added

- `test_none_not_cached_allows_retry`: verifies None is not cached and retry works
- `test_non_none_still_cached`: verifies existing caching behavior preserved
