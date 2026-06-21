---
rfc: 050
title: "Fix IDOR en export jobs — validar ownership por key_hash"
issue: https://github.com/Dkalds/Licitaciones_sap_SP/issues/50
author: agent:architect
date: 2026-05-24
status: implemented
---

## Contexto

El endpoint `GET /exports/{job_id}` y `DELETE /exports/{job_id}` solo requieren un API key válido pero no validan que el job pertenezca al usuario que lo creó. Cualquier usuario autenticado puede acceder a exports de otro si conoce el UUID. Esto es un IDOR (Insecure Direct Object Reference) — severidad P2.

## Decisión

1. Al crear un export job (`POST /exports`), almacenar el `key_hash` del `AuthContext` como `owner` en `_store[job_id]`.
2. En `GET /exports/{job_id}` y `DELETE /exports/{job_id}`, recibir el `AuthContext` (ya disponible via `Depends(require_api_key)`) y comparar `job["owner"]` con `ctx.key_hash`. Si no coincide → HTTP 403.
3. Cambiar `_auth: Any = Depends(require_api_key)` a `ctx: AuthContext = Depends(require_api_key)` para tener acceso al `key_hash`.

**Qué NO se hace:**
- No se cambia el almacén en memoria a DB (fuera de scope).
- No se cambia el mecanismo de auth (HMAC-SHA256 se mantiene).
- No se requiere migración de schema.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Scoped UUIDs (namespace por usuario) | Aislamiento total | Más complejo, rompe URLs existentes | Over-engineering para el problema |
| Signed job IDs (HMAC del UUID) | Sin estado extra | Requiere secret management adicional | Complejidad innecesaria |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Ninguno — `api/routes/` no es strict | — |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno — sin cambios DB | — |
| §3.4 Auto-marking tests | Ninguno — test nombrado `test_unit_*` | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Ninguno — usa AuthContext existente | — |

## Plan de implementación

1. `api/routes/exports.py`: cambiar los 3 endpoints para usar `AuthContext` tipado, almacenar `owner` en `_store`, validar ownership en GET y DELETE.
2. `tests/test_unit_export_idor.py`: test que verifica 403 cuando un usuario intenta acceder al export de otro.

**Archivos de partida**: `api/routes/exports.py`, `api/auth.py`
**Riesgo estimado**: bajo
**Tiempo estimado**: 1 hora

## Acceptance criteria

- [x] `POST /exports` almacena `owner` = `key_hash` del creador
- [x] `GET /exports/{id}` devuelve 403 si `key_hash` del request ≠ owner
- [x] `DELETE /exports/{id}` devuelve 403 si `key_hash` del request ≠ owner
- [x] Test unitario verifica el comportamiento IDOR
- [x] `make lint && make typecheck && make test-unit` pasan en verde

## Notas de review

2026-05-24T00:00Z agent:reviewer — RFC aprobado. Cambio mínimo, usa AuthContext existente, no toca invariantes. Sin riesgo de regresión.
