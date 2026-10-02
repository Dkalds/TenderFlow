# Discussion: Issue #63 — MaxBodyMiddleware raw ASGI migration

**Date**: 2026-05-24
**Issue**: https://github.com/Dkalds/Licitaciones_sap_SP/issues/63
**RFC**: docs/rfc/063-maxbody-raw-asgi-middleware.md

## Summary

Migrated `_MaxBodyMiddleware` from `BaseHTTPMiddleware` (Starlette anti-pattern) to raw ASGI middleware. Eliminated access to private `request._body` attribute.

## Review notes

- **Reviewer**: No invariants affected (§3.1–§3.6 all clear). Change is localized to `api/app.py`.
- **Security triage**: No security concerns. The middleware still enforces 1MB body limit. The 413 response uses hardcoded JSON (no injection risk). No new dependencies introduced.
- **Test coverage**: 8 unit tests covering GET passthrough, small/exact/over-limit POST, PUT, JSON response format.

## Decision

Approved and implemented. Raw ASGI middleware avoids double-buffering, preserves streaming, and removes dependency on private Starlette internals.
