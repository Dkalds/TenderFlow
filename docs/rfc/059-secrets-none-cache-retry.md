---
rfc: 059
title: "No cachear valores None en config/secrets.py"
issue: https://github.com/Dkalds/Licitaciones_sap_SP/issues/59
author: agent:architect
date: 2026-05-24
status: implemented
---

## Contexto

`config/secrets.py` cachea permanentemente el resultado de `get_secret()`, incluyendo `None`. Si un backend externo (Azure KV, AWS SM) falla transitoriamente durante startup, el secreto queda como `None` para toda la vida del proceso sin posibilidad de reintento automático.

## Decisión

Opción A (simple): **No cachear valores `None`**. Solo cachear cuando `result is not None`. Esto permite reintentos naturales en llamadas subsecuentes sin añadir complejidad de TTL.

No se implementa TTL (Opción B del issue) porque añade complejidad innecesaria: si el resultado es `None`, simplemente no se cachea y la próxima llamada reintenta.

Se añade logging cuando se omite el cache para observabilidad.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Cache con TTL para None | Control fino del reintento | Complejidad: timestamps, config TTL, cambio de tipo en _cache | Over-engineering para el caso de uso |
| No cachear nada | Máxima frescura | Llamadas repetidas al backend externo, latencia | Rompe el propósito del cache |
| Opción A: no cachear None | Simple, zero-config, retry natural | Llamadas repetidas si el secreto realmente no existe | Aceptable: secretos inexistentes son error de config |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | config/ es strict — mantener | Sin cambios de tipos |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno | — |
| §3.4 Auto-marking tests | Ninguno | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. `config/secrets.py`: en `get_secret()`, solo cachear si `result is not None`. Añadir log.debug cuando se omite cache.
2. `tests/test_config_secrets.py`: añadir test que verifica que None no se cachea y un reintento funciona.

**Archivos de partida**: `config/secrets.py`, `tests/test_config_secrets.py`
**Riesgo estimado**: bajo
**Tiempo estimado**: <1 hora

## Acceptance criteria

- [x] `get_secret()` no cachea `None` — llamadas subsecuentes reintentan el backend
- [x] Valores no-None siguen cacheados normalmente
- [x] Test unitario cubre el escenario de reintento tras None
- [x] `make lint && make typecheck && make test-unit` pasan en verde
