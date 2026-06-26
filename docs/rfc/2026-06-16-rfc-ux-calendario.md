---
rfc: pendiente
title: "UX/KPIs · Calendario — datos diarios reales y reorientar a vencimientos accionables"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: draft
area: web/calendario
---

## Contexto

`web/src/app/(dashboard)/calendario/page.tsx` muestra un heatmap estilo
"contribuciones de GitHub" por día. Tiene dos problemas serios:

1. **Los conteos diarios son sintéticos.** La página pide
   `/api/v1/analytics/trends?group_by=week` (conteos **semanales** de publicación)
   y luego **inventa** la granularidad diaria repartiendo cada semana entre 7 días:
   `dailyShare = Math.round(point.count / 7)`, con un sesgo de día laborable
   (`d < 5 ? dailyShare + 1 : dailyShare`, líneas 77-78). El heatmap por día no
   refleja actividad diaria real: es un reparto uniforme con un fudge. Misma clase
   de bug que el heatmap sintético de Tendencias y el proxy de CCAA de Resumen —
   presenta dato fabricado como real.

2. **Métrica equivocada para un "Calendario".** Para una herramienta de
   licitaciones, un calendario debería responder **"¿qué vence y cuándo?"**
   (`fecha_limite`/fin de plazo de presentación) — lo accionable (el propio Resumen
   tiene un KPI "Vencen 48h"). En cambio muestra un heatmap de **publicaciones**, y
   encima con resolución diaria falsa. El usuario no puede ver sus plazos.

> La página ya consume vía API (§3.8). El arreglo pide un agregado diario real y
> reorienta el contrato hacia vencimientos (§3.5 aditivo).

## Decisión

Convertir Calendario en un **calendario de vencimientos accionable**, con datos
diarios reales.

1. **Datos diarios reales.** Exponer `group_by=day` (o un endpoint de calendario)
   en `services/analytics`, y consumirlo en vez de repartir la serie semanal.
   Eliminar el `dailyShare`/fudge.

2. **Reorientar a vencimientos.** La vista principal pasa a ser plazos de
   presentación (`fecha_limite`/`fecha_fin`): cada día muestra cuántas licitaciones
   **cierran** ese día; intensidad por nº y/o importe en juego. La actividad de
   publicación queda como vista secundaria conmutable.

3. **Accionable.** Click en un día → lista de licitaciones que vencen ese día
   (enlazadas al detalle/PLACSP). Resaltar "hoy" y los próximos 7 días; integrar
   con la watchlist ("vencen y coinciden con tus reglas").

4. **KPIs del calendario.** "Vencen esta semana", "vencen este mes", "día pico de
   cierres" — desde el dato real.

**Qué NO se hace:**

- **No** se elimina la vista de actividad de publicación; se conserva como toggle.
- **No** se construye un calendario editable/de eventos propios (fuera de scope).
- **No** se mezcla con `mi-watchlist` (se enlaza, no se fusiona).

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Mantener el spread semanal→diario | Cero backend | Dato diario falso; métrica no accionable | Engaña y no sirve para plazos |
| Solo datos diarios reales (sin reorientar) | Heatmap honesto | Sigue mostrando publicaciones, no vencimientos | Pierde el valor del calendario |
| Datos diarios reales + foco en vencimientos (elegida) | Honesto y accionable | Endpoint nuevo (día / vencimientos) | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Tipos generados (serie diaria / vencimientos) | Regenerar OpenAPI; tipar |
| §3.5 Pydantic v2 DTOs | **Aditivo**: agregado diario y de vencimientos | Cambio consciente; regenerar cliente |
| §3.8 Frontend vía API | El agregado diario se calcula en backend | `services/analytics` |
| §3.2 / §3.3 / §3.4 / §3.6 | Ninguno | — |

## Plan de implementación

1. `services/analytics` + `api/routes/analytics.py` — agregado por día
   (publicación) y por día de vencimiento (`fecha_limite`/`fecha_fin`).
2. `calendario/page.tsx` — consumir el diario real; vista principal = vencimientos;
   día clicable → listado; resaltar hoy + próximos 7; KPIs de cierres.
3. Regenerar `@/generated/api`.
4. Tests vitest: el heatmap usa el dato del backend (no `count/7`); click navega a
   las licitaciones que vencen ese día.

**Archivos de partida**: `calendario/page.tsx:55-130`,
`components/charts/calendario-charts.tsx`, `services/analytics/trends.py`,
`db/repositories/licitaciones.py` (campos de fecha límite), `api/routes/analytics.py`.
**Riesgo estimado**: bajo-medio. Endpoint aditivo; el front cambia de fuente.
**Tiempo estimado**: 1-1.5 días.

## Acceptance criteria

- [ ] El heatmap usa conteos diarios reales del backend (sin reparto semanal/fudge).
- [ ] La vista principal muestra vencimientos por día; "hoy" y próximos 7 resaltados.
- [ ] Click en un día lista las licitaciones que cierran ese día.
- [ ] KPIs "vencen esta semana/mes" desde el dato real.
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend) en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

2026-06-25 — **Implementado parcialmente (criterio #1: datos diarios reales).**
El bug de integridad —el núcleo del RFC— queda resuelto. Backend
(`services/analytics/trends.py`): `_build_series` y `TrendsFilters.group_by`
ganan `"day"` (período `"D"`, formato `"%Y-%m-%d"`); el endpoint
`/api/v1/analytics/trends` acepta `group_by=day`. Frontend
(`calendario/page.tsx`): la página pide `group_by=day` y construye `dailyCounts`
leyendo el conteo REAL por fecha; se elimina el reparto sintético
`dailyShare = Math.round(point.count / 7)` con el fudge de día laborable
(ADR-014, Patrón 1). El heatmap, las barras mensuales y la distribución por día
de la semana ahora derivan del dato diario real. Tests: nuevo
`tests/test_analytics_trends.py` (4) cubre day/month grouping, filtros y vacío.
Verde: pytest/mypy/ruff/codespell + `tsc`/`eslint`/`vitest` (285); el scanner de
invariantes ya no marca la página.

**Diferido (criterios #2-#4: reorientar a vencimientos).** Mostrar plazos de
presentación (`fecha_limite`/`fecha_fin`) como vista principal, día clicable →
listado de cierres, resaltar hoy/próximos 7 y KPIs de vencimientos es un rework
de producto más amplio: requiere exponer el campo de fecha límite en el agregado
(hoy `load_stats_dataframe` sirve `fecha_publicacion`) y un endpoint/serie de
vencimientos. Se aborda en un RFC/iteración aparte; la vista de actividad de
publicación —ahora honesta— se mantiene como base.
