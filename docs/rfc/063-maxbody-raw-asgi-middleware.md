---
rfc: 063
title: Migrar MaxBodyMiddleware de BaseHTTPMiddleware a raw ASGI
issue: https://github.com/Dkalds/Licitaciones_sap_SP/issues/63
author: agent:architect
date: 2026-05-24
status: approved
---

## Contexto

`_MaxBodyMiddleware` en `api/app.py:236-272` hereda de `BaseHTTPMiddleware` (anti-pattern documentado por Starlette) y accede al atributo privado `request._body`. Esto causa:

1. Doble buffering del body en memoria
2. Interferencia con streaming responses (SSE en `/api/v1/stream`)
3. Background tasks pueden no ejecutarse correctamente
4. Fragilidad ante upgrades de Starlette por uso de `_body`

## Decisión

Reescribir `_MaxBodyMiddleware` como raw ASGI middleware que:
- Intercepta `http.request` messages en `receive()` y acumula tamaño
- Rechaza con 413 si se excede el límite (1 MB)
- Mantiene el fast-path de Content-Length check
- No toca `request._body` ni hereda de `BaseHTTPMiddleware`
- Se elimina el import de `BaseHTTPMiddleware`

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Mantener BaseHTTPMiddleware | Sin cambios | Anti-pattern, `_body` privado, streaming roto | Es el bug reportado |
| Usar middleware de terceros (e.g. limits) | Mantenido externamente | Nueva dependencia, menos control | Evitar deps innecesarias |
| Configurar max body en uvicorn/nginx | Zero code | No disponible en uvicorn; requiere reverse proxy | No siempre hay reverse proxy |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Ninguno — `api/` no es strict | — |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno | — |
| §3.4 Auto-marking tests | Ninguno — test nombrado `test_unit_*` | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. Reescribir `_MaxBodyMiddleware` en `api/app.py` como clase ASGI pura (sin herencia de BaseHTTPMiddleware)
2. Eliminar import de `BaseHTTPMiddleware`
3. Mantener `app.add_middleware(_MaxBodyMiddleware)` sin cambios
4. Escribir test unitario en `tests/test_unit_maxbody_middleware.py`

**Archivos de partida**: `api/app.py`
**Riesgo estimado**: bajo
**Tiempo estimado**: 1 hora

## Acceptance criteria

- [ ] `_MaxBodyMiddleware` no hereda de `BaseHTTPMiddleware`
- [ ] No hay acceso a `request._body` ni atributos privados de Starlette
- [ ] Content-Length fast-path sigue funcionando (413 para bodies > 1MB)
- [ ] Chunked requests sin Content-Length son rechazados si exceden 1MB
- [ ] Requests normales (< 1MB) pasan sin problemas
- [ ] `make lint && make typecheck && make test-unit` pasan en verde

## Notas de review

2026-05-24T00:00Z agent:reviewer — RFC aprobado. Cambio localizado, bajo riesgo, sin impacto en invariantes.
