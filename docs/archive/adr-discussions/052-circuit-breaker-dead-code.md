# Discussion: Issue #52 — Circuit breaker reset_timeout dead code

**Date**: 2026-05-24
**Issue**: https://github.com/Dkalds/Licitaciones_sap_SP/issues/52
**RFC**: docs/rfc/052-circuit-breaker-dead-code.md

## Summary

The `CircuitBreaker` constructor used `reset_timeout=300` (5 min), but `_AdaptiveBackoffListener` immediately overwrites it to `settings.BREAKER_BASE_TIMEOUT` (60s) on the first state change. The initial value was dead code.

## Decision

Aligned the constructor to use `settings.BREAKER_BASE_TIMEOUT` directly. Added tests verifying initial timeout alignment and adaptive backoff behavior.

## Review Notes

- **Reviewer**: No invariants affected. Trivial change, low risk. No security implications.
- **Security triage**: No security concerns — change is purely cosmetic/correctness in timeout configuration.

## Files Changed

- `scraper/resilience.py`: line 127 — `60 * 5` → `settings.BREAKER_BASE_TIMEOUT`
- `tests/test_resilience.py`: added 2 tests (initial timeout, adaptive backoff)
- `docs/rfc/052-circuit-breaker-dead-code.md`: RFC
