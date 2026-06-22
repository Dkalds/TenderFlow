---
rfc: pendiente
title: "Meta-RFC · Integridad analítica del frontend — el frontend no fabrica datos; backend = única fuente de verdad analítica"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: draft
graduates-to: ADR-014 (si se aprueba)
---

## Contexto

El barrido página-por-página del dashboard (25 RFCs `2026-06-16-rfc-ux-*`) no
encontró bugs aislados: encontró **5 patrones sistémicos** que se repiten porque el
frontend asume responsabilidades que son del backend. Este meta-RFC consolida los 5,
establece invariantes y —lo importante— añade **guardarraíles** para que no
reaparezcan. Complementa **ADR-013** (jerarquía de materializaciones analíticas en
backend), **ADR-007** (capa de servicios de dominio) y el invariante **AGENTS.md
§3.8** (frontend siempre vía API): §3.8 dice "consumí la API"; este RFC añade "y
**no fabriques** la analítica que la API no te dio".

### Patrón 1 — Dato sintético presentado como real *(el más grave; 5 páginas, mismo fix)*

El frontend **deriva granularidad o relaciones** que el backend no entregó, y las
pinta como dato real:

| Página | RFC | Qué se fabrica |
|---|---|---|
| Tendencias | `…-tendencias.md` | heatmap Mes×Estado = producto de marginales (distribución global × mes) |
| Calendario | `…-calendario.md` | conteos diarios = serie **semanal** ÷ 7 + fudge de día laborable |
| Resumen | `…-resumen.md` | "CCAA cubiertas" = `concentracion_top3 × 17` (concentración ≠ cobertura) |
| Red Órgano-Empresa | `…-red-organo-empresa.md` | aristas órgano↔empresa = "comparten CCAA" (no adjudicación real) |
| Ecosistema Partners | `…-ecosistema-partners.md` | aristas empresa↔empresa = co-ocurrencia en CCAA (no UTE/co-licitación) |

**Causa raíz única**: no existe (o no se consume) el endpoint que devuelve el
**cross-tab / grafo / agregado real**, así que el cliente lo improvisa desde datos
más gruesos. **Fix único**: el backend expone la tabla cruzada/grafo/agregado real
sobre el dataset completo; el frontend lo renderiza. *Referencia interna*: la página
de **Tecnologías** ya lo hizo bien — su código dice *"Real tecnologia x organo
heatmap (replaces the previous synthetic matrix)"*. Es el patrón a replicar.

### Patrón 2 — Agregación cliente sobre sample/lista parcial, etiquetada como total

| Página | RFC | Defecto |
|---|---|---|
| Geografía | `…-geografia.md` | provincias agregadas en cliente desde `licitaciones?limit=500` (sample, ignora filtros) |
| Órganos | `…-organos.md` | "Importe Total"/"Concentración" sumados sobre el **top-50** devuelto |
| Detalle | `…-detalle.md` | score mergeado desde un `scoring?limit=500` disjunto de la página |
| Proyectos/Módulos | `…-proyectos-modulos.md` | importe sumado por fila de módulo → doble conteo multi-módulo |

**Causa raíz**: el cliente suma una lista truncada/parcial y la presenta como total
del dataset. **Fix**: los **totales** se calculan en backend sobre el dataset
completo (distinct donde aplique); los charts siguen siendo "top-N".

### Patrón 3 — Estado de usuario en `localStorage` cuando necesita servidor

| Página | RFC | Defecto |
|---|---|---|
| Mi Watchlist | `…-mi-watchlist.md` | reglas + **frecuencia de alerta** en localStorage → las alertas nunca se envían |
| Detalle | `…-detalle.md` | "destacados" en localStorage (3ª watchlist) |
| Investigador | `…-investigador.md` | historial en localStorage |

**Causa raíz**: features con estado guardadas solo en cliente → sin sync entre
dispositivos y **sin** poder disparar trabajo server-side (alertas/email). **Fix**:
persistencia server-side (reusar `services/watchlist.py`/`saved_filters.py`);
localStorage solo como caché/migración.

### Patrón 4 — Hardcode que rompe en despliegue o driftea

