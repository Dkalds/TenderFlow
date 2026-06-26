---
rfc: pendiente
title: "UX/KPIs · Detalle — score inline alineado con la paginación (no merge con top-500 disjunto)"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: draft
area: web/detalle
---

## Contexto

`web/src/app/(dashboard)/detalle/page.tsx` es el listado principal de
licitaciones y está muy bien hecho: TanStack Table, paginación/orden/filtros
**server-side** vía `/api/v1/licitaciones` (limit/offset/sort_by/q + filtros
globales), panel de detalle, comparador, export. Pero la columna de **score** se
arma mal:

1. **Score desde una lista top-500 disjunta.** El score se pide aparte:
   `/api/v1/analytics/scoring?limit=500` (líneas 215-219) y se mergea por
   `id_externo` con las filas de la página. Como esa lista son los **500 mejores
   por score** —no las filas que estás viendo— el merge solo acierta cuando la fila
   visible casualmente está en ese top-500. Consecuencias:
   - En páginas avanzadas (offset > top-500), o con otro orden/filtro, **la columna
     de score sale vacía** para casi todas las filas.
   - El score mostrado es **inconsistente** con la vista paginada/ordenada/filtrada:
     ordenás por importe en la página 3 y solo ves score en las pocas filas que
     además están en el top-500 global por score.
   Es el mismo patrón de "dato desalineado con lo que se muestra" que vimos en
   otras páginas, aquí entre dos endpoints.

2. **Tercera watchlist en `localStorage`.** `detalle_watchlist` (línea 77) guarda
   licitaciones "destacadas" solo en local — un tercer concepto de watchlist junto
   a las reglas de `mi-watchlist` (también local) y la watchlist de empresas
   (server-side). Fragmentación: lo destacado no sincroniza ni alimenta alertas.

> La lista ya es server-side (§3.8). El arreglo correcto es que el score venga
> **inline** con cada licitación, no de un endpoint paralelo (§3.5 aditivo).

## Decisión

1. **Score inline en el listado.** Incluir `score`/`band` (y, si cabe, `desglose`)
   por fila en la respuesta de `/api/v1/licitaciones`, calculados/joineados en
   backend **para exactamente las filas de la página** (mismo orden/filtro). El
   frontend deja de hacer el fetch de `scoring?limit=500` y el merge cliente. Así
   el score está siempre alineado con lo que se ve, en cualquier página.
   - Opción de bajo coste si el join es caro: endpoint de scoring **por lote de
     ids** (`POST /scoring` con los ids de la página) en vez del top-500 fijo.
2. **Consolidar "destacados" en la watchlist server-side.** Migrar
   `detalle_watchlist` a la watchlist persistente (ver RFC de Mi Watchlist), para
   que destacar una licitación sincronice y pueda alertar. `localStorage` queda
   como caché/migración.

**Qué NO se hace:**

- **No** se cambia el modelo de scoring ni la tabla/paginación.
- **No** se elimina el export; se mantiene (el CSV cliente exporta la página, el
  ExportPopover el server — se documenta la diferencia).
- **No** se rehace el sistema de filtros.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo (merge con top-500) | Cero backend | Score ausente/inconsistente fuera del top-500 | Columna engañosa |
| Subir el `limit` del scoring | Trivial | Sigue disjunto del orden/filtro/página; transfiere de más | No alinea |
| Score inline en el listado (elegida) | Siempre alineado; una sola query | Campo DTO nuevo / join | — |
| Scoring por lote de ids de la página | Sin tocar el join del listado | Segunda request acoplada a la página | Aceptable como fallback |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | `LicitacionSummary` gana `score`/`band` (o endpoint batch) | Regenerar OpenAPI; tipar |
| §3.5 Pydantic v2 DTOs | **Aditivo**: `score`/`band` en el summary | Cambio consciente; regenerar cliente |
| §3.8 Frontend vía API | **Refuerza** — elimina el merge cliente entre dos endpoints | Join/score en backend |
| §3.3 Migraciones | Solo si "destacados" pasa a tabla (ver RFC Mi Watchlist) | Revisión nueva; OK humano §6 |
| §3.2 / §3.4 / §3.6 | Ninguno | — |

## Plan de implementación

1. `services/` + `api/routes/licitaciones.py` — `score`/`band` por fila en el
   listado (join con `licitacion_tecnologia_score`/scoring), o endpoint batch por ids.
2. `detalle/page.tsx` — consumir el score inline; eliminar `scoring?limit=500` +
   merge; migrar "destacados" a la watchlist server-side.
3. Regenerar `@/generated/api`.
4. Tests: el score aparece en filas de páginas avanzadas y bajo cualquier orden;
   destacar sincroniza con la watchlist.

**Archivos de partida**: `detalle/page.tsx:75-122,196-219`,
`api/routes/licitaciones.py`, `db/repositories/licitaciones.py`,
`services/threshold_tuning.py`/scoring.
**Riesgo estimado**: bajo-medio. El join de score en el listado conviene medirlo
(índice `idx_lts_lic` ya existe).
**Tiempo estimado**: 1 día.

## Acceptance criteria

- [ ] El score/band se muestra alineado con las filas de cualquier página/orden/filtro.
- [ ] No queda el fetch `scoring?limit=500` + merge cliente.
- [ ] "Destacar" una licitación persiste server-side (no solo `localStorage`).
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend) en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

2026-06-25 — **Implementado (criterio #1: score alineado a la página).** El bug
era aún peor de lo descrito: el merge leía `scoring.items`, pero el endpoint
devuelve `ScoringResult.opportunities` → la columna de score **nunca** se
rellenaba (ni en el top-500), además de estar disjunta del orden/filtro/página.
Fix con el fallback "por lote de ids" del propio RFC (el scoring es un pipeline
pandas sobre todo el dataset con normalización global P10/P90, no una columna de
DB, así que un join inline en `/licitaciones` no encaja): `ScoringFilters` gana
`ids`; `get_scoring` puntúa EXACTAMENTE esas filas (ignorando min_score/band/
limit) reusando el P10/P90 global → score idéntico al ranking. El endpoint
`/api/v1/analytics/scoring` acepta `ids` (CSV) de forma **retrocompatible**: sin
`ids` mantiene el top-N que usa Tecnologías. Frontend
(`detalle/page.tsx`): se elimina el fetch `scoring?limit=500` + merge cliente; se
pide el score de los `id_externo` de la página visible (PAGE_SIZE=25) con
`useQuery` cacheado por ese conjunto; se corrige `.items` → `.opportunities`. Así
el score aparece en cualquier página/orden/filtro. Tests: nuevo
`tests/test_analytics_scoring.py` (5) cubre top-N, ids-mode (exacto, ignora
min_score/limit), consistencia de normalización, id desconocido y vacío. Verde:
pytest/mypy/ruff/codespell + `tsc`/`eslint`/`vitest` (285); el scanner ya no marca
`large-limit` en Detalle.

**Diferido (criterio #3: consolidar "destacados" en la watchlist server-side).**
`detalle_watchlist` en `localStorage` sigue siendo el tercer concepto de
watchlist; migrarlo a persistencia server-side es transversal con `mi-watchlist`
y se aborda junto al RFC de Pipeline de Alertas / Mi Watchlist (donde vive el
modelo de reglas y la migración Alembic).
