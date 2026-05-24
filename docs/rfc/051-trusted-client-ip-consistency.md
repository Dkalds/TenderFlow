---
rfc: 051
title: Uso consistente de _trusted_client_ip para prevenir IP spoofing
issue: https://github.com/Dkalds/Licitaciones_sap_SP/issues/51
author: agent:architect
date: 2026-05-24
status: approved
---

## Contexto

`RateLimitMiddleware` usa `_trusted_client_ip()` para validar `X-Forwarded-For` contra proxies confiables. Sin embargo, tres puntos leen el header directamente sin validación:

1. `api/middleware.py:325-327` — `AccessLogMiddleware`
2. `api/routes/security.py:44-46` — CSP report endpoint
3. `api/app.py:341-343` — `/metrics` endpoint

Esto permite IP spoofing en logs, métricas y rate limiting del CSP endpoint.

## Decisión

Reemplazar las 3 lecturas directas de `X-Forwarded-For` por llamadas a `_trusted_client_ip(request)`. La función ya existe y está probada en `api/middleware.py`.

Para `api/routes/security.py` y `api/app.py`, importar `_trusted_client_ip` desde `api.middleware`.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Crear middleware global que inyecte `request.state.client_ip` | Centralizado | Over-engineering para 3 puntos | Complejidad innecesaria |
| Mover `_trusted_client_ip` a `shared/` | Mejor ubicación | Cambio más amplio, no urgente | Scope creep para un fix de seguridad |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Ninguno — función ya tipada | — |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno | — |
| §3.4 Auto-marking tests | Ninguno | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. `api/middleware.py:325-327` — reemplazar lectura directa por `_trusted_client_ip(request)`
2. `api/routes/security.py:44-46` — importar y usar `_trusted_client_ip`
3. `api/app.py:341-343` — importar y usar `_trusted_client_ip`

**Archivos de partida**: `api/middleware.py`, `api/routes/security.py`, `api/app.py`
**Riesgo estimado**: bajo
**Tiempo estimado**: 1 hora

## Acceptance criteria

- [ ] Los 3 puntos usan `_trusted_client_ip(request)` en lugar de lectura directa
- [ ] Tests unitarios verifican que IP spoofing no funciona en los 3 puntos
- [ ] `make lint && make typecheck && make test-unit` pasan en verde

## Notas de review

2026-05-24T00:00Z agent:reviewer — RFC aprobado. Cambio mínimo, bajo riesgo, no toca invariantes. La función `_trusted_client_ip` es privada (prefijo `_`) pero su uso intra-paquete `api/` es aceptable.