| Página | RFC | Defecto |
|---|---|---|
| Observabilidad | `…-observabilidad.md` | `GRAFANA_URL = "http://localhost:3001"` → enlace roto en prod |
| Feature Flags | `…-feature-flags.md` | `LOCAL_FLAGS` hardcodeado → flags del backend invisibles |
| Administración | `…-administracion.md` | `MOCK_USERS` → gestión de usuarios falsa |

**Causa raíz**: listas/URLs/datos que el backend o el entorno deben proveer, fijados
en el frontend. **Fix**: config en runtime (env/endpoint `/meta`) y backend como
fuente; cero mock/hardcode en datos renderizados.

### Patrón 5 — Señales infrautilizadas y falta de drill-down

`renovaciones` no prioriza por `riesgo_cambio`; `tecnologias` no acciona
`sin_clasificar`; casi ninguna vista enlaza análisis→registros. **Causa raíz**:
datos disponibles que no se usan para priorizar/accionar. **Fix**: priorizar por las
señales disponibles; toda vista analítica enlaza a los registros que la sustentan.

## Decisión

Adoptar tres **invariantes de integridad analítica del frontend** y hacerlos
**verificables** en CI (no solo documentados).

### Invariantes (extensión de §3.8)

1. **El frontend no fabrica analítica.** Cross-tabs, grafos, agregados, totales y
   series temporales se calculan en **backend** sobre el dataset completo (distinct
   donde aplique). El frontend renderiza y compone; **nunca** deriva granularidad,
   relaciones ni totales que el endpoint no entregó. Si un valor es estimado, la UI
   lo **etiqueta** como "estimado" o lo oculta — nunca lo presenta como real.
2. **El estado de usuario es server-side.** Reglas, alertas, destacados y vistas
   guardadas persisten en servidor; `localStorage` solo caché/migración one-shot.
3. **Sin hardcode que el backend/entorno deben proveer.** Listas (flags, usuarios),
   URLs (Grafana) y datos vienen de API/config; prohibido `MOCK_*`/`localhost` en
   datos renderizados commiteados.

### Guardarraíles (prevención, no solo cura)

1. **Doc canónico**: nueva sección en `web/AGENTS.md` + `docs/frontend-data-invariants.md`
   con los 3 invariantes, los 5 anti-patrones (con ejemplos reales de este barrido) y
   el patrón correcto (Tecnologías).
2. **Check de CI** `scripts/check_frontend_invariants.py` (en el job `frontend`
   existente), con denylist de marcadores de alto valor y bajo falso-positivo:
   - `http://localhost` en `web/src/**` (excepto tests/comentarios).
   - `const MOCK_`/`const LOCAL_` arrays que alimenten render.
   - `localStorage`/`getJSON`/`setJSON` con keys de `*watchlist*`/`*rules*`/`*alert*`.
   - `?limit=(500|1000)` seguido de `.reduce(`/`.map(` (agregación cliente).
   - heurística de grafo sintético: construir `links`/`matrix` filtrando por
     `ccaa`/`co-occurrence`/`share`.
   El check **avisa** (warning) con allowlist por línea justificada, para no bloquear
   incrementalmente; se endurece a error por categoría a medida que las páginas se
   migran (igual que se hizo con el lint progresivo del frontend).
3. **Checklist de PR / nueva página**: "¿esta vista deriva analítica en cliente?
   Si sí, justificar o mover a backend." + "¿totales sobre dataset completo o sobre
   sample?".
4. **Contrato de endpoints analíticos**: una página analítica nueva consume un
   endpoint de agregado dedicado; no reconstruye desde el listado.

### Fix compartido del Patrón 1 (lo que pidió foco)

Los 5 casos se resuelven con **una forma de fix**, agrupable por capa:

- **Cross-tabs** (Tendencias Mes×Estado, Calendario día, Resumen CCAA): exponer
  agregados reales en `services/analytics/*` (`trends.py`, `overview.py`,
  `quality.py`) — idealmente un helper común `crosstab(rows, cols, measure)` +
  `daily_counts()` + `distinct_ccaa()`, construido **una vez** y reusado.
- **Grafos** (Red Órgano-Empresa, Ecosistema Partners): consumir
  `services/organ_company_graph.py` y `services/partners.py`/`entity_resolution.py`
  (ya existen) vía endpoints de grafo; el cliente deja de inferir aristas.

