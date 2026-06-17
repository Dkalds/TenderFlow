---
rfc: pendiente
title: "UX/KPIs · Competidores — trayectoria temporal, señales proactivas y coherencia de filtros"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: draft
area: web/competidores
---

## Contexto

`web/src/app/(dashboard)/competidores/page.tsx` es la página más completa del set:
KPIs (HHI con interpretación, % oferta única, top competidor), barras/pie/treemap
de cuota, scatter ticket-medio vs dependencia, heatmap CCAA×empresa, posicionamiento
baja vs ticket, estacionalidad, ranking de bajas, comparador radar de 2 empresas y un
Sheet de drill-down con 8 KPIs + contratos recientes + watch toggle. Además es
cuidadosa con los totales (el "Otros" del pie usa `data.importe_total` del backend,
no la suma del top-N — mejor que Órganos).

Los gaps son más finos y de **coherencia/proactividad**, no de profundidad:

1. **Inconsistencia de filtros.** El ranking de bajas
   (`/api/v1/competitive/bajas`) "honra `ccaa` global … pero el endpoint **ignora el
   resto de filtros**" (comentario líneas 126-127). El resto de la página respeta la
   barra completa; esa card no. Confunde al comparar.
2. **Drill-down CCAA incompleto.** El desglose "Actividad por CCAA" del Sheet
   (`drillDownCcaa`, líneas 352-357) se deriva de `data.heatmap_ccaa`, que está
   **recortado al top-10 empresas** (líneas 258-261). Para cualquier empresa fuera de
   ese top-10 el desglose sale vacío ("Sin desglose por CCAA"), aunque la empresa sí
   tenga actividad. La drill-down promete más de lo que entrega.
3. **Descriptiva, no proactiva.** Todo el análisis es estático: no hay **trayectoria
   temporal** por competidor (¿sube o baja?) ni **señales** ("nuevo entrante en tu
   CCAA", "X ganó cuota en tu nicho"). Hay watchlist de empresas, pero no alimenta
   alertas competitivas.
4. **Fechas crudas** (`ultima`, `fecha_adjudicacion.slice(0,10)`, líneas 808/915):
   robustez de formato (cruza con el RFC de normalización de fechas).

> Todo vía API tipada (§3.8). Las señales y el trend se calculan en
> `services/competitive/` (§3.5 aditivo) y pueden reutilizar la watchlist y
> `notifications`/`watchlist_feed` ya existentes.

## Decisión

Llevar Competidores de **análisis descriptivo** a **inteligencia accionable**,
arreglando primero las dos incoherencias.

1. **Coherencia de filtros.** Hacer que `/competitive/bajas` honre la barra de
   filtros completa (rango, CPV, etc.), no solo CCAA — o, si hay razón de
   rendimiento, **declararlo explícitamente** en la UI ("ranking global, no
   filtrado") en vez de un comentario en el código.
2. **Drill-down CCAA completo.** Servir el desglose por CCAA de la empresa desde el
   endpoint de perfil (`/competitive/empresas/{id}/perfil`), no del heatmap top-10,
   para que funcione con cualquier empresa de la tabla.
3. **Trayectoria temporal por competidor.** En el Sheet, mini-serie de
   contratos/importe por año (↑/↓) — señala si el competidor crece o decae.
4. **Señales proactivas.** Job/endpoint que detecta y lista, para las empresas/CCAA
   vigiladas: nuevos entrantes, saltos de cuota, rachas de adjudicación. Surface en
   un bloque "Movimientos" y, opcionalmente, en `notifications`.
5. **Fechas con `formatDate`.**

**Qué NO se hace:**

- **No** se rehacen los charts existentes (son correctos y ricos).
- **No** se duplica el maestro de empresas (esta página enlaza al perfil; ver RFC de
  Empresas para el cruce).
- **No** se implementa scoring predictivo de competidores (fuera de scope; los
  modelos predictivos tienen su propio RFC).

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo | Cero trabajo | Filtros incoherentes; drill-down vacío para no-top-10; sin proactividad | Gaps reales |
| Solo arreglar coherencia (1,2) | Rápido, alto valor/coste | Sigue siendo descriptiva | Mínimo necesario, pero deja valor sobre la mesa |
| Coherencia + trend + señales (elegida) | Coherente y proactiva; reusa watchlist/notifications | Señales requieren job + endpoint | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Tipos generados (perfil con CCAA, trend, señales) | Regenerar OpenAPI; tipar |
| §3.5 Pydantic v2 DTOs | **Aditivo**: CCAA en perfil, serie temporal, señales | Cambio consciente; regenerar cliente |
| §3.8 Frontend vía API | Cálculos en `services/competitive/`; sin acceso directo a db | Endpoints dedicados |
| §3.2 / §3.3 / §3.4 / §3.6 | Ninguno | — |

## Plan de implementación

1. `services/competitive/` + `api/routes/competitive.py` — `bajas` honra filtros
   completos; perfil incluye desglose CCAA y serie temporal; endpoint de señales
   sobre watchlist.
2. `competidores/page.tsx` — drill-down CCAA desde el perfil; mini-trend en el Sheet;
   bloque "Movimientos"; `formatDate`; etiqueta de scope si el ranking no se filtra.
3. Regenerar `@/generated/api`.
4. (Opcional) integrar señales en `notifications`/`watchlist_feed`.
5. Tests vitest + backend: drill-down CCAA no vacío para empresa no-top-10; bajas
   respeta filtros; señales detectan un nuevo entrante sintético.

**Archivos de partida**: `competidores/page.tsx:118-365,796-947`,
`services/competitive/`, `api/routes/competitive.py`,
`services/watchlist.py`, `api/routes/watchlist_feed.py`.
**Riesgo estimado**: medio — las señales añaden cómputo; conviene cachear/job.
**Tiempo estimado**: 2 días (coherencia 0.5 día; trend+señales el resto).

## Acceptance criteria

- [ ] El ranking de bajas respeta los filtros globales, o lo declara explícitamente en UI.
- [ ] El drill-down muestra desglose CCAA para cualquier empresa (no solo top-10).
- [ ] El Sheet muestra trayectoria temporal (↑/↓) del competidor.
- [ ] Existe un bloque de señales/movimientos sobre empresas/CCAA vigiladas.
- [ ] Fechas con `formatDate`.
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend) en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->
