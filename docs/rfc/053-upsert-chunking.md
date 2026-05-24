---
rfc: 053
title: Chunked upsert_licitaciones_with_history para liberar write lock
issue: https://github.com/Dkalds/Licitaciones_sap_SP/issues/53
author: agent:architect
date: 2026-05-24
status: approved
---

## Contexto

`upsert_licitaciones_with_history()` procesa todo el batch en una sola transacción SQLite. En backfills grandes (miles de licitaciones), esto mantiene el write lock durante toda la operación, bloqueando scheduler, dashboard y API.

## Decisión

Añadir chunking configurable al upsert:

1. Nuevo parámetro `chunk_size: int = 500` en `upsert_licitaciones_with_history()`.
2. Cada chunk se procesa en su propia transacción (`connect()` context manager).
3. Añadir método `merge()` a `UpsertResult` para acumular resultados parciales.
4. Añadir setting `UPSERT_CHUNK_SIZE: int = 500` en `config/settings.py` como default configurable.
5. El caller en `scraper/pipeline.py` pasa `chunk_size=settings.UPSERT_CHUNK_SIZE`.

**Qué NO se hace**: no se cambia la lógica interna del upsert por item, solo se divide el batch.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| WAL mode SQLite | Permite lecturas concurrentes | No resuelve write contention; ya está habilitado | No suficiente |
| Async upsert con queue | Desacopla completamente | Complejidad alta, cambio arquitectural | Overengineering para P2 |
| Sin cambio (status quo) | Cero riesgo | Bloqueo persiste | No resuelve el problema |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Toca config/ (strict) | Mantener typing strict en nuevo campo |
| §3.2 Upsert idempotente | Preservado — cada chunk es idempotente | Sin cambio en lógica de upsert |
| §3.3 Migraciones append-only | Ninguno | — |
| §3.4 Auto-marking tests | Ninguno | — |
| §3.5 Pydantic v2 DTOs | Ninguno | — |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. Añadir `UPSERT_CHUNK_SIZE: int = 500` a `config/settings.py` — `Settings` class
2. Añadir `merge()` a `UpsertResult` en `db/upsert.py`
3. Refactorizar `upsert_licitaciones_with_history()`: extraer lógica interna a `_upsert_chunk()`, iterar por chunks
4. Actualizar caller en `scraper/pipeline.py` para pasar `chunk_size=settings.UPSERT_CHUNK_SIZE`
5. Añadir test unitario para chunking (verificar que múltiples chunks producen resultado correcto)

**Archivos de partida**: `db/upsert.py`, `config/settings.py`, `scraper/pipeline.py`
**Riesgo estimado**: bajo
**Tiempo estimado**: 1 hora

## Acceptance criteria

- [x] `upsert_licitaciones_with_history()` acepta `chunk_size` parameter
- [x] Batches > chunk_size se dividen en transacciones separadas
- [x] `UpsertResult.merge()` acumula resultados correctamente
- [x] Tests existentes siguen pasando
- [x] Nuevo test verifica chunking con batch > chunk_size
- [x] `make lint && make typecheck && make test-unit` pasan en verde

## Notas de review

2026-05-24T00:00Z agent:reviewer — RFC aprobado. Cambio de bajo riesgo, preserva idempotencia. El chunking parcial (chunks anteriores persisten si uno falla) es un beneficio aceptable documentado en el issue.
