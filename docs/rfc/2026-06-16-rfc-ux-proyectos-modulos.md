---
rfc: pendiente
title: "UX/KPIs · Proyectos/Módulos — KPIs a nivel licitación (sin doble conteo multi-módulo) y drill-down"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: implemented
area: web/proyectos-modulos
---

## Contexto

`web/src/app/(dashboard)/proyectos-modulos/page.tsx` analiza módulos SAP y tipos de
proyecto con datos del backend (módulos, tipos, `total_clasificados`, `top_modulo_yoy`,
cross-tab `tipo_estado`, CPV) — buen patrón (cross-tabs reales).

Problema de **exactitud de KPI por fan-out multi-módulo**: una licitación puede
tener **varios módulos SAP**. `ModuloItem` agrega por módulo (`count`/`importe` =
licitaciones e importe **con** ese módulo). Pero las KPIs suman sobre los módulos:

```ts
const ticketMedioSAP = sum(m.importe) / sum(m.count);   // líneas 93-97
```

Si una licitación tiene módulos A+B, su importe se suma **en A y en B** → el
"importe total SAP" queda **inflado** y el denominador de `ticket medio` cuenta
**asignaciones de módulo**, no licitaciones. (`pctMultiModulo` usa esa misma
diferencia como heurística — razonable — pero las KPIs de importe/ticket sí se
distorsionan.) Además no hay drill-down de módulo/tipo al listado.

> Vía API (§3.8). El arreglo es calcular las KPIs de importe/ticket a nivel
> licitación en backend (distinct), no por suma de filas de módulo.

## Decisión

1. **KPIs a nivel licitación.** Calcular en backend `importe_total_sap` y
   `ticket_medio_sap` sobre licitaciones **distintas** (no sumando filas de módulo),
   exponerlas en el DTO y usarlas en las cards. Los breakdowns por módulo siguen
   por-módulo (eso es correcto para los charts).
2. **Drill-down.** Módulo/tipo/celda de `tipo_estado` enlazan al listado filtrado.

**Qué NO se hace:**

- **No** se cambian los charts por-módulo (correctos para distribución).
- **No** se toca la clasificación de módulos.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo | Cero trabajo | Importe/ticket SAP inflados por multi-módulo | KPI inexacto |
| Deduplicar en cliente | Sin backend | El cliente no tiene el mapeo licitación→módulos completo | No fiable |
| KPIs distinct en backend + drill-down (elegida) | Exacto y accionable | Campos DTO nuevos | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.5 Pydantic v2 DTOs | **Aditivo**: `importe_total_sap`/`ticket_medio_sap` distinct | Cambio consciente |
| §3.8 Frontend vía API | Cálculo en `services/analytics/proyectos_modulos.py` | — |
| §3.1 / §3.2 / §3.3 / §3.4 / §3.6 | Ninguno/mínimo | Tipar |

## Plan de implementación

1. `services/analytics/proyectos_modulos.py` + `api/routes/analytics.py` — KPIs de
   importe/ticket a nivel licitación distinct.
2. `proyectos-modulos/page.tsx` — usar esas KPIs; drill-down de módulo/tipo/celda.
3. Regenerar `@/generated/api`.
4. Tests: una licitación multi-módulo no infla el importe total; drill-down filtra.

**Archivos de partida**: `proyectos-modulos/page.tsx:60-100`,
`services/analytics/proyectos_modulos.py`, `api/routes/analytics.py`.
**Riesgo estimado**: bajo.
**Tiempo estimado**: 0.5-1 día.

## Acceptance criteria

- [ ] `importe total SAP` y `ticket medio SAP` se calculan a nivel licitación distinct (sin doble conteo).
- [ ] Módulo/tipo/celda enlazan al listado filtrado.
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend) en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

2026-06-22 — **Implementado (KPIs distinct).** Backend
(`services/analytics/proyectos_modulos.py`): `ProyectosModulosResult` gana
`importe_total_sap` y `ticket_medio_sap` calculados a nivel **licitación distinct**
(`_build_modulos` devuelve el importe sumado una vez por licitación clasificada, no
por fila de módulo). Frontend: la card "Ticket Medio SAP" usa `data.ticket_medio_sap`
del backend en vez de `sum(modulos.importe)/sum(modulos.count)` (que inflaba por
multi-módulo). Tests: +1 backend (FI+CO en una licitación → importe contado una vez),
9/9 verde; mypy limpio; `tsc`/`eslint`/`vitest` (285) verde. **Diferido:** drill-down
de módulo/tipo/celda al listado filtrado.
