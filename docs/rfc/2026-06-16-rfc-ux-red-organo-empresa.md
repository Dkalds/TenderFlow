---
rfc: pendiente
title: "UX/KPIs · Red Órgano-Empresa — grafo de adjudicaciones reales (no aristas inventadas por CCAA)"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: implemented
area: web/red-organo-empresa
---

## Contexto

`web/src/app/(dashboard)/red-organo-empresa/page.tsx` dibuja un grafo bipartito
órgano↔empresa. Pero **las aristas son inventadas**: se construyen por
**co-localización en la misma CCAA**, no por adjudicaciones reales. El propio
código lo dice (línea 101):

```ts
// Build relationships: organo↔empresa if they share CCAA
for (const organo of topOrganos) {
  const oCcaa = organoCcaa.get(organo.organo_contratacion);
  for (const empresa of topEmpresas) {
    if (!eCcaas?.has(oCcaa)) continue;     // ← une si comparten CCAA
    const cell = heatmap.find(h => h.empresa === empresa.nombre && h.ccaa === oCcaa);
    const count = cell?.count ?? 1;        // ← peso = actividad de la empresa en esa CCAA
    ...
  }
}
```

Consecuencia: el grafo muestra "Empresa X ↔ Órgano Y" porque **ambos operan en
Madrid**, no porque X haya ganado contratos de Y. Y el peso de la arista es la
actividad de la empresa en la CCAA, no el nº/importe de adjudicaciones de ese
órgano a esa empresa. Para una herramienta de inteligencia, esto es **engañoso**:
la premisa de una "red órgano-empresa" es la relación contractual real, y aquí se
fabrica desde el solapamiento regional. Es la versión "grafo" del anti-patrón de
dato sintético que aparece en otras páginas.

> Ya existe `services/organ_company_graph.py` (servicio de grafo órgano-empresa).
> El arreglo es consumir las aristas reales de ahí (§3.8), no derivarlas en cliente.

## Decisión

1. **Aristas reales de adjudicación.** Consumir el grafo órgano↔empresa real desde
   `services/organ_company_graph.py` vía un endpoint dedicado: una arista existe
   **solo si** la empresa fue adjudicataria de ese órgano, con peso = nº/importe de
   adjudicaciones reales. Eliminar `buildBipartiteData` por-CCAA del cliente.
2. **Respetar filtros y top-N en backend.** El subgrafo (top órganos/empresas) se
   acota en backend, coherente con los filtros globales.
3. **Interacción.** Click en nodo → detalle del órgano/empresa; click en arista →
   las licitaciones que la sustentan.

**Qué NO se hace:**

- **No** se mantiene la heurística de CCAA como fallback (induce a error); si no hay
  dato real, se muestra vacío/etiquetado, no inventado.
- **No** se rehace el componente `ForceGraph` (se le pasan datos reales).

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo (aristas por CCAA) | Cero backend | Relaciones falsas; peso equivocado | Engaña; rompe la premisa del grafo |
| Reconstruir adjudicaciones en cliente | Sin endpoint nuevo | El cliente no tiene el detalle órgano-empresa completo | Inviable/parcial |
| Grafo real desde `organ_company_graph` (elegida) | Veraz, con pesos reales, accionable | Endpoint nuevo (o reuso) | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Tipos generados (nodos/aristas reales) | Regenerar OpenAPI; tipar |
| §3.5 Pydantic v2 DTOs | **Aditivo**: endpoint de grafo órgano-empresa | Cambio consciente |
| §3.8 Frontend vía API | **Refuerza** — elimina la derivación en cliente | `services/organ_company_graph.py` |
| §3.2 / §3.3 / §3.4 / §3.6 | Ninguno | — |

## Plan de implementación

1. `api/routes/` — exponer el grafo de `services/organ_company_graph.py` (nodos +
   aristas de adjudicación con peso real, top-N acotado y filtros).
2. `red-organo-empresa/page.tsx` — consumir el grafo real; eliminar
   `buildBipartiteData` por-CCAA; interacción nodo/arista → detalle/listado.
3. Regenerar `@/generated/api`.
4. Tests: una arista existe solo con adjudicación real; peso = nº/importe reales;
   sin aristas inventadas por CCAA.

**Archivos de partida**: `red-organo-empresa/page.tsx:72-154`,
`services/organ_company_graph.py`, `api/routes/` (nuevo/endpoint),
`components/charts/force-graph.tsx`.
**Riesgo estimado**: bajo-medio. El servicio existe; falta exponerlo/consumirlo.
**Tiempo estimado**: 1 día.

## Acceptance criteria

- [ ] Las aristas órgano↔empresa representan adjudicaciones reales (no CCAA compartida).
- [ ] El peso de la arista = nº/importe de adjudicaciones reales.
- [ ] Click en nodo/arista lleva a detalle/listado correspondiente.
- [ ] No queda derivación de relaciones por CCAA en el cliente.
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend) en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

2026-06-24 — **Implementado.** Backend: `services/analytics/red_organo_empresa.py`
(wrapper sobre `build_bipartite_graph`, que ya existía pero no estaba expuesto) +
endpoint `GET /api/v1/analytics/organ-company-graph` (filtro CCAA + top-N en
backend). Las aristas son **adjudicaciones reales** (órgano → empresa adjudicataria,
peso = nº contratos + importe + frecuencia anual), no co-localización por CCAA.
Frontend: eliminado `buildBipartiteData` (aristas "share CCAA") y la matriz por
co-ocurrencia geográfica; el grafo, la matriz (contratos reales) y la tabla
consumen las aristas reales del endpoint. KPIs desde totales del backend. Tests: 3
backend (aristas reales, min_contratos, vacío). Verde: pytest/mypy/ruff/codespell +
`tsc`/`eslint`/`vitest` (285). `check_frontend_invariants`: `synthetic-graph` 2→1.
**Diferido:** click en nodo/arista → detalle/listado (drill-down; `ForceGraph` ya
expone `onNodeClick`, falta destino de navegación con filtro).
