---
rfc: pendiente
title: "UX/KPIs · Clusters — guía de calidad para elegir K e interpretabilidad de clusters"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: draft
area: web/clusters
---

## Contexto

`web/src/app/(dashboard)/clusters/page.tsx` está bien construida: clustering
server-side (`/api/v1/analytics/clusters?n_clusters=K&auto_k=...`), slider de K,
toggle auto-K, barras de tamaño por cluster, box-plots de importe por cluster
(cuartiles del backend) y detalle de items. La mecánica es sólida.

El gap es de **UX de ML**, no de implementación:

1. **Se elige K a ciegas.** El slider deja fijar K (o auto-K), pero no hay ninguna
   **métrica de calidad** (silhouette, inercia/elbow) que indique si ese K produce
   clusters bien separados. El usuario mueve el slider sin saber qué K es razonable.
2. **Interpretabilidad limitada.** Cada cluster tiene un `label` truncado, pero no
   se explica **qué lo caracteriza** (términos top, CPV/órgano/CCAA dominantes). Un
   cluster sin "tarjeta de identidad" es difícil de accionar.
3. **Sin puente al listado.** Los items del cluster no enlazan al listado principal
   filtrado por ese conjunto.

> Clustering ya se calcula en backend (`services/clusters.py`/`clustering_engine.py`,
> `mat_clusters`). Exponer silhouette/centroides es aditivo (§3.5); consumo vía API
> (§3.8).

## Decisión

1. **Métrica de calidad para elegir K.** Exponer y mostrar silhouette (o inercia
   con curva elbow) por K; al mover el slider, indicar la calidad y/o sugerir el K
   "codo". Auto-K muestra qué optimizó.
2. **Tarjeta de identidad por cluster.** Por cluster: términos/keywords top, CPV y
   órgano dominantes, rango de importe (ya hay box-plot) — para que el `label` sea
   interpretable.
3. **Bridge al listado.** "Ver en listado" por cluster → listado filtrado por sus
   ids/criterio.

**Qué NO se hace:**

- **No** se cambia el algoritmo de clustering (es backend/otro RFC); aquí se
  **expone** calidad e identidad.
- **No** se añade clustering jerárquico ni 2D-embedding scatter (posible follow-up).

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo | Cero trabajo | K a ciegas; clusters opacos | UX de ML pobre |
| Solo silhouette | Guía la elección de K | Clusters siguen opacos | Medio camino |
| Calidad + identidad + bridge (elegida) | K informado y clusters accionables | Campos backend nuevos | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Tipos generados (silhouette, términos top) | Regenerar OpenAPI; tipar |
| §3.5 Pydantic v2 DTOs | **Aditivo** en el DTO de clusters | Cambio consciente |
| §3.8 Frontend vía API | Cálculo en `services/clusters.py` | — |
| §3.2 / §3.3 / §3.4 / §3.6 | Ninguno | — |

## Plan de implementación

1. `services/clusters.py`/`clustering_engine.py` + `api/routes/analytics.py` —
   exponer silhouette (o inercia por K) y descriptores por cluster (términos/CPV/
   órgano dominantes).
2. `clusters/page.tsx` — indicador de calidad junto al slider; tarjeta de identidad;
   bridge al listado.
3. Regenerar `@/generated/api`.
4. Tests: la calidad cambia con K; la tarjeta muestra descriptores; el bridge filtra.

**Archivos de partida**: `clusters/page.tsx:61-115`, `services/clusters.py`,
`services/clustering_engine.py`, `api/routes/analytics.py`.
**Riesgo estimado**: bajo-medio. Silhouette por K puede ser costoso; cachear.
**Tiempo estimado**: 1-1.5 días.

## Acceptance criteria

- [ ] Al elegir K se muestra una métrica de calidad (silhouette/inercia) y/o sugerencia de K.
- [ ] Cada cluster muestra descriptores interpretables (términos/CPV/órgano dominantes).
- [ ] Hay bridge del cluster al listado filtrado.
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend) en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

2026-06-24 — **Implementado.** Backend (`services/analytics/clusters.py`):
`ClustersResult` gana `silhouette` (calidad de la partición, calculada sobre los
labels finales con `sample_size` acotado; el `silhouette_score` ya se usaba en
`_optimal_k` pero no se exponía); `ClusterEntry` gana `cpv_dominante` (con
`cpv_label`) y `organo_dominante` (moda por cluster) → tarjeta de identidad. El
endpoint `/api/v1/analytics/clusters` ya existía. Frontend: nueva KPI "Calidad
(silhouette)" con interpretación (buena/moderada/débil) que guía la elección de K;
columnas "CPV dominante"/"Órgano dominante" en la tabla resumen. Tests: aserciones
de silhouette + descriptores en `test_clusters_shape_and_labels`. Verde:
pytest/mypy/ruff/codespell + `tsc`/`eslint`/`vitest` (285). **Diferido:** bridge del
cluster al listado principal filtrado (drill-down ya existe in-page con la tabla de
items; falta el enlace al listado global).
