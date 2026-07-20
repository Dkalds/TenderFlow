---
rfc: pendiente
title: "UX/KPIs · Pipeline/Alertas — alertas reales suscribibles y clarificar IA vs renovaciones/calendario"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: implemented
area: web/pipeline-alertas
---

## Contexto

`web/src/app/(dashboard)/pipeline-alertas/page.tsx` es el tracker de oportunidades
por plazo: en plazo, vencen 7d/30d, upcoming, por horizonte/trimestre, scatter
urgencia-vs-valor y forecast de re-tendering. Es backend-driven y rico. Dos
problemas:

1. **"Alertas" en el nombre, pero es un panel pasivo.** Muestra urgencia
   (vencen_7d/30d, scatter) pero **no entrega alertas**: no hay suscripción ni
   notificación cuando una licitación de alto valor entra en plazo crítico. La
   promesa del nombre no se cumple — mismo hueco que `mi-watchlist` (reglas sin
   alerta real).
2. **Solapamiento de IA.** "Plazos/oportunidades que vienen" se reparte entre
   **pipeline-alertas** (tenders activos cerrando + forecast), **renovaciones**
   (contratos ganados que vencen) y **calendario** (vista calendario de plazos).
   Tres páginas en el mismo territorio; el usuario no sabe cuál es su "qué hago
   hoy".

> Existe infra de notificaciones/watchlist (`services/notifications.py`,
> `watchlist_feed`). Vía API (§3.8); la suscripción es aditiva (§3.5).

## Decisión

1. **Alertas reales suscribibles.** Permitir suscribirse a un criterio/umbral
   (p.ej. "alto valor venciendo en ≤7d en mi nicho") que dispare notificación
   (`notifications`/email) — reusando la misma infra que el RFC de Mi Watchlist.
   La página deja de ser solo visual.
2. **Clarificar IA.** Definir un rol claro por página y enlazarlas: pipeline-alertas
   = oportunidades **activas** cerrando + suscripción; renovaciones = **vencimientos
   de contratos ganados** (riesgo de cambio); calendario = vista temporal de plazos.
   Un encabezado en cada una y navegación cruzada que evite confusión.
3. **Drill-down.** Scatter/tablas enlazan al detalle de la licitación.

**Qué NO se hace:**

- **No** se fusionan las tres páginas (tienen ángulos distintos); se diferencian y
  enlazan.
- **No** se duplica el motor de alertas: se reusa el del RFC de Mi Watchlist.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo | Cero trabajo | "Alertas" que no alertan; IA confusa con 2 páginas más | No cumple la promesa |
| Solo renombrar | Trivial | Pierde la oportunidad de alertar de verdad | Cosmético |
| Alertas reales + IA clara (elegida) | Cumple la promesa; reusa infra | Suscripción + coordinación con Mi Watchlist | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.5 Pydantic v2 DTOs | Aditivo (suscripción de alerta) | Reusar el modelo del RFC de Mi Watchlist |
| §3.8 Frontend vía API | Reusa `notifications`/`watchlist_feed` | — |
| §3.3 Migraciones | Si la suscripción persiste, reusa la tabla del RFC Mi Watchlist | OK humano §6 |
| §3.1 / §3.2 / §3.4 / §3.6 | Ninguno/mínimo | Tipar |

## Plan de implementación

1. Coordinar con el RFC de Mi Watchlist (motor de reglas/alertas): exponer
   suscripción desde pipeline-alertas.
2. `pipeline-alertas/page.tsx` — botón "alertarme de esto"; encabezado de rol +
   enlaces a renovaciones/calendario; drill-down.
3. Tests: suscribir un criterio genera notificación; drill-down navega.

**Archivos de partida**: `pipeline-alertas/page.tsx:42-95`,
`services/notifications.py`, `api/routes/watchlist_feed.py`,
`renovaciones/page.tsx`, `calendario/page.tsx` (IA).
**Riesgo estimado**: bajo-medio (depende del motor de alertas del RFC Mi Watchlist).
**Tiempo estimado**: 1 día (sobre el motor de alertas existente).

## Acceptance criteria

- [ ] Se puede suscribir un criterio/umbral y recibir notificación real.
- [ ] Cada una de pipeline-alertas/renovaciones/calendario declara su rol y enlaza a las otras.
- [ ] Scatter/tablas enlazan al detalle.
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend) en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

**2026-06-27 — Implementado parcialmente (frontend puro, sin migración):**

- **Clarificar IA** (criterio 2) ✅: nuevo componente
  `web/src/components/pipeline-role-nav.tsx` declara el rol de
  pipeline-alertas / renovaciones / calendario y las enlaza entre sí; añadido a las
  tres páginas bajo su título.
- **Drill-down** (criterio 3) ✅: la lista de urgentes y la tabla de forecast enlazan
  al detalle (`/detalle?lic=…`); el scatter Urgencia×Valor navega al hacer click en un
  punto (`PipelineUrgencyScatter` con prop `onPointClick`).
