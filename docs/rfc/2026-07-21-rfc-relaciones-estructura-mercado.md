---
rfc: pendiente
title: "UX · Relaciones → Estructura de mercado: del hairball a vistas orientadas a preguntas (concentración, ego-network, drill-down de arista)"
issue: pendiente (crear issue y renumerar)
author: agent:architect
date: 2026-07-21
status: draft
area: web/red-organo-empresa · web/ecosistema-partners · web/components/charts/force-graph · services/analytics
supersedes: >
  Continúa docs/rfc/2026-06-28-rfc-ux-grafos-red-partners.md (implemented), que
  arregló la *capa de render* del ForceGraph pero mantuvo el grafo global como
  protagonista y dejó diferido el drill-down de arista. Este RFC cambia la
  *propuesta de valor* de ambas páginas, no solo su estética.
---

## Contexto

La sección **Relaciones** tiene dos páginas que comparten el componente
[`force-graph.tsx`](../../web/src/components/charts/force-graph.tsx):

- [`red-organo-empresa`](../../web/src/app/(dashboard)/red-organo-empresa/page.tsx) — grafo bipartito órgano↔empresa (adjudicaciones reales).
- [`ecosistema-partners`](../../web/src/app/(dashboard)/ecosistema-partners/page.tsx) — grafo empresa↔empresa (UTE, comunidades Louvain).

El RFC de junio arregló los **datos** (aristas reales) y el RFC de 2026-06-28
arregló el **render** (fit, contención, leyenda, comunidades). Pese a eso, la
queja persiste: *"se ven muy feas las relaciones y no aportan mucho"*. El
diagnóstico es que el problema ya **no es de render sino de encuadre de producto**:
un grafo dirigido por fuerzas es un *hairball* donde la posición del nodo no
significa nada, así que no responde ninguna pregunta de negocio.

### Defectos concretos (de producto, no de datos ni de render)

1. **El grafo global es decorativo.** En un force layout la posición no codifica
   nada (salvo el split bipartito en X). El usuario no puede leer una decisión:
   sirve para un screenshot, no para "¿quién domina el Ministerio X?".
2. **Tres codificaciones visuales compiten.** Tamaño=importe, grosor=contratos,
   color=grupo/comunidad. El nodo visualmente dominante es el de más dinero, no el
   más conectado — engaña sobre quién es el actor central.
3. **Tres vistas redundantes del mismo set de aristas** en `red-organo-empresa`:
   grafo + matriz + tabla. Además la matriz es un top-10×top-10 recortado **en el
   cliente** ([page.tsx:122-134](../../web/src/app/(dashboard)/red-organo-empresa/page.tsx))
   y la tabla está capada a 30 filas ([:356](../../web/src/app/(dashboard)/red-organo-empresa/page.tsx)):
   no escala y el footer "N relaciones" miente sobre el total.
4. **Sin "trabajo a resolver".** Se aterriza en frío ante un grafo abstracto. Las
   preguntas reales de inteligencia de mercado — *¿quién es incumbente en este
   órgano?*, *¿qué tan cerrado es este comprador?*, *¿con quién armo UTE?* — no se
   responden en ninguna de las dos páginas.
5. **KPI "Densidad"** ([:142-143](../../web/src/app/(dashboard)/red-organo-empresa/page.tsx))
   es una métrica de teoría de grafos sin lectura accionable.
6. **Drill-down de arista pendiente.** El RFC previo lo dejó explícitamente fuera
   (§cierre): hoy click en arista solo navega a la empresa, no a *las licitaciones
   que sustentan la relación*.

## Decisión

Reconvertir ambas páginas de **"páginas de grafo"** a **"inteligencia de estructura
de mercado orientada a preguntas"**. El grafo se **degrada a ego-network** (una
entidad + sus vecinos — el único caso donde un node-link es legible) y el peso
analítico se mueve a métricas que hoy faltan y son lo más valioso del dato:
concentración/incumbencia, rankings y drill-down. Todo el cálculo nuevo va en
**backend** ([[ADR-014-integridad-analitica-frontend|ADR-014]]).

### A. Backend (aditivo)

1. **Concentración/incumbencia por órgano** — nueva función pura
   `services/organ_concentration.py::build_organ_concentration` + wrapper
   `services/analytics/red_organo_empresa.py::get_organ_concentration` +
   `GET /api/v1/analytics/organ-concentration`. Por órgano sobre el dataset
   completo: nº de proveedores distintos, importe/contratos totales, cuota del
   top-1 y CR3 (top-3), **HHI** (reusa la convención 0-10000 de
   `competitors._compute_hhi`) y una clasificación de **apertura**
   (`Abierto`<1500, `Moderado`<2500, `Cerrado`≥2500). Es el nuevo *hero* de
   Red Órgano-Empresa.
2. **Ego-network órgano↔empresa** — `get_organ_company_ego` +
   `GET /api/v1/analytics/organ-company-graph/ego?entity_type&entity_key`. Filtra
   el df al vecindario de la entidad y reusa `build_bipartite_graph` acotado a
   top-N vecinos. Devuelve el mismo `OrganCompanyGraphResult`.
