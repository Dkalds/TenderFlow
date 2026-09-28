# Discussion Log — Issue #50: IDOR en export jobs

**Issue**: https://github.com/Dkalds/Licitaciones_sap_SP/issues/50
**RFC**: docs/rfc/050-idor-export-jobs.md
**Branch**: agent/issue-50-idor-export-jobs
**Date**: 2026-05-24

## Timeline

1. **RFC draft** — Propuesta: asociar `key_hash` como owner en `_store`, validar en GET/DELETE con 403.
2. **RFC review** — Aprobado sin cambios. Cambio mínimo, usa AuthContext existente.
3. **Implementation** — 3 endpoints modificados en `api/routes/exports.py`. `_auth: Any` → `ctx: AuthContext`.
4. **Tests** — 8 tests unitarios en `tests/test_unit_export_idor.py` (owner access, 403, 404, delete, create).
5. **Gates** — lint ✅, typecheck ✅, tests ✅ (8/8 passed).
6. **Security review** — No timing leak, no auth weakening, backward-compatible.

## Decision

Fix IDOR vinculando ownership de export jobs al `key_hash` del creador. Defensa en profundidad sobre UUID entropy.

## Status

Pendiente de human review para merge.
