# Discussion: Issue #51 — Uso consistente de _trusted_client_ip

**Date**: 2026-05-24
**Issue**: https://github.com/Dkalds/Licitaciones_sap_SP/issues/51
**RFC**: docs/rfc/051-trusted-client-ip-consistency.md
**Status**: Implemented, pending human review

## Summary

Three code locations read `X-Forwarded-For` directly without validating the source proxy, allowing IP spoofing in access logs, Prometheus metrics, and CSP report rate limiting. Fixed by replacing all three with calls to the existing `_trusted_client_ip()` function.

## Decision

Use `_trusted_client_ip(request)` consistently across all code that needs client IP. The function validates that the direct TCP connection comes from a trusted proxy before honoring XFF.

## Files changed

- `api/middleware.py` — AccessLogMiddleware
- `api/routes/security.py` — CSP report endpoint
- `api/app.py` — /metrics endpoint

## Future consideration

Consider moving `_trusted_client_ip` to `shared/` or injecting the resolved IP via `request.state.client_ip` in a single middleware to prevent future inconsistencies.
