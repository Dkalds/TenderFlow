---
rfc: 058
title: Añadir rate limiting al endpoint /api/v1/ask (LLM)
issue: https://github.com/Dkalds/Licitaciones_sap_SP/issues/58
author: agent:architect
date: 2026-05-24
status: approved
---

## Contexto

El endpoint `/api/v1/ask` dispara llamadas a APIs LLM (OpenAI, Anthropic) que son costosas. Actualmente no está incluido en `_HEAVY_ENDPOINT_LIMITS` y usa el límite global de 120 req/min, lo que permite abuso económico y agotamiento de rate limits del proveedor.

## Decisión

Añadir `/api/v1/ask` a `_HEAVY_ENDPOINT_LIMITS` con un límite de 10 req/min (la ventana de 60s ya es la default del middleware). También añadir `/api/v1/ask/models` con 30 req/min (es solo lectura pero no necesita ser ilimitado).

No se implementa rate limiting por `key_hash` individual ni estimación de coste por request en este RFC (scope futuro).

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Middleware dedicado para LLM | Más granular | Over-engineering para un cambio de 1 línea | Complejidad innecesaria |
| Rate limit por key_hash + IP | Más justo multi-tenant | Requiere refactor del middleware | Scope futuro, no bloquea este fix |
| Límite de 5 req/min | Más conservador | Puede afectar uso legítimo | 10 es razonable para empezar |

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

1. Añadir entradas a `_HEAVY_ENDPOINT_LIMITS` en `api/middleware.py` (línea ~160)
2. Añadir test unitario en `tests/test_middleware.py` verificando que el límite se aplica

**Archivos de partida**: `api/middleware.py`
**Riesgo estimado**: bajo
**Tiempo estimado**: <1 hora

## Acceptance criteria

- [x] `/api/v1/ask` tiene rate limit de 10 req/min en `_HEAVY_ENDPOINT_LIMITS`
- [x] Test unitario verifica que el endpoint usa el límite reducido
- [x] `make lint && make typecheck && make test-unit` pasan en verde

## Notas de review

2026-05-24T00:00Z agent:reviewer — Cambio mínimo, no afecta invariantes. Aprobado.
