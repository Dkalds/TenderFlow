# Discussion: Issue #46 — Fix silent DB init error in dev/staging

**Date**: 2026-05-24
**Issue**: https://github.com/Dkalds/Licitaciones_sap_SP/issues/46
**RFC**: docs/rfc/046-fix-silent-db-init-error.md
**Status**: Implemented

## Summary

Removed environment-conditional error handling in `api/app.py` lifespan. Previously, `init_db()` failures were silently swallowed in dev/staging, allowing the app to start without a database. Now the exception is always re-raised (fail-fast universal).

## Review Notes

- **2026-05-24 agent:reviewer** — Change is minimal (2 lines removed, 1 added). No invariants affected. No security implications. Approved.
- **2026-05-24 agent:security_triage** — No security concerns. The change improves reliability by preventing a degraded state. No secrets or auth changes.

## Decision

Fail-fast universal is the correct approach. Graceful degradation was considered but rejected as it adds complexity without benefit — the app cannot serve any useful response without a database.
