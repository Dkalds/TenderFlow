---
rfc: pendiente
title: "UX/KPIs · Resumen — deltas consistentes, KPIs accionables y arreglo de CCAA cubiertas"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: draft
area: web/resumen
---

## Contexto

`web/src/app/(dashboard)/resumen/page.tsx` es la página de aterrizaje (overview
ejecutivo). Hoy ya es densa: KPIs (`KpiRows`), banner de novedades, timeline
scatter, top licitaciones, estado/tipos, Sankey Tipo→Estado, indicadores de
mercado, comparación de periodos, actividad/tecnología, evolución mensual, top
órganos y funnel de estados — 13 secciones apiladas, alimentadas por 9 queries
(`overview`, `resumen/hoy`, `sankey`, `timeline`, `top`, `compare-periods`,
`tecnologias`, `proyectos-modulos`, `novedades`).

Las KPI cards (`resumen/_components/kpi-rows.tsx`) ya son sofisticadas:
sparklines (`MiniSparkline`), detección de anomalías (`isAnomaly`), acentos e
iconos. Pero hay gaps concretos de KPI/UX:

1. **Delta inconsistente.** Solo *"Organos Unicos"* muestra `trend`
   (`overview.yoy_delta`, línea 126). El resto (Total Licitaciones, Importe Total,
   Importe Medio…) muestra la *forma* del sparkline pero **no el cambio
   cuantificado** ("+12 % vs periodo anterior"). El dato existe: `por_mes` y
   `/analytics/compare-periods` ya se piden, pero el delta vive aislado en la
   sección `PeriodComparison`, muy abajo. El usuario ve una curva pero no el número.

2. **KPIs sin acción (dead-ends).** `KpiCard` no enlaza a ningún lado. Las
   métricas más accionables —*"Vencen 48h"*, *"Nuevas 24h"*, *"Calientes"*— son
   **números muertos**: no se puede clicar para ver *cuáles* licitaciones vencen o
   están calientes. La página más orientada a la acción del producto es pasiva.

3. **"CCAA cubiertas" es un proxy engañoso.** Se back-calcula como
   `Math.round((concentracion_geo_top3 / 100) * 17)` (líneas 133-137): deriva una
   "cobertura" de un porcentaje de *concentración* del top-3 × 17 CCAA.
   Concentración ≠ cobertura: el número puede ser incorrecto. Es un **bug de
   correctitud de KPI**, no estético.

4. **Sin jerarquía / IA.** 13 secciones en scroll vertical, sin progressive
   disclosure ni agrupación; en móvil es un muro de charts. No hay un "qué mirar
   primero / qué requiere atención".

> Contexto técnico: la página consume todo vía `useFilteredQuery` → API tipada
> (`@/generated/api`). Respeta el invariante §3.8 (frontend siempre vía API). Las
> mejoras de KPI que requieran datos nuevos pasan por el contrato DTO (§3.5).

## Decisión

Convertir el Resumen en un **cockpit ejecutivo accionable**, reutilizando datos ya
disponibles y añadiendo solo los campos KPI que falten en el contrato.

1. **Delta period-over-period consistente en todos los KPIs primarios.** `KpiCard`
   muestra, junto al sparkline, el `%` de cambio vs el periodo comparable anterior
   (signo + color + flecha + `aria-label`). Fuente: `por_mes` (últimos vs previos)
   o `compare-periods` cuando `comparar` está activo. Unifica la señal que hoy
   está partida entre sparkline (arriba) y `PeriodComparison` (abajo).

2. **KPIs accionables (drill-down).** *"Vencen 48h"*, *"Nuevas 24h"*,
   *"Calientes"*, *"Total activas"* se vuelven clicables → navegan al listado
   (`detalle`/`investigador`) con el filtro correspondiente preaplicado (vence ≤
   48h, publicado ≤ 24h, score caliente). `KpiCard` acepta `href`/`onClick`
   opcional, accesible (rol link, foco, teclado).

3. **Arreglar "CCAA cubiertas".** Sustituir el back-cálculo por un conteo real de
   CCAA distintas con actividad en el rango (campo nuevo `ccaa_cubiertas: int` en
   el DTO de overview, calculado en `services/analytics/overview.py`). Mientras el
   backend no lo exponga, **ocultar** la card en vez de mostrar un número dudoso.

4. **Jerarquía / progressive disclosure (IA).** Bloque superior "Requiere
   atención" (vencimientos + novedades de alto importe) por encima del fold;
   agrupar las secciones analíticas profundas (Sankey, scatter completo, funnel)
   bajo tabs o secciones colapsables "ver más", de modo que el overview entre en
   una pantalla. Garantizar reflow en móvil.

