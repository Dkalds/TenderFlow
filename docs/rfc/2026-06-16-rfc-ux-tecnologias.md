---
rfc: pendiente
title: "UX/KPIs · Tecnologías — cobertura del clasificador (sin_clasificar) accionable y bridge al listado"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: implemented
area: web/tecnologias
---

## Contexto

`web/src/app/(dashboard)/tecnologias/page.tsx` es la página analítica **mejor
construida** del set: el backend entrega cross-tabs **reales**
(`cross_organo`, `cross_geo`) y la propia página lo documenta —
*"Real tecnologia x organo heatmap (replaces the previous synthetic matrix)"*
(línea 223). Es el patrón correcto que otras páginas deberían adoptar (ver RFC de
Tendencias, cuyo heatmap sigue siendo sintético).

El gap aquí no es un bug sino un **hueco de producto**: la respuesta incluye
`sin_clasificar` (TecnologiasResponse, línea 66) — el nº de licitaciones que el
clasificador SAP **no pudo asignar** a una tecnología — pero está infrautilizado:

1. **La cobertura del clasificador no es un KPI de primer nivel.** `sin_clasificar`
   es la métrica de calidad central de una página de *clasificación*: ¿qué % del
   corpus queda sin tecnología? Hoy no hay una card "Cobertura del clasificador:
   X % clasificado / N sin clasificar" que lo haga visible.
2. **No hay acción sobre lo no clasificado.** Existe una página `active-learning`
   para etiquetar, pero desde Tecnologías no hay puente: ver y **etiquetar** las
   licitaciones sin clasificar (que alimentaría el reentrenamiento) no es posible.
   El bucle de mejora del modelo queda abierto.
3. **El detalle por tecnología no enlaza al listado.** El drill por tecnología
   (`/analytics/tecnologias/detail`) muestra items, pero sin puente al listado
   principal filtrado por esa tecnología (patrón análisis→registros que falta en
   varias páginas).

> Todo vía API (§3.8) y con cross-tabs ya correctas. Las mejoras son de
> exposición/accionabilidad; lo nuevo (cola de no-clasificadas) puede reusar la
> infraestructura de feedback/active-learning existente (§3.5 aditivo si hace falta).

## Decisión

Cerrar el **bucle de calidad de clasificación** y conectar análisis con acción.

1. **KPI de cobertura.** Card "Cobertura del clasificador": `% clasificado` y
   `N sin clasificar` (desde `sin_clasificar` / total), con color de alerta si la
   cobertura cae bajo un umbral. Es la métrica de salud del modelo en su propia
   página.
2. **Acción sobre no clasificadas.** Botón/enlace "Revisar sin clasificar" → la
   cola de `active-learning` (o un listado filtrado `tecnologia IS NULL`) para
   etiquetar, alimentando el reentrenamiento (`ML_TECH_AUTO_RETRAIN` ya existe).
3. **Bridge al listado.** El detalle por tecnología y las barras enlazan al listado
   principal filtrado por esa tecnología.
4. **Patrón de referencia.** Documentar este heatmap real como el patrón a replicar
   (link cruzado al RFC de Tendencias).

**Qué NO se hace:**

- **No** se toca el modelo de clasificación (es otro RFC); aquí se **expone** su
  cobertura y se facilita el etiquetado.
- **No** se rehacen los charts (son correctos).
- **No** se duplica la cola de active-learning; se enlaza.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo | Cero trabajo | La calidad del clasificador queda invisible y sin acción | Hueco de producto en su página clave |
| Solo mostrar `sin_clasificar` como número | Trivial | Sin acción ni bucle de mejora | Medio camino |
| Cobertura KPI + acción + bridge (elegida) | Hace visible y accionable la calidad; cierra el bucle | Enlace a active-learning / listado | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Mínimo (datos ya tipados) | — |
| §3.5 Pydantic v2 DTOs | Aditivo solo si la cola de no-clasificadas necesita endpoint nuevo | Reusar feedback/active-learning |
| §3.8 Frontend vía API | Sin cambios de acceso | — |
| §3.2 / §3.3 / §3.4 / §3.6 | Ninguno | — |

## Plan de implementación

1. `tecnologias/page.tsx` — KPI de cobertura desde `sin_clasificar`; botón "revisar
   sin clasificar" → active-learning/listado; enlaces de detalle/barras al listado.
2. `api/routes/feedback.py` / `active-learning` — asegurar un endpoint que liste
   `tecnologia IS NULL` priorizadas (si no existe).
3. Tests vitest: la card de cobertura calcula `% clasificado`; el botón navega a la
   cola; el bridge filtra por tecnología.

**Archivos de partida**: `tecnologias/page.tsx:64-156`,
`services/analytics/tecnologias.py`, `api/routes/feedback.py`,
`web/src/app/(dashboard)/active-learning/page.tsx`.
**Riesgo estimado**: bajo. Mayormente frontend + reuso de feedback.
**Tiempo estimado**: 0.5-1 día.

## Acceptance criteria

- [ ] Hay un KPI de cobertura del clasificador (% clasificado / N sin clasificar).
- [ ] Existe acción para revisar/etiquetar las no clasificadas (active-learning).
- [ ] El detalle por tecnología y las barras enlazan al listado filtrado.
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend) en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

2026-06-22 — **Implementado (cobertura + acción).** Backend
(`services/analytics/tecnologias.py`): `TecnologiasResult` gana `total`
(licitaciones en alcance = denominador exacto de cobertura). Frontend: nueva card
"Cobertura del clasificador" — `% clasificado = (total − sin_clasificar) / total`
+ `N sin clasificar`, con alerta ámbar si cae bajo 70% y botón "Revisar sin
clasificar" → `/active-learning`. Tests: +aserción backend de `total`, 4/4 verde;
mypy limpio; `tsc`/`eslint`/`vitest` (285) verde. **Diferido:** bridge del detalle
por tecnología / barras al listado filtrado (drill-down).
