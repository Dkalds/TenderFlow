---
id: ADR-012
title: "Plano único de orquestación por entorno + convergencia de entrypoints"
status: accepted
date: 2026-06-10
deciders: "Daniel Kalitovics"
related:
  - "[[ADR-004-sqlite-turso-vs-postgres]]"
  - "[[ADR-007-services-domain-layer]]"
  - "[[086-linaje-analitico-parquet-manifest]]"
tags: [adr]
---

# ADR-012 — Plano único de orquestación por entorno + convergencia de entrypoints

* **Estado:** Aceptado
* **Fecha:** 2026-06-10
* **Deciders:** Daniel Kalitovics
* **Relacionados:** [[ADR-004-sqlite-turso-vs-postgres|ADR-004]] (SQLite/Turso, supuesto single-writer), [[ADR-007-services-domain-layer|ADR-007]]
  (capa `services/`), [[086-linaje-analitico-parquet-manifest|RFC-086]] (linaje analítico — flaggeó el drift de `run_update.py`)

## Contexto

El proyecto programa trabajos batch (scraping, KPI, agregados, drift, backup,
retención, alertas) en dos planos de orquestación independientes sin
coordinación entre ellos:

* **Plano A — GitHub Actions cron** (`.github/workflows/`): `run_update.py`
* **Plano B — APScheduler** (`scheduler/loop.py`): bucle Docker con jobs registrados

### Problemas concretos

1. **Divergencia de código entre planos.** `run_update.py` (plano A) solo llamaba
   KPI precompute pero **no** aggregates precompute ni analytics export. `daily_atom`
   (plano B) sí ejecutaba la pipeline completa.

2. **Materializaciones stale en serverless.** En la topología recomendada (Opción A),
   `mat_clusters` y `mat_top_empresas_ccaa` nunca se refrescaban.

3. **Riesgo de doble disparo.** Ambos planos activos contra la misma BD: doble
   escritura y jobs no idempotentes (retención, retrain) en carrera.

## Decisión

1. **Un plano dueño por entorno, mutuamente excluyente.** Variable de entorno
   `SCHEDULER_PLANE` (`actions` | `docker`).

2. **Pipeline canónica en `scheduler/pipeline_runs.py`.** `run_daily_pipeline()`,
   `run_bulk_pipeline(months)` y `run_backfill_pipeline(year, month)` encapsulan
   la secuencia oficial. Ambos planos delegan en estas funciones.

3. **Tabla `job_locks` con TTL.** Lock liviano en SQLite para jobs no idempotentes.
   `acquire(name, ttl)` → False si hay lock vigente → job se vuelve no-op.

4. **Healthcheck reporta plano activo** y timestamp de última pipeline canónica.

## Archivos modificados

| Archivo | Cambio |
|---|---|
| `scheduler/pipeline_runs.py` | **Nuevo** — pipeline canónica |
| `scheduler/run_update.py` | Delega en `pipeline_runs` |
| `scheduler/jobs/daily_atom.py` | Delega en `pipeline_runs` |
| `scheduler/jobs/recent_bulk.py` | Delega en `pipeline_runs` |
| `services/job_locks.py` | **Nuevo** — acquire/release/is_held |
| `db/schema.py` | DDL tabla `job_locks` |
| `db/migrations.py` | Migración v34 |
| `db/alembic/versions/v34_job_locks.py` | **Nuevo** — migración Alembic |
| `scheduler/healthcheck.py` | Plano activo + última pipeline run + locks |

## Consecuencias

**Positivas:**
* Una sola definición de pipeline: imposible que un plano corra pasos que el otro omite.
* `mat_clusters` / `mat_top_empresas_ccaa` dejan de quedar stale en serverless.
* El doble disparo deja de corromper jobs no idempotentes.

**Negativas:**
* Nueva tabla `job_locks` → migración alembic append-only.
* Requiere documentar qué plano gobierna cada topología.
