---
id: ADR-017
title: "Camino de lectura analítico tras el cutover a Postgres"
status: accepted
date: 2026-07-26
deciders: "Daniel Kalitovics"
supersedes: ADR-013
related:
  - "[[ADR-012-plano-unico-orquestacion]]"
  - "[[ADR-016-destino-persistencia-supabase]]"
tags: [adr, analytics, materializations]
---

# ADR-017 — Camino de lectura analítico tras el cutover a Postgres

* **Estado:** Aceptado
* **Fecha:** 2026-07-26
* **Sustituye a:** [[ADR-013-jerarquia-materializaciones-analiticas|ADR-013]]

## Contexto

ADR-013 fijó una jerarquía de materializaciones analíticas sobre tres premisas
que hoy son falsas:

1. **"SQLite = fuente OLTP".** El backend de producción es Supabase Postgres
   desde el cutover F3c ([[ADR-016-destino-persistencia-supabase|ADR-016]]).
2. **"El dashboard lee de `kpi_snapshots` y `mat_*`".** El paquete `dashboard/`
   (Streamlit) ya no existe — se retiró al adoptar FastAPI + Next.js
   ([[ADR-002-streamlit-vs-fastapi-react|ADR-002]]). Sus reglas de lectura no
   aplican a ningún consumidor actual.
3. **"Tres materializaciones con un solo punto de refresh".** De las tres,
   solo una tenía lector real.

El resultado era una ADR que describía un sistema inexistente, con la
consecuencia práctica de que se seguía computando trabajo que nadie consumía.

## Estado real medido (2026-07-26)

| Materialización | Escritor | Lector real |
|---|---|---|
| `mat_clusters` | `aggregates_precompute` | `services/clustering_engine.py` ✅ |
| `kpi_snapshots` | `kpi_precompute` | `scheduler/healthcheck.py` (marca temporal de la última pipeline) ✅ |
| `mat_top_empresas_ccaa` | `aggregates_precompute` | **ninguno** ❌ |

## Decisión

### Camino de lectura canónico

```
Supabase Postgres (OLTP)
  ├─[pipeline canónica, ADR-012]─> mat_clusters ──> services/clustering_engine
  │                              └> kpi_snapshots ─> scheduler/healthcheck
  └─[consulta en vivo]──────────> services/analytics/* ──> api/ ──> web/
```

1. **El camino por defecto de `/analytics` es cómputo en vivo + caché de
   respuesta** (`shared/cache.py`, TTL 120–1800 s según endpoint). No hay
   materialización intermedia y no debe añadirse una sin medir antes que el
   cómputo en vivo es el cuello de botella.

2. **Una materialización solo se justifica con un consumidor declarado.** Si
   una tabla `mat_*` o de snapshots deja de tener lector, se elimina — no se
   conserva "por si acaso". Una copia derivada sin consumidor es coste
   recurrente y una fuente de verdad que puede divergir en silencio.

3. **`mat_top_empresas_ccaa` se elimina** (migración
   `v58_drop_mat_top_empresas_ccaa`). Se recomputaba entera cada 4h sin
   lectores.

4. **Parquet sigue siendo el snapshot offline canónico** para consumidores
   externos (`run_analytics_export`, RFC-086). Sin cambios respecto a ADR-013.

## Consecuencias

**Positivas:**
- Dos pasos menos de cómputo por cada pasada de la pipeline (cada 4h).
- Una fuente derivada menos que puede divergir.
- La regla "materialización ⇒ consumidor declarado" es verificable: basta
  buscar el lector.

**Negativas:**
- `kpi_snapshots` sigue computando el conjunto completo de métricas cuando su
  único consumidor lee un `MAX(computed_at)`. Es coste conocido y aceptado por
  ahora: sustituirlo exige cambiar la señal de frescura del healthcheck, que es
  el único SLI que hoy se mide de verdad en producción, y no se toca sin tener
  antes la observabilidad de la Fase 6 en pie.
- Si `/analytics` crece en volumen, habrá que revisar la decisión 1. El
  disparador es una medición, no una intuición.
