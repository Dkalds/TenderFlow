---
rfc: pendiente
title: "UX/KPIs · Tendencias CPV — forecast por CPV (no global) y drill-down"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: partially-implemented
area: web/tendencias-cpv
---

## Contexto

`web/src/app/(dashboard)/tendencias-cpv/page.tsx` compara la evolución de varias
familias CPV (series por CPV del backend, multi-select, top-15 por importe,
overlay de forecast). Usa `useFilteredQuery` (respeta filtros). Bien hecha, con un
defecto de correctitud:

1. **El forecast overlay es global, no por CPV.** Se pide
   `/api/v1/analytics/forecast/volume?months_ahead=6` **sin parámetro de CPV**
   (línea 83). Es decir, al activar "forecast" sobre un gráfico de CPVs
   seleccionados se superpone **la previsión global del mercado**, idéntica
   independientemente de qué CPVs elijas. El usuario lo lee como "la previsión de mi
   CPV", y no lo es. Mismo patrón de "dato que no corresponde a lo mostrado".
2. **Sin drill-down.** Las series/top-CPV no enlazan al listado filtrado por ese CPV.

> Vía API (§3.8). Un forecast por CPV es aditivo en el endpoint (§3.5).

## Decisión

1. **Forecast por CPV.** Pasar el/los CPV seleccionados al endpoint de forecast
   (`forecast/volume?cpv=...`) para que la previsión corresponda a la serie
   mostrada. Si solo se soporta global, **etiquetarlo explícitamente** como
   "previsión global del mercado" hasta tener el per-CPV, no como previsión del CPV.
2. **Drill-down.** Top-CPV y series enlazan al listado filtrado por ese CPV.

**Qué NO se hace:**

- **No** se cambia el modelo de forecast; se le pasa el filtro de CPV.
- **No** se rehace el multi-select ni los charts.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo (forecast global en gráfico por CPV) | Cero trabajo | Engaña: previsión no corresponde al CPV | Incorrecto |
| Etiquetar como global | Trivial, honesto | No da previsión real por CPV | Mínimo aceptable, no ideal |
| Forecast por CPV + drill-down (elegida) | Previsión correcta y accionable | Param nuevo en el endpoint | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.5 Pydantic v2 DTOs | **Aditivo**: `cpv` en `forecast/volume` | Cambio consciente; regenerar cliente |
| §3.8 Frontend vía API | Forecast por CPV en `services/analytics/forecast*` | — |
| §3.1 / §3.2 / §3.3 / §3.4 / §3.6 | Ninguno/mínimo | Tipar |

## Plan de implementación

1. `services/analytics/forecast*` + `api/routes/analytics.py` — aceptar `cpv` en el
   forecast.
2. `tendencias-cpv/page.tsx` — pasar el CPV; etiquetar correctamente; drill-down al
   listado.
3. Regenerar `@/generated/api`.
4. Tests: el forecast cambia con el CPV seleccionado; el drill-down filtra.

**Archivos de partida**: `tendencias-cpv/page.tsx:71-110`,
`services/analytics/forecast_svc.py`, `api/routes/analytics.py`.
**Riesgo estimado**: bajo.
**Tiempo estimado**: 0.5-1 día.

## Acceptance criteria

- [ ] El forecast corresponde al/los CPV seleccionados (o se etiqueta como global explícitamente).
- [ ] Top-CPV y series enlazan al listado filtrado por CPV.
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend) en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

2026-06-22 — **Implementado (parcial, frontend).** (1) El forecast overlay es global
(`/forecast/volume` sin CPV); mientras no exista el per-CPV se **etiqueta explícito**
("Global del mercado" + `CardDescription`) para no leerse como previsión del CPV
seleccionado — opción "mínimo aceptable" del propio RFC. Además, fix del hack de
banda blanca (`hsl(0,0%,100%)` → `hsl(var(--card))`, igual que en ux-tendencias;
no estaba listado en este RFC pero el smell vivía aquí también, línea 266). Verde:
`tsc`/`eslint`/`vitest` (19 files, 285 tests). **Diferido (requiere backend):**
forecast por CPV (`forecast/volume?cpv=...`) y drill-down al listado por CPV.
