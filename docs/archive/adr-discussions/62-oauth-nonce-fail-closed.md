# Discussion: Issue #62 — OAuth nonce store fail-closed

**Date**: 2026-05-24
**Issue**: https://github.com/Dkalds/Licitaciones_sap_SP/issues/62
**RFC**: docs/rfc/062-oauth-nonce-fail-closed.md
**Status**: Implemented

## Summary

The `_RedisNonceStore.contains()` method returned `False` when Redis was unavailable (fail-open), allowing potential replay attacks on OAuth state tokens.

## Decision

Implemented Option B: fail-closed with in-memory fallback. When Redis is unavailable:
- `contains()` delegates to an internal `_TTLCacheNonceStore` instead of returning `False`
- `add()` always writes to both Redis and the in-memory fallback

This provides anti-replay protection within the same process even during Redis outages, without blocking legitimate logins.

## Review Notes

- **Security**: Fix eliminates the fail-open vulnerability. The in-memory fallback doesn't cover cross-process replay during Redis outage, but this is acceptable for P3 severity.
- **Invariants**: No typing regressions. `shared/auth_core.py` maintains existing strict typing level. No new `Any` or `# type: ignore` added.
- **Tests**: 4 new/updated tests cover fallback behavior, dual-write, and replay detection via fallback.
