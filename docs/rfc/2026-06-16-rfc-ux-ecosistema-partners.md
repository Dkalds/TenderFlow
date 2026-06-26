---
rfc: pendiente
title: "UX/KPIs · Ecosistema Partners — grafo de co-licitación real (UTE/co-adjudicación), no co-ocurrencia por CCAA"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: draft
area: web/ecosistema-partners
---

## Contexto

`web/src/app/(dashboard)/ecosistema-partners/page.tsx` dibuja un grafo de
"partners" entre empresas. Pero **las aristas no son de partnership real**: se
construyen por **co-ocurrencia en la misma CCAA**. El código lo dice (línea 112):

```ts
// Links: co-occurrence in same CCAA
for (...) {
  for (const [ccaa, countA] of mapA) {
    const countB = mapB.get(ccaa);
    if (countB) weight += Math.min(countA, countB);   // peso = solapamiento regional
  }
  if (weight > 0) links.push({ source, target, weight });
}
```

Consecuencia: dos empresas aparecen como "partners" porque **ambas operan en
Madrid**, no porque hayan **co-licitado** (formado UTE) nunca. Dos competidores
directos que se disputan los mismos contratos en la misma región mostrarían una
arista de "partner" fuerte — lo contrario de la realidad. En una página llamada
"Ecosistema Partners" esto es especialmente engañoso. Es el mismo anti-patrón de
grafo inventado que el RFC de Red Órgano-Empresa.

> El dato real existe: `services/partners.py`, `services/entity_resolution.py`
> (miembros de UTE) — la página de Empresas ya muestra `ute_miembros`/
> `participa_en_utes`. El grafo debe construirse desde co-adjudicación/UTE real
> (§3.8), no desde CCAA en el cliente.

## Decisión

1. **Aristas de co-licitación real.** Una arista empresa↔empresa existe **solo si**
   han co-licitado (UTE conjunta / co-adjudicación), con peso = nº de UTEs/contratos
   compartidos. Exponer ese grafo desde `services/partners.py`/`entity_resolution`
   y consumirlo; eliminar la co-ocurrencia por CCAA del cliente.
2. **Interacción.** Click en nodo → perfil de empresa; click en arista → las UTEs/
   contratos compartidos. Resaltado/búsqueda como ahora.
3. **Coherencia con UTEs.** Es el grafo que el RFC de UTEs propone enlazar; unificar
   la fuente.

**Qué NO se hace:**

- **No** se mantiene la co-ocurrencia CCAA como fallback (engaña); sin dato real →
  vacío/etiquetado.
- **No** se rehace `ForceGraph` (datos reales de entrada).

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo (co-ocurrencia CCAA) | Cero backend | "Partners" falsos; une competidores | Engaña; contradice el nombre de la página |
| Inferir UTEs en cliente | Sin endpoint | El cliente no tiene el grafo de UTE completo | Inviable |
| Grafo de co-licitación real (elegida) | Veraz y accionable | Endpoint nuevo (o reuso de partners) | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Tipos generados (grafo de partners real) | Regenerar OpenAPI; tipar |
| §3.5 Pydantic v2 DTOs | **Aditivo**: endpoint de grafo de co-licitación | Cambio consciente |
| §3.8 Frontend vía API | **Refuerza** — elimina derivación en cliente | `services/partners.py`/`entity_resolution.py` |
| §3.2 / §3.3 / §3.4 / §3.6 | Ninguno | — |

## Plan de implementación

1. `api/routes/` — exponer el grafo de co-licitación (nodos empresa + aristas UTE/
   co-adjudicación con peso real) desde `services/partners.py`/`entity_resolution.py`.
2. `ecosistema-partners/page.tsx` — consumir el grafo real; eliminar
   `buildGraphData` por-CCAA; interacción nodo/arista.
3. Regenerar `@/generated/api`.
4. Unificar con el enlace propuesto en el RFC de UTEs.
5. Tests: arista solo con co-licitación real; peso correcto; sin aristas por CCAA.

**Archivos de partida**: `ecosistema-partners/page.tsx:65-160`,
`services/partners.py`, `services/entity_resolution.py`, `api/routes/`,
`components/charts/force-graph.tsx`.
**Riesgo estimado**: bajo-medio. El dato de UTE existe; falta el grafo expuesto.
**Tiempo estimado**: 1-1.5 días.

## Acceptance criteria

- [ ] Las aristas representan co-licitación real (UTE/co-adjudicación), no CCAA compartida.
- [ ] El peso = nº de UTEs/contratos compartidos.
- [ ] Click en nodo/arista lleva a empresa/UTEs/contratos.
- [ ] No queda derivación de partners por CCAA en el cliente.
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend) en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

2026-06-24 — **Implementado.** Backend: `services/analytics/ecosistema_partners.py`
(wrapper sobre `build_partnership_graph`, que ya existía sin endpoint) + endpoint
`GET /api/v1/analytics/partnership-graph` (filtro CCAA + top-N en backend). Las
aristas empresa↔empresa salen de **co-licitación real** (UTE conjunta, parseada del
`nombre` vía `parse_ute_members`), peso = nº de UTEs compartidas + importe — no
co-ocurrencia por CCAA. Frontend: eliminado `buildGraphData` (links "co-occurrence
in same CCAA"); el grafo de la pestaña "Red de Partners" consume el endpoint real
(query separada con los sliders como `top_nodes`/`min_contratos`). El resto de la
página (KPIs, tabla, Ganadores) sigue con datos reales de `competitors`. Tests: 3
backend (aristas UTE reales, min_contratos, vacío sin UTEs). Verde:
pytest/mypy/ruff/codespell + `tsc`/`eslint`/`vitest` (285). `check_frontend_invariants`:
`synthetic-graph` 1→**0** (cerrados los dos grafos sintéticos). **Diferido:** click
en nodo/arista → perfil/UTEs (drill-down); unificación con el RFC de UTEs.