- Test: `web/src/components/__tests__/pipeline-role-nav.test.tsx`.

**2026-06-27 — Criterio 1 (alertas reales suscribibles) ✅:** botón "Alertarme de
oportunidades así" en la card de filtros de forecast (`pipeline-alertas/page.tsx`) que
crea una regla de watchlist con el umbral de importe actual (frecuencia diaria) vía
`POST /api/v1/watchlist/rules`, reutilizando el motor de alertas server-side construido
para `ux-mi-watchlist` (tabla `watchlist_rules` v43 + job del scheduler que entrega las
notificaciones reales). Con esto los 3 criterios quedan cubiertos → status `implemented`.

**2026-07-20 — Rework de altitud (cierra el "pendiente de decisión" del RFC de
Resumen sobre reubicación de charts).** El set de charts nunca fue objeto de una
decisión explícita; el rework aplica el mismo criterio que el Resumen (quitar lo
que duplica página dedicada, KPIs accionables/clicables) más 3 fixes de datos
descubiertos en el camino:

- **Fix de datos:** `PipelineEntry.score` era siempre `null` (no existía columna
  `score` en `load_stats_base_df()`) — el badge de Score de la Cola de cierre nunca
  se veía. Nuevo helper público `score_dataframe()` en `services/analytics/scoring.py`
  (reusa `_build_context`/`_score_row`, sin perfil de usuario) puebla `score`/`band`
  de verdad, mergeado sobre la ventana completa del pipeline.
- **Fix de datos:** la página no pasaba `dias`, así que corría con el default de
  30d del endpoint — "En plazo" ≡ "Vencen ≤30 días" (mismo número) y los buckets
  30-90d/90+d del chart de horizonte estaban siempre vacíos. La página ahora pide
  `dias=365`.
- **Fix de datos:** `/analytics/pipeline` no aceptaba los filtros globales que
  `useFilteredQuery` ya enviaba (`ccaa`/`tecnologia`/`estado`/`q`/`importe_min`/
  `fecha_desde`/`fecha_hasta`) — FastAPI los descartaba en silencio. Añadidos al
  `PipelineFilters`/route, con el mismo `_apply_filters` que `overview.py`.

**Quitado** (duplicaba página dedicada): "Distribución por horizonte" y "Volumen
trimestral" (redundantes con los KPIs/tendencias de mercado); "Forecast de volumen
(6 meses)" (duplicado exacto del que ya tiene `/tendencias`); el bloque completo
"Forecast re-licitación" (filtros + 5 cards + Gantt + tabla), que solapaba con
`/renovaciones` (mismo ángulo — contratos que vencen — con un modelo más rico:
`riesgo_cambio` + opportunity score). Sustituido por `RenovacionesBanner`, un CTA
compacto con totales server-side nuevos (`totales_renovaciones()` en
`services/competitive/renovaciones.py`, expuesto en
`GET /competitive/renovaciones/resumen`).

**Añadido:** KPI "Calientes" (licitaciones en plazo con banda de scoring ≥75,
agregado nuevo `PipelineResult.calientes`/`valor_calientes`); los 4 KPIs ahora son
clicables (`href` a `#cola-cierre`/`#ultimas-alertas`, patrón ya usado en Resumen/
Renovaciones); feed "Últimas alertas" (`AlertsFeed`, vía `GET /notifications` —
la página se llamaba "Alertas" pero no mostraba ninguna); feed "Movimientos del
pipeline" (`EventosFeed`, vía `GET /eventos`/`contrato_eventos`, endpoint existente
sin explotar); banda de score (Caliente/Atractiva/Tibia/Descarte) visible en la
Cola de cierre.

**Mantenido:** fila KPI (reformada), Alertas suscribibles, scatter Urgencia vs
valor, Cola de cierre, `PipelineRoleNav`, `ExportPopover`, filtros globales.
`GanttChart` (sin otro consumidor) y los charts `PipelineHorizonChart`/
`PipelineQuarterlyChart`/`PipelineForecastChart` se eliminaron de
`pipeline-charts.tsx`; los endpoints `forecast/volume` y `forecast/retendering`
quedan intactos en el backend (sin consumidor en esta página) — ver
`docs/IMPROVEMENT_BACKLOG.md` para la decisión pendiente sobre su futuro.

Verde: backend (`ruff`/`mypy`/`pytest` — 2499 tests) y frontend (`tsc`/`eslint`/
`vitest` — 89 files, 789 tests, `next build`); `check_frontend_invariants.py` sin
hallazgos nuevos. Verificación manual end-to-end (servicio real contra SQLite
sembrada): score/band poblados, `calientes` cuenta banda Caliente sobre la ventana
completa, filtro `ccaa` filtra de verdad, `totales_renovaciones`/`eventos_recientes`
devuelven los datos esperados.