**Qué NO se hace:**

- **No** se eliminan secciones ni se mueven a otras páginas en este RFC (solo se
  agrupan/colapsan); una reubicación de charts a sus páginas dedicadas
  (`tendencias`, `geografia`) se evalúa por separado.
- **No** se cambia el sistema de filtros global (`useFilters`/nuqs).
- **No** se inventa un KPI nuevo sin dato: si el backend no lo soporta, se oculta
  (caso CCAA) en lugar de aproximar.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo | Cero trabajo | KPIs sin delta numérico ni acción; CCAA potencialmente incorrecta | No mejora KPI/UX |
| Solo añadir deltas | Rápido | Deja los KPIs como dead-ends y la CCAA dudosa | Parcial |
| Rediseño completo del overview | Máximo control de IA | Riesgo alto, toca 13 secciones y 9 queries | Desproporcionado; se prefiere incremental |
| Cockpit accionable incremental (elegida) | Reusa datos; alto impacto; bajo riesgo | Requiere 1 campo DTO nuevo (CCAA) y `href` en KpiCard | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Tipos generados (`@/generated/api`) + props nuevas de `KpiCard` (`delta`, `href`) | Tipar; regenerar OpenAPI si cambia el DTO |
| §3.5 Pydantic v2 DTOs | **Campo nuevo** `ccaa_cubiertas` (y, si hace falta, `delta_pct` por KPI) en el DTO de overview | Cambio **aditivo y consciente**; regenerar el cliente tipado |
| §3.8 Frontend vía API | Los nuevos datos se consumen por API, no por acceso directo a db | Calcular en `services/analytics/overview.py`, exponer en `api/routes/analytics.py` |
| §3.2 / §3.3 / §3.4 / §3.6 | Ninguno | — |

## Plan de implementación

1. `components/charts/kpi-card.tsx` — props opcionales `delta` (valor + dirección)
   y `href`/`onClick`; render accesible del delta y del enlace.
2. `resumen/_components/kpi-rows.tsx` — calcular delta vs periodo previo desde
   `porMes`/`compare`; pasar `href` con filtro preaplicado a las 4 cards de "hoy".
3. `services/analytics/overview.py` + `api/routes/analytics.py` — `ccaa_cubiertas`
   (conteo distinto de CCAA en rango); regenerar OpenAPI → `@/generated/api`.
4. `resumen/page.tsx` — bloque "Requiere atención" arriba; agrupar Sankey/scatter/
   funnel en secciones colapsables; revisar reflow móvil.
5. Tests vitest: delta correcto (subida/bajada/igual), card clicable navega con el
   filtro, card CCAA oculta si falta el dato.

**Archivos de partida**: `resumen/page.tsx`, `resumen/_components/kpi-rows.tsx`,
`components/charts/kpi-card.tsx`, `resumen/_components/period-comparison.tsx`,
`services/analytics/overview.py`, `api/routes/analytics.py`.
**Riesgo estimado**: bajo-medio. El grueso es frontend aditivo; el único cambio de
contrato es `ccaa_cubiertas` (aditivo).
**Tiempo estimado**: 1-1.5 días.

## Acceptance criteria

- [ ] Todos los KPIs primarios muestran delta vs periodo anterior (no solo Organos).
- [ ] "Vencen 48h"/"Nuevas 24h"/"Calientes" son clicables y navegan al listado
      filtrado (accesible por teclado).
- [ ] "CCAA cubiertas" usa un conteo real del backend, o se oculta si no existe.
- [ ] El overview presenta un bloque "Requiere atención" por encima del fold y las
      secciones profundas son colapsables; reflow correcto en móvil.
- [ ] `npm run typecheck && npm run lint && npm test` (web) en verde; si cambió el
      DTO, `make lint && make typecheck && make test-unit` también.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

2026-06-22 — **Implementado (#3, correctitud).** La card "CCAA cubiertas" se
back-calculaba como `concentracion_geo_top3 / 100 × 17` (concentración ≠ cobertura).
Eliminada la fabricación `× 17`: la card se **reetiqueta al dato real** que ya
entrega el backend — "Concentración top-3 CCAA" = `concentracion_geo_top3%`
(importe en las 3 CCAA principales). Honesto y sin pérdida de información; el conteo
real de CCAA distintas (`ccaa_cubiertas`) queda como adición backend si se quiere la
métrica de cobertura. Verde: `tsc`/`eslint`/`vitest` (19 files, 285 tests).
**Diferido:** (1) delta period-over-period en todos los KPIs, (2) KPIs clicables
con drill-down, (4) progressive disclosure / bloque "Requiere atención".
