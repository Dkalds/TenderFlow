---
rfc: pendiente
title: "UX/KPIs · Geografía — agregación de provincias en backend (no sample de 500) y drill-down"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: partially-implemented
area: web/geografia
---

## Contexto

`web/src/app/(dashboard)/geografia/page.tsx` está, en general, bien construida:
choropleth de España, barras y pie por CCAA, tabla de CCAAs y tabla de provincias.
El mapa, las barras, el pie y las filas de CCAA toggleaan el filtro global
(`toggleCcaa` → `useFilters`), y los KPIs (CCAA más activa, concentración top-3,
total CCAAs, mayor ticket medio) se calculan correctamente.

Pero la **tabla de Provincias tiene un bug de correctitud y consistencia**:

```tsx
// líneas 65-76 — NO usa useFilteredQuery
const { data: licData } = useQuery<LicitacionesResponse>({
  queryKey: ["licitaciones", "provinces"],
  queryFn: async () => {
    const res = await fetch("/api/v1/licitaciones?limit=500", { credentials: "include" });
    ...
  },
});
// líneas 144-159 — agrega provincias en el cliente desde ese sample
```

Dos problemas:

1. **Sample no representativo.** Solo trae las **500 licitaciones más recientes**
   (orden por defecto `fecha_publicacion DESC`) y agrega provincias en el cliente.
   La tabla no refleja el dataset completo: una provincia con mucha actividad
   histórica pero poca reciente aparece infrarrepresentada o ausente.
2. **Ignora los filtros globales.** Usa `useQuery` directo, **no**
   `useFilteredQuery`, así que —a diferencia de TODO lo demás en la página— no
   respeta la barra de filtros (rango, CCAA, CPV…). El usuario filtra por una CCAA
   y la tabla de provincias sigue mostrando el sample global de 500. Es
   incoherente y confunde.

Gaps menores de UX:

3. **Filas de provincia no clicables.** Las filas de CCAA filtran al click; las de
   provincia no (inconsistencia), y no hay filtro de provincia en el sistema global.
4. **KPIs sin drill-down** (patrón común a las páginas).
5. **Accesibilidad del mapa**: conviene confirmar navegación por teclado/lector en
   `SpainMap` (el proyecto ya hizo keyboard-nav en Sankey).

> La página consume vía API (§3.8). El arreglo principal mueve un cálculo del
> cliente al backend, reforzando el invariante.

## Decisión

1. **Agregación de provincias en el backend.** Exponer `by_provincia` (conteo +
   importe por provincia) en `/api/v1/analytics/geography` (o endpoint dedicado),
   calculado en `services/analytics/geography.py` sobre el dataset completo, y
   consumirlo con `useFilteredQuery` para que respete los filtros globales. Eliminar
   el `fetch("/api/v1/licitaciones?limit=500")` y la agregación client-side.

2. **Drill-down de provincia.** Filas de provincia clicables → navegan al listado
   filtrado por provincia (y por la CCAA activa si la hay). Si el sistema de
   filtros no tiene provincia, añadir el parámetro de forma consciente.

3. **KPIs accionables.** "CCAA más activa" / "mayor ticket medio" enlazan a la CCAA
   correspondiente con el filtro aplicado.

4. **A11y del mapa.** Verificar/añadir navegación por teclado y `aria-label` por
   región en `SpainMap`, consistente con el trabajo previo en Sankey.

**Qué NO se hace:**

- **No** se rehace el choropleth ni el sistema de color del mapa.
- **No** se añade un nivel municipal (fuera de scope; el dato es provincia/CCAA).
- **No** se cambian los KPIs existentes (se les añade enlace).

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Subir el `limit` del sample | Trivial | Sigue siendo sample, sigue ignorando filtros, transfiere todo el dataset al cliente | No corrige la raíz |
| Agregar provincias en backend con `useFilteredQuery` (elegida) | Correcto, coherente con filtros, ligero | 1 campo/endpoint nuevo | — |
| Mantener client-side pero usar `useFilteredQuery` sobre licitaciones | Respeta filtros | Sigue limitado por paginación; agrega en cliente datos pesados | Ineficiente y parcial |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Tipo generado nuevo (`by_provincia`) | Regenerar OpenAPI; tipar |
| §3.5 Pydantic v2 DTOs | **Aditivo**: `by_provincia` en el DTO de geography | Cambio consciente; regenerar cliente |
| §3.8 Frontend vía API | **Refuerza** — elimina el `fetch` crudo y la agregación en cliente | Cálculo en `services/analytics/geography.py` |
| §3.2 / §3.3 / §3.4 / §3.6 | Ninguno | — |

## Plan de implementación

1. `services/analytics/geography.py` + `api/routes/analytics.py` — añadir
   `by_provincia` (count + importe por provincia, respetando filtros).
2. `geografia/page.tsx` — reemplazar el `useQuery`/`fetch` de 500 por
   `useFilteredQuery` al nuevo dato; filas de provincia clicables; KPIs enlazados.
3. Regenerar `@/generated/api`.
4. `components/charts/spain-map.tsx` — revisar a11y (teclado + aria por región).
5. Tests vitest: la tabla de provincias respeta filtros; click navega filtrado;
   agregación coincide con el backend.

**Archivos de partida**: `geografia/page.tsx:64-76,144-174`,
`services/analytics/geography.py`, `api/routes/analytics.py`,
`components/charts/spain-map.tsx`.
**Riesgo estimado**: bajo. Sustituye un cálculo cliente por uno backend; aditivo.
**Tiempo estimado**: 1 día.

## Acceptance criteria

- [ ] La tabla de provincias usa agregación backend sobre el dataset completo y
      respeta los filtros globales (no un sample de 500).
- [ ] Las filas de provincia son clicables → listado filtrado.
- [ ] No queda `fetch("/api/v1/licitaciones?limit=500")` para agregación geográfica.
- [ ] `SpainMap` navegable por teclado con `aria-label` por región.
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend) en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

2026-06-22 — **Implementado (agregación backend).** Backend
(`services/analytics/geography.py`): `GeoResult` gana `by_provincia` (count +
importe por provincia) agregado sobre TODO el dataset filtrado. Frontend
(`geografia/page.tsx`): la tabla de provincias consume `data.by_provincia` vía la
query `useFilteredQuery` existente (respeta los filtros globales) en vez del
`fetch("/api/v1/licitaciones?limit=500")` + agregación cliente (eliminados ese
fetch y las interfaces muertas). Tests: +2 backend (agrega dataset completo;
respeta filtro de tecnología), mypy limpio; `tsc`/`eslint`/`vitest` (285) verde.
`check_frontend_invariants`: `large-limit` 3→2. **Diferido:** filas de provincia
clicables (drill-down, requiere filtro de provincia en el sistema global) y a11y
del `SpainMap`.
