---
rfc: 046
title: "Fix silent DB initialization error in dev/staging"
issue: https://github.com/Dkalds/Licitaciones_sap_SP/issues/46
author: agent:architect
date: 2026-05-24
status: implemented
---

## Contexto

En `api/app.py:89-92`, cuando `init_db()` falla en dev/staging, la excepción se captura y se loguea pero la app continúa sin BD. Esto causa errores 500 confusos en cada request posterior, difíciles de diagnosticar.

## Decisión

Opción A (fail-fast universal): re-lanzar la excepción en **todos** los entornos. Si la BD no inicializa, la app no debe arrancar. Esto es consistente con el principio fail-fast y simplifica el código.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| A: Fail-fast universal (elegida) | Simple, consistente, fácil de diagnosticar | App no arranca si BD falla | Es el comportamiento correcto |
| B: Graceful degradation + health check | App arranca, health reporta unhealthy | Complejidad extra, requests siguen fallando con 500 | Complejidad innecesaria para el beneficio |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Ninguno | — |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno | — |
| §3.4 Auto-marking tests | Ninguno | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. `api/app.py`: Eliminar el condicional `if settings.ENV == "prod"` — siempre re-lanzar la excepción tras loguearlo.
2. `tests/test_unit_api_startup.py`: Test que verifica que `lifespan` propaga la excepción cuando `init_db()` falla.

**Archivos de partida**: `api/app.py`
**Riesgo estimado**: bajo
**Tiempo estimado**: <1 hora

## Acceptance criteria

- [x] `init_db()` failure causa crash en todos los entornos
- [x] El error se loguea antes de re-lanzar
- [x] Test unitario cubre el caso
- [x] `make lint && make typecheck && make test-unit` pasan en verde
