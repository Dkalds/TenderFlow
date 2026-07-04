---
rfc: 086
title: Linaje analítico canónico — manifest Parquet y orden de materialización
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-09
status: implemented
---

## Contexto

Hoy coexisten cuatro materializaciones derivadas de los datos operacionales:

1. **`kpi_snapshots`** (SQLite) — escrita por `scheduler/kpi_precompute.py` con SQL
   puro sobre SQLite. Ruta viva, llamada desde `scheduler/jobs/daily_atom.py::run()`
   y `scheduler/jobs/recent_bulk.py::run()`.
2. **`mat_clusters` / `mat_top_empresas_ccaa`** (SQLite) — escritas por
   `scheduler/aggregates_precompute.py` (KMeans sobre embeddings + ranking SQL).
   Consumidas por `dashboard/data_loader.py` y `dashboard/clustering.py`.
3. **Export Parquet** (`db/analytics.py::export_parquet`) — **ruta dormida**: solo
   se ejecuta vía `python -m scheduler.kpi_precompute --export-parquet`. Ningún
   job del scheduler la llama.
4. **Attach DuckDB** (`services/analytics_engine.py`) — ataca SQLite en memoria,
   se invalida con `shared/cache_signal.py`.

Problemas detectados:

- `analytics_engine.maybe_refresh()` se invalida con `cache_signal`, que significa
  "hubo ingesta", **no** "la materialización analítica terminó". Existe una ventana
  donde el engine se refresca contra datos a medio materializar.
- No hay registro de *cuándo* y *desde qué estado* se generó cada materialización:
  un consumidor no puede saber si el Parquet (cuando exista) está fresco.
- `scheduler/run_update.py` es un tercer entrypoint de orquestación que solo llama
  `kpi_precompute` best-effort (sin aggregates): ya drifteó respecto a
  `scheduler/jobs/*`.

Escala actual: cientos de licitaciones en BD (backfill 2026-04: "Total en BD: 311").
Esto descarta particionado/incremental y justifica mantener SQLite-directo como
ruta primaria de cálculo. Relacionado: [[ADR-004-sqlite-turso-vs-postgres|ADR-004]] (SQLite/Turso), [[0011-cdc-debezium|ADR-0011]] (no-CDC).

## Decisión

Establecer un **modelo de linaje analítico explícito**:

- **SQLite** = OLTP **+ materializaciones ML-derived** (`mat_clusters`,
  `mat_top_empresas_ccaa`, `kpi_snapshots`). Estas tablas se quedan.
- **Parquet** = snapshot de hechos analíticos crudos (`licitaciones`,
  `adjudicaciones`) + **manifest**.
- **DuckDB sobre Parquet** = fuente para `analytics_engine` y para
  `kpi_snapshots` *cuando el engine duckdb-parquet está disponible*.

Cambios concretos:

1. **Manifest** `DATA_DIR/parquet/_manifest.json` escrito atómicamente
   (write-temp + rename) al final de cada export. Contenido mínimo:
   `{generated_at, engine: "duckdb-parquet" | "sqlite-direct", row_counts: {tabla: n}, source_db_mtime}`.
2. **Cablear el export al pipeline** (net-new, no reorden): en
   `scheduler/jobs/daily_atom.py::run()` y `scheduler/jobs/recent_bulk.py::run()`,
   insertar `export Parquet → write manifest` **entre** la ingesta y
   `run_kpi_precompute()`. Si DuckDB no está instalado, el paso escribe el
   manifest con `engine: "sqlite-direct"` y row_counts leídos de SQLite — no
   falla.
3. **Invariante de linaje, no de motor**: `kpi_snapshots` se calcula siempre
   *después* del manifest del mismo run. SQLite-directo es la ruta **primaria**
   de cálculo a esta escala; DuckDB-sobre-Parquet es la alternativa cuando el
   extra está instalado. Nunca puede existir un snapshot KPI más nuevo que el
   manifest del que deriva.
4. **`analytics_engine.maybe_refresh()` migra de `cache_signal` al manifest**:
   se refresca cuando `generated_at` del manifest avanza. `cache_signal` se
   mantiene sin cambios para las cachés OLTP del dashboard (roles distintos:
   "hubo ingesta" vs "materialización lista").
5. **Banner de frescura**: el dashboard muestra `generated_at` del manifest en
   las vistas analíticas.
