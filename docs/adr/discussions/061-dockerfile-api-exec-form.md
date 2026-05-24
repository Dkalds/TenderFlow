# Discussion: Issue #61 — Dockerfile.api CMD exec form

**Date**: 2026-05-24
**Issue**: https://github.com/Dkalds/Licitaciones_sap_SP/issues/61
**RFC**: docs/rfc/061-dockerfile-api-exec-form.md

## Summary

Dockerfile.api used `CMD ["sh", "-c", "..."]` which ran `sh` as PID 1, preventing SIGTERM propagation to uvicorn. Fixed by introducing `docker-entrypoint-api.sh` with `exec` and using `ENTRYPOINT` exec form.

## Decision

- Created `docker-entrypoint-api.sh` with `exec python -m uvicorn ...`
- Changed Dockerfile.api to use `ENTRYPOINT ["docker-entrypoint-api.sh"]` + `CMD ["--workers", "2"]`
- uvicorn now runs as PID 1 via `exec`, receiving signals directly

## Review Notes

- No AGENTS.md §3 invariants affected (pure infrastructure change)
- No security concerns — entrypoint only runs uvicorn with existing config
- Pattern consistent with Dockerfile.dashboard exec form usage