3. **Drill-down de arista** (cierra la deuda del RFC previo) — `get_organ_company_edge`
   + `GET /api/v1/analytics/organ-company-edge?organo&empresa` → licitaciones que
   sustentan la relación (id, título, importe, fecha, url). Reusa el join a
   `licitaciones` ya presente en `load_raw_with_licitaciones`.
4. **Resúmenes de comunidad en partners** — campo aditivo `communities` en
   `PartnershipGraphResult` (id, tamaño, líder, importe total, top miembros),
   derivado de los nodos que ya traen `community`. Es el *hero* de Ecosistema Partners.

### B. Frontend

1. **`ForceGraph`**: nuevo `layout="ego"` + prop `centerId` (nodo central fijo,
   vecinos en anillo vía `forceRadial`, etiquetas visibles). Reusa zoom/drag/
   tooltip/leyenda. No rompe `bipartite`/`force`.
2. **Red Órgano-Empresa** → "Estructura de mercado por órgano": leaderboard de
   concentración (hero, con `StatusBadge` de apertura), selector de entidad
   (`SearchAutocomplete`), ego-network al seleccionar, y drill-down de arista en
   un `Sheet`. Se elimina el KPI "Densidad" y la matriz derivada en cliente.
3. **Ecosistema Partners** → "Partners y comunidades": cards por comunidad (hero),
   partner finder que enfoca el ego-network del partner elegido, se conservan los
   bar charts "Ganadores" y la tabla.

### C. Qué NO se hace

- **No** se cambia el origen/semántica de las aristas (siguen siendo adjudicaciones
  / UTEs reales).
- **No** se migra a canvas/WebGL: los ego-networks son de decenas de nodos.
- **No** se fabrica analítica en cliente: concentración, ego y comunidades salen
  del backend. El *focus* de un ego (qué subconjunto se muestra) es una operación
  de vista, no una derivación de relaciones/totales.
- **No** se fusionan las dos páginas ni se cambia la navegación (siguen como tabs).

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| Status quo | Es exactamente la queja: el grafo no aporta |
| Solo pulido del grafo (curvas, colores) | Maquilla el síntoma; el hairball sigue sin responder preguntas |
| Fusionar en una sola página con selector de modo | Los datos son genuinamente distintos (bipartito vs. co-licitación); forzaría una abstracción falsa |
| Disolver relaciones en las páginas de entidad | Correcto a futuro pero cambio de navegación mayor; fuera de alcance de esta iteración |
| Ego + concentración + drill-down (elegida) | Responde las preguntas reales, reusa el pipeline y cierra deuda del RFC |

## Impacto en invariantes (AGENTS.md §3 / ADR-014)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.5 Pydantic v2 DTOs | Nuevos DTOs de concentración/ego/edge; `communities` aditivo en partners | Campos nuevos, backward-compatible |
| §3.8 Frontend vía API / ADR-014 | **Refuerza**: concentración/HHI/comunidades se calculan en backend sobre el dataset completo; se elimina la matriz y la densidad derivadas en cliente | `check_frontend_invariants.py` (synthetic-graph sigue 0) |
| §3.1 Typing strict | Props nuevas de `ForceGraph`; tipos generados | Regenerar `@/generated/api` |
| §3.3 Migraciones | Ninguno (todo se calcula al vuelo) | — |

## Plan de implementación

1. Backend: `services/organ_concentration.py` (pura) + `get_organ_concentration`,
   `get_organ_company_ego`, `get_organ_company_edge` en `red_organo_empresa.py`;
   `communities` en `ecosistema_partners.py`. Rutas en `api/routes/analytics.py`.
2. `ForceGraph`: `layout="ego"` + `centerId` (`forceRadial`).
3. `red-organo-empresa/page.tsx`: leaderboard + selector + ego + drill-down; quitar
   densidad y matriz.
4. `ecosistema-partners/page.tsx`: community cards + partner-ego; conservar ganadores/tabla.
5. Regenerar `@/generated/api`.
6. Tests: backend (HHI/apertura sobre fixture, ego=vecindario, edge=licitaciones
   reales, communities) + componente (`layout="ego"` centra `centerId`).

**Riesgo**: medio (el grueso es frontend + 3 endpoints acotados y aditivos).

## Acceptance criteria

- [ ] `organ-concentration` devuelve por órgano HHI 0-10000, cuota top-1/CR3 y
      apertura; ordenado y acotado en backend.
- [ ] `organ-company-graph/ego` devuelve solo el vecindario de la entidad.
- [ ] `organ-company-edge` lista las licitaciones reales de la relación órgano×empresa.
- [ ] `partnership-graph` incluye `communities` (líder + top miembros por clúster).
- [ ] Red Órgano-Empresa muestra el leaderboard de concentración como hero; sin
      KPI "Densidad" ni matriz derivada en cliente; el ego-network reemplaza al
      grafo global; click en arista abre el drill-down.
- [ ] Ecosistema Partners muestra cards por comunidad; el partner elegido enfoca su ego.
- [ ] `ForceGraph layout="ego"` fija `centerId` al centro y coloca los vecinos alrededor.
- [ ] `python scripts/check_frontend_invariants.py` mantiene `synthetic-graph` en 0.
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make lint typecheck test-unit` (backend) en verde.

## Notas de review

<!-- 2026-07-21 agent:architect — borrador inicial -->
