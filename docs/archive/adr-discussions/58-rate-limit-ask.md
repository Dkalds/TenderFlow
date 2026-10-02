# Discussion: Issue #58 — Rate limiting /api/v1/ask (LLM)

## Summary

Added `/api/v1/ask` (10 req/min) and `/api/v1/ask/models` (30 req/min) to `_HEAVY_ENDPOINT_LIMITS` in `api/middleware.py` to prevent abuse of costly LLM API calls.

## Decision

Minimal change: two entries added to the existing heavy endpoint limits dict. No new middleware, no schema changes, no new dependencies.

## Review Notes

- **Security**: Rate limit of 10 req/min prevents cost abuse. The existing middleware infrastructure handles enforcement.
- **No invariants affected**: No typing, DB, migration, or auth changes.
- **Tests**: 3 new unit tests verify the dict entries and middleware integration.

## RFC

See `docs/rfc/058-rate-limit-ask-endpoint.md`.
