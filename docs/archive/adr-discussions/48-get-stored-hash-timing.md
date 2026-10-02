# Discussion: Issue #48 — get_stored_hash silent exception swallowing

**Date**: 2026-05-24
**Issue**: https://github.com/Dkalds/Licitaciones_sap_SP/issues/48
**RFC**: docs/rfc/048-get-stored-hash-exception-handling.md
**Status**: Implemented

## Summary

`get_stored_hash()` in `services/auth.py` caught all exceptions and returned `None`, which:
1. Silenced DB errors (connection failures, corruption)
2. Enabled timing attacks — when `stored_hash` was `None`, `hmac.compare_digest` was skipped

## Decision

- `services/auth.py`: Log and re-raise DB exceptions instead of swallowing them
- `api/auth.py`: Catch DB errors → HTTP 503; `None` hash → dummy constant-time compare + 401

## Review Notes

- **Security**: Timing attack vector eliminated. All code paths now perform constant-time comparison.
- **Invariants**: §3.6 (HMAC auth) strengthened. No other invariants affected.
- **Tests**: 5 unit tests added covering error propagation, None handling, and HTTP status codes.
