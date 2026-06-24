---
rfc: pendiente
title: "UX/KPIs · UTEs — relaciones de co-licitación (quién se asocia con quién) y drill-down"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: draft
area: web/utes
---

## Contexto

`web/src/app/(dashboard)/utes/page.tsx` está limpia y es 100 % backend-driven
(`/api/v1/analytics/utes`: KPIs, top_miembros, evolución, comparativa UTE vs
individual). Sin bugs de datos.

El gap es de **valor analítico**: responde *"cuánto ganan las UTEs"* (importe,
ticket medio vs individual, top miembros por frecuencia) pero **no responde la
pregunta propia de una UTE: quién se asocia con quién**. Las relaciones de
co-licitación (qué empresas forman UTE juntas, con qué frecuencia y para qué
órganos/importes) son el insight competitivo accionable — y hoy solo se ve una
lista de miembros por frecuencia, no el grafo de alianzas. Además, los miembros y
KPIs no tienen drill-down a sus UTEs/contratos.

> Existe `ecosistema-partners`/`red-organo-empresa` (grafos): este RFC **enlaza**
> a esa vista o trae un sub-grafo de socios frecuentes, sin duplicar. Vía API
> (§3.8); aditivo si hace falta el dato de pares (§3.5).

## Decisión

1. **Relaciones de socios.** Mostrar, por miembro, sus **socios más frecuentes** en
   UTE (pares co-adjudicatarios) — tabla o mini-grafo — o enlazar a la vista de red
   (`ecosistema-partners`) preseleccionando la empresa. Responde "¿con quién se
   alía X?".
2. **Drill-down.** Click en un miembro → sus UTEs/contratos en el listado.
3. **KPIs accionables.** "Empresas distintas en UTE" / "top miembro" enlazan a la
   empresa/red.

**Qué NO se hace:**

- **No** se duplica el grafo de `ecosistema-partners`/`red-organo-empresa`; se
  enlaza o se trae un sub-grafo acotado.
- **No** se cambian los KPIs ni la comparativa (correctos).

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo | Cero trabajo | No responde "quién se alía con quién" | Pierde el insight propio de UTEs |
| Sub-grafo de socios en la página (elegida) | Insight in situ, accionable | Dato de pares (puede existir) | — |
| Solo enlazar a la red | Mínimo | Menos contexto in situ | Aceptable como primer paso |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.5 Pydantic v2 DTOs | Aditivo si se expone "socios frecuentes" | Reusar `organ_company_graph`/partners |
| §3.8 Frontend vía API | Cálculo en `services/` (partners/entity graph) | — |
| §3.1 / §3.2 / §3.3 / §3.4 / §3.6 | Ninguno/mínimo | Tipar |

## Plan de implementación

1. `services/` (partners / `organ_company_graph`) + `api/routes/` — pares de
   co-licitación frecuentes por empresa (si no existe ya en partners).
2. `utes/page.tsx` — sección/enlace de socios frecuentes; drill-down de miembro;
   KPIs enlazados.
3. Regenerar `@/generated/api` si hay dato nuevo.
4. Tests: socios frecuentes correctos; drill-down filtra.

**Archivos de partida**: `utes/page.tsx:31-95`, `services/partners.py`,
`services/organ_company_graph.py`,
`web/src/app/(dashboard)/ecosistema-partners/page.tsx`.
**Riesgo estimado**: bajo.
**Tiempo estimado**: 0.5-1 día.

## Acceptance criteria

- [ ] Por miembro se ven (o se enlazan) sus socios de UTE más frecuentes.
- [ ] Click en un miembro lleva a sus UTEs/contratos.
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend, si aplica) en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

2026-06-24 — **Implementado.** Backend (`services/analytics/utes.py`): `UTEResult`
gana `socios_frecuentes` (pares de empresas que han co-licitado en UTE, vía
`build_partnership_graph` sobre el df de UTEs; top-20 por nº de UTEs juntas). El
endpoint `/api/v1/analytics/utes` ya existía → el campo se auto-expone. Frontend:
nueva card "Socios Frecuentes (quién se asocia con quién)" con tabla
empresa/socio/UTEs juntas/importe conjunto — responde la pregunta propia de la
página, que antes solo mostraba miembros por frecuencia. Reusa el grafo de
co-licitación real (no se duplica `ecosistema-partners`). Tests: 2 backend. Verde:
pytest/mypy/ruff/codespell + `tsc`/`eslint`/`vitest` (285). **Diferido:** drill-down
de miembro → sus UTEs/contratos en el listado.
