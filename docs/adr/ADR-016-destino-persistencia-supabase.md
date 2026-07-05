---
id: ADR-016
title: "Destino de persistencia: Supabase + psycopg3"
status: accepted
date: 2026-07-05
deciders: "Daniel Kalitovics"
supersedes: ADR-004
tags: [adr, persistence, postgres, supabase]
---

# ADR-016: Destino de persistencia — Supabase + psycopg3

**Status:** Accepted
**Date:** 2026-07-05
**Supersedes:** ADR-004 (SQLite + Turso vs PostgreSQL)

## Contexto

ADR-004 eligió SQLite/Turso bajo la premisa explícita de **un solo writer**. Esa
premisa ya no se cumple: scraper pipeline, scheduler (KPI/aggregates/drift),
dashboard API y el sistema multi-agente escriben concurrentemente. El propio ADR-004
lo reconoce en su bloque de "Migration Tripwires" (añadido 2026-06-10):

> *"The original 'single writer' assumption from ADR-004 no longer holds; these
> tripwires provide a proactive migration signal instead of reacting to incidents."*

La decisión de migrar se tomó el 2026-07-05 sin esperar a que saltaran los tripwires,
como prescribe el RFC pre-cocido (2026-06-30, ahora superseded por este ADR).

## Decisión

Migrar a **Supabase** (PostgreSQL 16 gestionado) con **psycopg3** (`psycopg`) como
driver y `psycopg_pool` para el connection pool.

## Justificación del destino

| Criterio | Supabase | Neon | RDS Aurora Serverless |
|---|---|---|---|
| IPv4 en GH Actions | Supavisor session pooler :5432 | Sí | Sí |
| FTS nativo | `pg_trgm` + `tsvector` | Sí | Sí |
| Plan inicial | Pro ~8.5 GB | Free tier limitado | Costoso |
| Backup automático | Sí | Parcial (free) | Sí |
| Esfuerzo devops | Bajo (managed) | Bajo | Alto |

Supabase ganó por: IPv4 garantizado vía Supavisor, plan Pro adecuado al tamaño
actual, backup automático y stack conocido (Postgres 16).

## Parámetros de conexión

- **Endpoint:** Supavisor en modo **session** (`puerto 5432`)
  - Session mode evita colisiones con `PREPARE` (problema de transaction pooler).
  - GH Actions es IPv4-only → Supavisor siempre accesible.
- **Pool:** `psycopg_pool.ConnectionPool` (reemplaza el pool casero de `db/connection.py`).
- **DATABASE_URL:** variable de entorno con precedencia sobre `TURSO_*` y SQLite local.
  Formato: `postgresql://user:pass@host:5432/db?sslmode=require`

## Estrategia de FTS

SQLite usaba FTS5 (tabla virtual `licitaciones_fts` + triggers). PostgreSQL usa:

- **Columna generada:** `search_vector tsvector GENERATED ALWAYS AS (...) STORED`
  con configuración `'spanish'` (inmune a inyección, no requiere triggers).
- **Índice GIN** sobre `search_vector` (consultas `@@` eficientes).
- **pg_trgm** habilitado para similitud LIKE fallback.
- **`websearch_to_tsquery('spanish', query)`** — sintaxis Google-like, inmune a
  inyección (sustituye a `escape_fts5` del módulo legacy).

La abstracción `db/search_backend.py` (protocolo `SearchBackend`) permite al código
llamador operar sin conocer el backend actual.

## Shim de paramstyle

El código existente usa `?` (qmark/libsql). psycopg3 usa `%s`. En lugar de migrar
los 113 call-sites para el cutover, `db/connection.py` aporta un shim
`_translate_qmarks(sql)` que reescribe `?` → `%s` respetando strings literales y
comentarios. El shim se activa automáticamente cuando `DATABASE_URL` apunta a
Postgres. F5 (refactor de repositories) convertirá los sitios a `%s` nativo y
eliminará la presión del shim.

## Estrategia de migración

Ver `docs/runbooks/migracion-persistencia.md` (creado en F3c).

Fases:
- **F3a** (esta fase): ADR-016 + deps psycopg3 + `db/connection.py` shim +
  `db/search_backend.py` + migración alembic `v50_pg_search_infra`.
- **F3b**: ETL `scripts/migrate_sqlite_to_pg.py` + `scripts/verify_pg_parity.py` +
  ensayo de búsqueda.
- **F3c**: Cutover — ventana read-only corta, sin dual-write. Runbook completo.
- **F3d**: Post-cutover — backup con `pg_dump`, retirada de Turso.

## Consecuencias

**Positivas:**
- Elimina la premisa rota de single-writer (ADR-004).
- FTS nativa sin triggers frágiles ni tablas virtuales FTS5.
- Pool gestionado sin código casero.
- Backup con `pg_dump -Fc` (restore atómica, verificable).
- Prepara el camino para RLS y Row Level Security si se necesita en el futuro.

**Negativas / Riesgos:**
- El shim qmark añade un paso de traducción en cada query durante F3a-F5.
  Mitigación: unit tests exhaustivos del shim + suite integration-pg.
- Búsqueda percibida diferente (bm25 FTS5 ≠ ts_rank_cd). Mitigación: gate de
  paridad de búsqueda en F3b (Jaccard top-10 ≥ 0.6).
- GROUP BY laxo de SQLite no permitido en Postgres. Mitigación: job CI
  `integration-pg` (desde F3a) lo detecta inmediatamente.
- Coste Supabase Pro: ~$25/mes para el plan inicial.

## ADR-004 → Superseded

ADR-004 queda superseded por este ADR al completar la fase F3c (cutover).
Hasta entonces, el sistema opera en modo dual-config: SQLite cuando `DATABASE_URL`
no está definida, Postgres cuando sí lo está.
