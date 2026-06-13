# ADR-013 — Jerarquía de materializaciones analíticas

* **Estado:** Aceptado
* **Fecha:** 2026-06-10
* **Deciders:** Daniel Kalitovics
* **Relacionados:** ADR-004 (SQLite/Turso), ADR-012 (pipeline canónica)

## Contexto

Coexisten tres mecanismos de materialización analítica sin jerarquía definida:

| Materialización | Motor | Refresh | Consumidores |
|---|---|---|---|
| KPI snapshots (`kpi_snapshots`) | SQLite directo | Pipeline canónica (ADR-012) | `dashboard/kpi_bar.py` |
| Aggregates (`mat_clusters`, `mat_top_empresas_ccaa`) | SQLite directo | Pipeline canónica | `dashboard/clustering.py`, `dashboard/data_loader.py` |
| DuckDB analytics export | DuckDB ATTACH + Parquet | Opcional (`--export-parquet`) | Análisis offline |

Tres copias derivadas de la misma verdad, cada una con su propio refresh, crean
el riesgo de "el dashboard dice X y el export dice Y".

## Decisión

### Camino canónico de lectura

```
SQLite (OLTP) ──[pipeline canónica]──> KPI snapshots (SQLite, caché con refresh)
                                    ──> mat_clusters / mat_top_empresas_ccaa (SQLite)
                                    ──> Parquet + manifest (RFC-086, snapshot offline)
```

1. **SQLite = fuente OLTP + cache analítica ligera.** `kpi_snapshots` y
   `mat_*` son **caché materializada** con TTL implícito (se refrescan en cada
   pipeline run). El dashboard lee de estas tablas, no de SQL ad-hoc sobre
   `licitaciones`.

2. **Parquet = snapshot offline canónico.** Producido por `run_analytics_export()`
   en la pipeline canónica. Es la única salida para análisis fuera del sistema
   (notebooks, BI tools). El manifest de linaje (RFC-086) documenta qué datos
   contiene y cuándo se generó.

3. **DuckDB = motor opcional para exports Parquet pesados.** No es un read path
   del dashboard. Solo se usa como motor de `run_analytics_export()` cuando
   `duckdb` está instalado; si no, el export usa pandas como fallback.

### Reglas

- El dashboard **nunca** lee DuckDB ni Parquet directamente. Lee de
  `kpi_snapshots` y `mat_*` (via `services/` per §3.8).
- Un consumidor externo lee de Parquet. Nunca de `kpi_snapshots` SQLite.
- El único job que materializa es la pipeline canónica (ADR-012). No hay
  materialización fuera de `_run_post_ingestion_steps()`.

## Consecuencias

**Positivas:**
- Un solo punto de materialización (pipeline canónica) elimina inconsistencias.
- El linaje queda trazable: pipeline → snapshots/mat_* → dashboard,
  pipeline → Parquet → consumidores externos.
- DuckDB sigue siendo opcional; no agregar dependencia obligatoria.

**Negativas:**
- Las tablas KPI en SQLite son caché, no fuente de verdad. Si se corrompen,
  la siguiente pipeline run las regenera.
- El export Parquet es best-effort (no aborta la pipeline si falla). En caso
  de fallo, los consumidores externos ven datos stale hasta la siguiente run.
