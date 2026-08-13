# Mi Pipeline — inventario de la reconstrucción (2026-08-13)

Regla dura del rediseño: consolidar no elimina funcionalidad. Antes de
reconstruir el espacio se inventarían las funciones de las pantallas
absorbidas y se declara **dónde vive cada una después**. Este documento es ese
inventario.

## El movimiento

`/mi-pipeline` dejaba de significar dos cosas a la vez. La palabra *pipeline*
nombraba (a) los plazos del mercado entero (`/analytics/pipeline`, dato global
cacheado) y (b) el pipeline comercial real — los *pursuits* de
`/oportunidades`. El espacio con el posesivo "Mi" era justo el que no tenía
nada personal dentro, y además duplicaba el CRUD de reglas de Mi Watchlist.

La reconstrucción le da una sola identidad: **el cockpit personal de
compromisos, ordenado por tiempo**. Responde "¿qué se me muere si hoy no hago
nada?" con tres vistas:

- **Agenda** (`?vista=agenda`, entrada): pursuits abiertos + señales sin
  triar + renovaciones próximas, en una cronología por bandas de urgencia.
  Fusión, orden y bandas calculadas en `GET /api/v1/pursuits/agenda`
  (ADR-014: el frontend no fabrica orden). Triaje de señales compartido con
  el Radar (`radar_dismissals`); seguir/anticipar crea un pursuit.
- **Embudo** (`?vista=embudo`): `GET /pursuits/metrics`, que existía desde la
  Fase 1 y ninguna superficie pintaba — funnel, win rate, importe adjudicado
  y mediana de decisión.
- **Horizonte** (`?vista=horizonte`): la pantalla completa de renovaciones,
  intacta, más el CTA **Anticipar** por fila (abre un pursuit sobre el
  contrato que vence, antes de que la relicitación se publique).

Novedad de modelo: `pursuits.next_action` + `next_action_due` (migración
v83). Un pursuit sin próxima acción es abandono silencioso; ahora es un KPI y
se edita desde el inspector de la agenda.

## `?vista=` heredados

| Marcador viejo | Aterriza en |
| --- | --- |
| `/pipeline-alertas` | `/mi-pipeline?vista=agenda` (redirect 308) |
| `/renovaciones` | `/mi-pipeline?vista=horizonte` (redirect 308) |
| `/mi-pipeline?vista=pipeline` | vista `agenda` (alias en la página) |
| `/mi-pipeline?vista=renovaciones` | vista `horizonte` (alias en la página) |

## Inventario de `/pipeline-alertas` (pantalla retirada)

| # | Función | Dónde vive ahora |
| --- | --- | --- |
| 1 | Línea de estado: nº en plazo + valor 12 meses (mercado) | KPIs de mercado de `/resumen` ("Vencen 48h", "Grandes en plazo"); el corte completo, en `/detalle`. `GET /analytics/pipeline` sigue publicado para clientes API |
| 2 | KPI "Vencen ≤7 días" + valor (mercado) | Franja de la agenda, versión personal (`vence_semana` + importe, incluye vencidas); versión mercado en `/resumen` |
| 3 | KPI "Vencen ≤30 días" + valor | Banda "Próximos 30 días" de la agenda con conteo por banda |
| 4 | KPI "Calientes" (banda score ≥75) | Las bandas de score son del Radar y allí siguen (segmentos + orden por score). La agenda usa bandas de urgencia, no de score |
| 5 | KPI "Alertas sin leer" | Campana de notificaciones de la barra de ámbito (misma query, marca leídas ambas familias) |
| 6 | Alta rápida de regla (keyword/importe/frecuencia) | Mi Watchlist — ya era el CRUD canónico (la propia pantalla enlazaba "Gestionar en Mi Watchlist"); se elimina el duplicado |
| 7 | Lista de reglas con conteo real + borrar | Mi Watchlist |
| 8 | AlertsFeed (últimas alertas + marcar leídas) | Campana de notificaciones; las coincidencias **accionables** aparecen como señales en la agenda con seguir/descartar persistente |
| 9 | Scatter "Urgencia vs valor" (clic → detalle) | La agenda es ese mismo corte en lista: ordenada por urgencia con el importe en cada fila e inspector al lado. La exploración de mercado por importe/plazo vive en `/detalle` (ordenable por ambas columnas) |
| 10 | EventosFeed (movimientos de contrato, 30 días) | Movido a `/resumen` (`resumen/_components/eventos-feed.tsx`): su pregunta es "¿qué ha cambiado?", la del Resumen — no la agenda personal |
| 11 | Cola de cierre (orden por urgencia, búsqueda, umbral de importe, badges de banda, link a detalle) | Agenda: orden y bandas server-side; ámbito tecnología/CCAA en la barra; el filtrado libre de mercado (q, importe mínimo) es de `/detalle`, que lo aplica en backend sobre el corpus completo — no sobre una página cliente |
| 12 | RenovacionesBanner (totales + enlace) | Vista Horizonte del propio espacio (pantalla completa de renovaciones) |
| 13 | ExportPopover (`seccion=pipeline-alertas`) | El export de listados de mercado vive en `/detalle` (Excel/CSV). El endpoint de exports conserva la sección para clientes existentes |
| 14 | PipelineRoleNav (orientación del territorio) | Conservado: ahora Agenda / Horizonte / Calendario (`components/pipeline-role-nav.tsx`) |

Componentes borrados: `pipeline-alertas/page.tsx`, `_components/alerts-feed.tsx`,
`_components/renovaciones-banner.tsx`, `components/charts/pipeline-charts.tsx`
(scatter) y sus tests. Componente movido: `eventos-feed.tsx` → `resumen/_components/`.

## Inventario de `/renovaciones` (conservada como Horizonte)

Pantalla intacta al 100% (KPIs de totales server-side, cartera por empresa,
tabla virtualizada con score de oportunidad, búsqueda, horizonte 3-24 meses).
Se le **añade** la columna "Acción" con el CTA Anticipar. Su
`PipelineRoleNav` apunta ahora a la agenda en vez de a la pantalla retirada.

## Endpoints

| Endpoint | Estado |
| --- | --- |
| `GET /api/v1/pursuits/agenda` | **Nuevo**, tipado (`PipelineAgendaResponse`), sin caché compartida (dato por usuario/org) |
| `PATCH /api/v1/pursuits/{id}` | Acepta `next_action` / `next_action_due` |
| `GET /api/v1/analytics/pipeline` | Vivo. Retirarlo sería un breaking del contrato público (exigiría RFC); sigue siendo un corte legítimo de mercado |
| `GET /api/v1/eventos` | Vivo; su consumidor UI es ahora `/resumen` |
| `GET /api/v1/notifications` | Sin cambios (campana) |
