# Discussion: Issue #47 — Race condition en close_pool()

**Date**: 2026-05-24
**RFC**: docs/rfc/047-close-pool-race-condition.md
**Status**: Implemented

## Summary

`close_pool()` in `db/connection.py` checked `_pool is not None` and drained the pool without holding `_pool_lock`. This allowed concurrent `_get_conn()` calls to create connections that would never be closed (leak) or to use already-closed connections.

## Decision

Applied swap-then-drain pattern:
1. Under `_pool_lock`: capture pool reference, set `_pool = None`, reset `_pool_active = 0`
2. Outside lock: drain the captured queue (avoids deadlock)
3. `_return_conn()` now checks `_pool` under lock; closes orphan connections if pool was nullified

## Review Notes

- **Invariants**: No typing regressions, no migration changes, no auth changes
- **Security**: No new attack surface. Connection cleanup is defensive (exceptions silenced)
- **Testing**: 4 new unit tests covering: thread-local cleanup, atomic nullification, drain behavior, orphan connection handling
