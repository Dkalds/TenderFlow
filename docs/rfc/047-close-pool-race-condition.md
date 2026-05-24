---
rfc: 047
title: "Fix race condition en close_pool() — lock durante drain del pool"
issue: https://github.com/Dkalds/Licitaciones_sap_SP/issues/47
author: agent:architect
date: 2026-05-24
status: approved
---

## Contexto

`close_pool()` en `db/connection.py:276-296` verifica `_pool is not None` y drena el pool sin mantener `_pool_lock`. Otro hilo puede llamar `_get_conn()` concurrentemente, creando conexiones que nunca se cierran (leak) o usando conexiones ya cerradas (`OperationalError`).

## Decisión

1. Adquirir `_pool_lock` para atomizar la lectura y el nulleo de `_pool`.
2. Dentro del lock: capturar referencia local al pool, setear `_pool = None` y `_pool_active = 0`.
3. Fuera del lock: drenar el pool capturado (evita deadlock con `_return_conn`).
4. En `_return_conn`: verificar `_pool is not None` bajo lock antes de `put_nowait`.

Esto sigue el patrón propuesto en el issue: swap-then-drain.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Lock durante todo el drain | Simple | Deadlock si conn.close() tarda | Riesgo de hang |
| RLock en vez de Lock | Permite reentrada | Oculta bugs de diseño | Innecesario |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | `db/connection.py` no es strict pero `db/database.py` sí (fachada) | Sin cambio en fachada |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno | — |
| §3.4 Auto-marking tests | Ninguno | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. Modificar `close_pool()` en `db/connection.py`: swap-then-drain con `_pool_lock`
2. Modificar `_return_conn()`: check `_pool is not None` defensivamente (ya lo hace, pero reforzar)
3. Añadir test unitario `test_close_pool_concurrent_get_conn` en `tests/test_db_connection.py`

**Archivos de partida**: `db/connection.py`
**Riesgo estimado**: bajo
**Tiempo estimado**: 1 hora

## Acceptance criteria

- [x] `close_pool()` adquiere `_pool_lock` antes de leer/nullear `_pool`
- [x] Drain ocurre fuera del lock (sin deadlock)
- [x] Test unitario verifica que close_pool + concurrent _get_conn no leakea
- [x] `make lint && make typecheck && make test-unit` pasan en verde
