# Discussion: Issue #44 — GDPR get_user_id_from_key_id fallback fix

**Date**: 2026-05-24
**Issue**: https://github.com/Dkalds/Licitaciones_sap_SP/issues/44
**RFC**: docs/rfc/044-gdpr-fallback-fix.md

## Summary

Removed dangerous fallback in `get_user_id_from_key_id()` that returned the first user from the database when `user_id` was unavailable. This could cause GDPR operations to affect the wrong user — a RGPD Art. 17 violation.

## Decision

Return `None` with warning logs instead of falling back to an arbitrary user. Callers already handle `None` via `if user_id:` guards.

## Review Notes

- **Reviewer**: No invariants broken. Change is minimal and surgical. `services/` is not typing-strict so no mypy strict concerns.
- **Security triage**: Severity HIGH. The old code could execute `anonymize_user_data` on user ID 1 when the actual user's `user_id` was NULL. Fix correctly eliminates the vulnerability. No new attack surface introduced.
- **Test coverage**: 2 new regression tests added ensuring `None` is returned for missing keys and NULL user_id. Existing test updated to assert `None` instead of accepting fallback.

## Future Work

- Consider making `user_id` NOT NULL in `api_keys` via Alembic migration (requires human approval per AGENTS.md §6).
