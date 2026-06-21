---
rfc: 052
title: Alinear reset_timeout inicial del CircuitBreaker con BREAKER_BASE_TIMEOUT
issue: https://github.com/Dkalds/Licitaciones_sap_SP/issues/52
author: agent:architect
date: 2026-05-24
status: implemented
---

## Contexto

El `CircuitBreaker` en `scraper/resilience.py:125` se construye con `reset_timeout=60*5` (300s), pero el `_AdaptiveBackoffListener` sobreescribe este valor a `settings.BREAKER_BASE_TIMEOUT` (default 60s) en el primer `state_change` a "open" o "closed". El valor inicial de 300s es código muerto que confunde a los mantenedores.

## Decisión

Reemplazar el literal `60 * 5` por `settings.BREAKER_BASE_TIMEOUT` en el constructor de `placsp_breaker`. Esto alinea el valor inicial con lo que el listener usa, eliminando el código muerto sin cambiar el comportamiento en runtime (el listener ya sobreescribía el valor).

Añadir un test que verifique que `placsp_breaker.reset_timeout == settings.BREAKER_BASE_TIMEOUT` al importar.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Eliminar `reset_timeout` del constructor (usar default de pybreaker) | Menos código | Default de pybreaker (30s) difiere de BREAKER_BASE_TIMEOUT (60s); ventana de inconsistencia antes del primer state_change | Introduce inconsistencia temporal |
| Mantener 300s y documentar que es ignorado | Zero-change | Sigue siendo confuso | No resuelve el problema |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Ninguno — scraper/ no es strict | — |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno | — |
| §3.4 Auto-marking tests | Ninguno — test se nombra correctamente | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. `scraper/resilience.py` línea 127: cambiar `reset_timeout=60 * 5` → `reset_timeout=settings.BREAKER_BASE_TIMEOUT`
2. `tests/test_resilience.py`: añadir test que verifica `placsp_breaker.reset_timeout == settings.BREAKER_BASE_TIMEOUT`

**Archivos de partida**: `scraper/resilience.py`, `tests/test_resilience.py`
**Riesgo estimado**: bajo
**Tiempo estimado**: <1 hora

## Acceptance criteria

- [x] `placsp_breaker` se construye con `reset_timeout=settings.BREAKER_BASE_TIMEOUT`
- [x] Test verifica alineación del valor inicial
- [x] `make lint && make typecheck && make test-unit` pasan en verde

## Notas de review

2026-05-24T00:00Z agent:reviewer — Cambio trivial, bajo riesgo. No afecta invariantes. Aprobado.
