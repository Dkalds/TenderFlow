---
rfc: pendiente
title: "UX/IA · Licitadores vs Competidores — eliminar redundancia (mismo endpoint) o diferenciar propósito"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: draft
area: web/licitadores
---

## Contexto

`web/src/app/(dashboard)/licitadores/page.tsx` consume **el mismo endpoint** que
`competidores`: `/api/v1/analytics/competitors` (línea 74), con el mismo DTO
`CompetitorsData` (ranking, HHI, % oferta única, heatmap CCAA, estacionalidad).
Es una versión más ligera (tabs ranking/geografía/evolución) de `competidores`,
que además tiene radar, treemap, posicionamiento, drill-down, bajas, watch.

Esto es **redundancia de arquitectura de información**:

1. **Dos rutas para lo mismo.** El usuario no sabe cuál usar para "análisis de
   competidores"; ambas parten del mismo dato.
2. **Doble mantenimiento.** Cualquier mejora (p.ej. los arreglos del RFC de
   Competidores: coherencia de filtros, drill-down CCAA) hay que hacerla dos veces o
   diverge.
3. **Inconsistencia.** Las dos páginas pueden mostrar el mismo competidor con UX y
   capacidades distintas.

> No es un bug de datos sino de IA/producto. Sin cambios de backend necesarios.

## Decisión

Resolver la redundancia con una de dos vías (a decidir con el dueño de producto):

1. **Consolidar (preferida).** Hacer de `competidores` la única página de análisis
   competitivo y **redirigir** `licitadores` a ella (o convertir "licitadores" en
   una **vista/preset** dentro de competidores, p.ej. el ranking simple como tab).
   Elimina duplicación.
2. **Diferenciar.** Si se quieren dos páginas, darles **propósitos distintos y
   explícitos**: p.ej. `competidores` = estructura de mercado (HHI, posicionamiento)
   y `licitadores` = vista "bidder-first" accionable sobre **tu** nicho/watchlist
   (quién compite contigo). Cada una con su endpoint/parametrización propia, no el
   mismo crudo.

En ambos casos: enlazar claramente entre sí y evitar que el mismo dato se renderice
con dos UX divergentes.

**Qué NO se hace:**

- **No** se borra funcionalidad sin redirección/equivalencia (no romper enlaces
  guardados a `/licitadores`).
- **No** se duplican los arreglos del RFC de Competidores: se hacen una vez en la
  página canónica.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo (dos páginas iguales) | Cero trabajo | Confusión + doble mantenimiento + divergencia | Deuda de IA real |
| Consolidar en competidores (preferida) | Una fuente, menos mantenimiento | Hay que redirigir/avisar | — |
| Diferenciar por propósito | Dos ángulos útiles | Requiere endpoints/diseño distintos reales | Válida si producto los quiere ambos |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.8 Frontend vía API | Ninguno (misma API) | — |
| §3.1 / §3.2 / §3.3 / §3.4 / §3.5 / §3.6 | Ninguno | — |

## Plan de implementación

1. Decisión de producto: consolidar vs diferenciar.
2a. (Consolidar) `licitadores/page.tsx` → redirección a `competidores` (o tab/preset);
   actualizar la navegación (`layout`) y enlaces.
2b. (Diferenciar) redefinir el propósito de `licitadores` (bidder-first/nicho) con su
   propia parametrización; documentar la distinción en cada header.
3. Tests: la ruta `/licitadores` resuelve a la experiencia elegida sin romper deep-links.

**Archivos de partida**: `licitadores/page.tsx`, `competidores/page.tsx`,
`web/src/app/(dashboard)/layout.tsx` (navegación).
**Riesgo estimado**: bajo (frontend/IA); cuidar redirecciones y navegación.
**Tiempo estimado**: 0.5 día (consolidar) / 1-2 días (diferenciar).

## Acceptance criteria

- [ ] No hay dos páginas que rendericen el mismo `/analytics/competitors` con UX divergente.
- [ ] `/licitadores` redirige o tiene un propósito distinto y explícito.
- [ ] La navegación refleja la decisión; deep-links previos no se rompen.
- [ ] `npm run typecheck && npm run lint && npm test` (web) en verde.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->
<!-- Decisión consolidar vs diferenciar: requiere input del dueño de producto. -->

2026-06-22 — **Implementado (Consolidar).** Decisión de producto: **consolidar**.
`/licitadores` ahora redirige a `/competidores` (server-side `redirect()`), sin
romper deep-links. Eliminada la entrada "Licitadores" de la navegación
(`web/src/lib/navigation.ts`) y su icono `Medal` (import muerto). El análisis
competitivo vive solo en `competidores`; cualquier mejora futura se hace una vez.
Verde: `tsc`/`eslint`/`vitest` (19 files, 285 tests).