Secuenciarlos juntos amortiza el trabajo backend y permite borrar 5 derivaciones
cliente de una tacada.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Solo los 25 RFCs por página | Arregla instancias | Sin guardarraíl → el patrón reaparece en la página 26 | No ataca la causa |
| Guardarraíl como ADR directamente | Autoridad arquitectónica | Salta el ciclo RFC→review | Este meta-RFC **propone**; gradúa a ADR-014 al aprobarse |
| Lint duro (error) desde el día 1 | Máxima prevención | Bloquea hasta migrar 5+ páginas | Se prefiere warning→error progresivo (precedente del repo) |
| No hacer nada sistémico | Cero coste | Deuda recurrente; dato falso en herramienta de inteligencia | Inaceptable |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Helpers/endpoints nuevos en backend strict | Tipar; `scripts/check_*` con type hints |
| §3.5 Pydantic v2 DTOs | **Aditivo**: endpoints de cross-tab/grafo/agregado | Conscientes; regenerar cliente OpenAPI |
| §3.8 Frontend vía API | **Se refuerza y se amplía** (no fabricar analítica) | Doc + check de CI |
| §3.4 Auto-marking tests | Tests del check y de los nuevos agregados | Por nombre |
| §3.2 / §3.3 / §3.6 | Ninguno | — |

## Plan de implementación

1. **Documentar** los 3 invariantes: `web/AGENTS.md` + `docs/frontend-data-invariants.md`.
2. **CI guard**: `scripts/check_frontend_invariants.py` + paso en el job `frontend`
   (modo warning + allowlist).
3. **Backend compartido**: helpers de cross-tab/daily/distinct en `services/analytics/`
   y exposición de los grafos (`organ_company_graph`, `partners`).
4. **Migrar las 5 páginas de Patrón 1** a datos reales (cierra sus RFCs por página).
5. **Graduar a ADR-014** "Integridad analítica del frontend" en `docs/adr/` tras review.
6. Iterar Patrones 2-5 vía sus RFCs por página, ya bajo el invariante.

**Archivos de partida**: `web/AGENTS.md`, `docs/frontend-data-invariants.md` (nuevo),
`scripts/check_frontend_invariants.py` (nuevo), `.github/workflows/ci.yml` (job
`frontend`), `services/analytics/*`, `services/organ_company_graph.py`,
`services/partners.py`, y los 25 RFCs `docs/rfc/2026-06-16-rfc-ux-*.md`.
**Riesgo estimado**: medio — el grueso es backend aditivo (agregados/grafos) + un
check de CI; el riesgo está en no romper páginas al quitar las derivaciones cliente
(mitigado migrando una a una con tests).
**Tiempo estimado**: 1 día (doc + check) + 3-4 días (5 agregados/grafos backend y migración).

## Acceptance criteria

- [ ] `docs/frontend-data-invariants.md` y la sección en `web/AGENTS.md` documentan los 3 invariantes y los 5 anti-patrones con ejemplos.
- [ ] `scripts/check_frontend_invariants.py` corre en CI y detecta: `localhost` hardcodeado, `MOCK_/LOCAL_` arrays de datos, `localStorage` de reglas/alertas, `limit=500/1000`+agregación, grafo por CCAA.
- [ ] Las 5 páginas de Patrón 1 consumen cross-tabs/grafos reales del backend; cero derivación sintética cliente.
- [ ] Existe (o está planificado) el ADR-014 que registra el invariante.
- [ ] `make lint && make typecheck && make test-unit` y `npm run typecheck && npm run lint && npm test` (web) en verde.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->
<!-- Decisión de producto/arquitectura: aprobar el invariante habilita el ADR-014 y el check de CI. -->

2026-06-22 — **Implementado (parcial, guardarraíles).** Graduado a
[ADR-014](../adr/ADR-014-integridad-analitica-frontend.md). Entregado: doc canónico
`docs/frontend-data-invariants.md`, sección en `web/AGENTS.md`, check
`scripts/check_frontend_invariants.py` (modo aviso, detecta las 5 categorías; 13
hallazgos reales pendientes en 9 páginas), target `make check-frontend-invariants`,
y allowlist `fdi-allow` en el fallback SSR de `web/src/lib/api-client.ts`. **Pendiente:**
wiring del check al job `frontend` de CI (requiere OK humano §6) y migración de las
páginas de Patrón 1 (se cierran vía sus RFCs por página).
