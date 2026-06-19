---
rfc: pendiente
title: "UX/KPIs · Tendencias — heatmap real Mes×Estado, banda de forecast theme-safe, drill-down"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: draft
area: web/tendencias
---

## Contexto

`web/src/app/(dashboard)/tendencias/page.tsx` muestra la evolución temporal:
KPIs (total, importe, YoY cantidad/importe, mes pico), barras por mes, área de
importe acumulado, waterfall de variación, histograma de importes, heatmap
Mes×Estado y forecast a 6 meses con banda de confianza. Es una página rica, pero
tiene **dos defectos de correctitud/visualización** y gaps de interacción:

1. **El heatmap Mes×Estado es sintético, no real.** `heatmapData`
   (líneas 150-166) no usa una tabla cruzada real: calcula
   `value = round(m.n_licitaciones * (e.n / totalByEstado))` — aplica la
   distribución **global** de estados, idéntica a todos los meses. Es el producto
   de marginales, no el cruce real Mes×Estado. Parece dato pero no lo es (misma
   clase de bug que el proxy de CCAA en Resumen): un mes con un patrón de estados
   atípico se ve "normal". Esto **engaña** al analista.

2. **La banda de confianza del forecast rompe en dark mode.** Para simular una
   banda flotante, el `lower` se rellena de blanco opaco
   (`<Area dataKey="lower" fill="hsl(0, 0%, 100%)" fillOpacity={1} />`, línea 425).
   En tema oscuro eso pinta un **bloque blanco** sobre el chart. Es un hack frágil
   y theme-inconsistente.

3. **Sin drill-down.** Ni las barras por mes, ni las celdas del heatmap, ni los
   KPIs son clicables. El gesto natural —"ver las licitaciones de ese mes/estado"—
   no existe; las celdas solo tienen `title` (tooltip).

4. **Forecast sin señal de calidad/cobertura.** Muestra banda pero no dice sobre
   cuántos meses se entrenó ni un error (MAPE/intervalo). El backend ya tiene
   `services/analytics/forecast.py` / `forecast_svc.py` que pueden exponerlo.

> La página consume vía `useFilteredQuery` → API tipada (§3.8). Lo que requiera
> dato nuevo (cross-tab real, métrica de forecast) pasa por el contrato (§3.5).

## Decisión

1. **Heatmap con datos reales.** Exponer una tabla cruzada Mes×Estado real desde
   `services/analytics` (conteo por `(mes, estado)`), y consumirla directamente en
   vez de derivarla de marginales. Mientras no exista el endpoint, **etiquetar el
   heatmap como "estimado"** o no renderizarlo (no presentar síntesis como dato).

2. **Banda de forecast theme-safe.** Reemplazar el truco de relleno blanco por una
   banda correcta: o bien una `Area` de rango (base transparente + `upper-lower`)
   apilada, o dos áreas con tokens de tema (`hsl(var(--primary)/α)`), sin colores
   hardcodeados. Debe verse igual en claro y oscuro.

3. **Drill-down.** Barras por mes y celdas del heatmap clicables → navegan al
   listado con `fecha_desde/hasta` (y `estado`) preaplicados. KPIs YoY enlazan a
   la comparación de periodos.

4. **Contexto de calidad del forecast.** Mostrar nº de meses de histórico usados y
   una métrica de error (p.ej. MAPE backtest) si el servicio la provee; subtítulo
   "previsión basada en N meses, error ±X %". Si no está, indicar "previsión
   experimental".

**Qué NO se hace:**

- **No** se cambia el modelo de forecast (solo se expone su metadata de calidad).
- **No** se tocan los KPIs YoY (su cálculo client-side es correcto; se les añade
  enlace, no se rehace).
- **No** se rehace el sistema de filtros global.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Mantener heatmap sintético | Sin backend nuevo | Muestra dato falso; engaña | Inaceptable para una herramienta de inteligencia |
| Calcular el cross-tab en el cliente desde otra query | Sin endpoint nuevo | No hay endpoint que devuelva el detalle por (mes,estado); reconstruirlo en el cliente es caro/parcial | El backend es el lugar correcto |
| Dejar el hack de banda blanca | Cero trabajo | Bloque blanco en dark mode | Bug visible |
| Heatmap real + banda theme-safe + drill-down (elegida) | Correcto, accesible, accionable | 1 endpoint nuevo (cross-tab) + metadata forecast | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Tipos generados nuevos (cross-tab, forecast meta) | Regenerar OpenAPI; tipar |
| §3.5 Pydantic v2 DTOs | **Aditivo**: endpoint/campo de cross-tab Mes×Estado y metadata de forecast | Cambio consciente; regenerar cliente |
| §3.8 Frontend vía API | El cross-tab se calcula en `services/analytics`, no en el cliente | Endpoint dedicado |
| §3.2 / §3.3 / §3.4 / §3.6 | Ninguno | — |

## Plan de implementación

1. `services/analytics/` + `api/routes/analytics.py` — endpoint cross-tab
   `(mes, estado) -> count` y, en forecast, metadata de calidad (meses, error).
2. `tendencias/page.tsx` — consumir el cross-tab real; quitar `heatmapData`
   sintético; banda de forecast con tokens de tema (sin blanco hardcodeado);
   barras/celdas clicables con filtros preaplicados; subtítulo de calidad.
3. Regenerar `@/generated/api`.
4. Tests vitest: heatmap pinta los valores del endpoint (no marginales); banda
   visible en dark mode (snapshot/token, no blanco); click navega filtrado.

**Archivos de partida**: `tendencias/page.tsx:150-166,418-431`,
`components/charts/waterfall-chart.tsx`, `services/analytics/forecast_svc.py`,
`services/analytics/trends.py`, `api/routes/analytics.py`.
**Riesgo estimado**: bajo-medio. Frontend aditivo + 1 endpoint de cross-tab.
**Tiempo estimado**: 1-1.5 días.

## Acceptance criteria

- [ ] El heatmap Mes×Estado refleja el cruce real del backend (no marginales), o se
      etiqueta/oculta si el dato no existe.
- [ ] La banda de confianza del forecast se ve correctamente en claro y oscuro (sin
      relleno blanco hardcodeado).
- [ ] Barras por mes y celdas del heatmap son clicables → listado filtrado.
- [ ] El forecast muestra cobertura (meses) y, si está, error.
- [ ] `npm run typecheck && npm run lint && npm test` (web) en verde; `make lint &&
      make typecheck && make test-unit` si cambió el DTO.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->