6. **Tripwire de granularidad** (en vez de implementar incremental): si el
   export full supera 30 s o el archivo supera ~100 MB, se abre RFC de
   particionado mensual. Hasta entonces, re-export completo con zstd.

**Qué NO se hace:**

- **No** se toca `aggregates_precompute.py`: `mat_clusters` no puede derivar de
  Parquet (embeddings + KMeans), y mover solo `mat_top_empresas_ccaa` partiría el
  módulo en dos motores sin ganancia de consistencia (dentro de un run secuencial,
  SQLite y el Parquet recién exportado son idénticos por construcción). Solo se
  exige orden post-ingesta, que ya se cumple.
- **No** se retiran las tablas KPI de SQLite ni se implementa
  incremental/particionado.
- **No** se arregla `scheduler/run_update.py` aquí — se **flaggea**: queda
  drifteado (sin aggregates ni export) y debe deprecarse o delegar en los jobs
  de `scheduler/jobs/*` en un ítem separado del backlog. Sin ese ítem, este RFC
  crearía un cuarto camino inconsistente.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Parquet+DuckDB obligatorio para KPI | Un solo motor analítico | Dependencia pesada para 7 agregados sobre cientos de filas; rompe entornos sin extra `[fast]` | Invierte costo/beneficio a esta escala |
| Export incremental/particionado por mes | Escala a millones de filas | Complejidad de compactación y backfill | Dataset actual ~10³ filas; tripwire definido en su lugar |
| Mover aggregates_precompute a DuckDB/Parquet | Linaje uniforme | `mat_clusters` no puede; partiría el módulo en dos motores | Sin ganancia de consistencia intra-run |
| Reemplazar cache_signal por el manifest en todo | Una sola señal | Las cachés OLTP necesitan invalidarse en ingesta, antes de materializar | Roles distintos; convivencia deliberada |
| Status quo (export dormido) | Cero riesgo | `maybe_refresh` sigue colgado de la señal equivocada; sin trazabilidad de frescura | No resuelve la ventana de inconsistencia |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Toca `shared/` (helper manifest) y `config/` (setting de path) — strict | Tipar estricto desde el inicio |
| §3.2 Upsert idempotente | Preservado — export y manifest son re-ejecutables (overwrite atómico) | Write-temp + rename |
| §3.3 Migraciones append-only | Ninguno — sin cambios de schema | — |
| §3.4 Auto-marking tests | Ninguno — tests nuevos siguen convención de nombre | — |
| §3.5 Pydantic v2 DTOs | Ninguno (manifest es contrato interno scheduler↔dashboard, no API) | Documentar formato en este RFC |
| §3.6 HMAC/argon2 auth | Ninguno | — |

## Plan de implementación

1. `shared/parquet_manifest.py` — `write_manifest()` / `read_manifest()` tipados
   strict, escritura atómica. Tests unitarios.
2. `db/analytics.py` — `run_analytics_export()`: exporta `licitaciones` y
   `adjudicaciones` a `DATA_DIR/parquet/` si hay DuckDB; en ambos casos escribe
   manifest con el engine correspondiente.
3. `scheduler/jobs/daily_atom.py::run()` y `scheduler/jobs/recent_bulk.py::run()`
   — insertar `run_analytics_export()` entre la ingesta y `run_kpi_precompute()`.
4. `services/analytics_engine.py` — `maybe_refresh()` lee `generated_at` del
   manifest en lugar de `cache_signal`.
5. `dashboard/` — banner "datos analíticos a las HH:MM" desde el manifest.
6. `docs/IMPROVEMENT_BACKLOG.md` — ítem nuevo: deprecar/realinear
   `scheduler/run_update.py` con los jobs de `scheduler/jobs/*`.
7. Tests: orden del pipeline (export antes de KPI), manifest con ambos engines,
   refresh del analytics_engine gobernado por manifest.

**Archivos de partida**: `scheduler/jobs/daily_atom.py`,
`scheduler/jobs/recent_bulk.py`, `scheduler/kpi_precompute.py`,
`db/analytics.py`, `services/analytics_engine.py`, `shared/cache_signal.py`
(solo lectura, no cambia), `dashboard/data_loader.py`.
**Riesgo estimado**: bajo (aditivo; ningún consumidor existente cambia de fuente
salvo `maybe_refresh`).
**Tiempo estimado**: 1–2 días.
