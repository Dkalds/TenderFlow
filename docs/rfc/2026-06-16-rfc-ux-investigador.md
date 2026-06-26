---
rfc: pendiente
title: "UX/KPIs · Investigador — fidelidad de filtros en búsqueda y citas/feedback del RAG"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: partially-implemented
area: web/investigador
---

## Contexto

`web/src/app/(dashboard)/investigador/page.tsx` es la página de búsqueda híbrida
(semántica + keyword, `alpha`) y RAG ("ask" con streaming). Es potente: topK,
selección de modelo, ejemplos, historial. Pero la integración con los filtros tiene
un bug y al RAG le falta cierre de bucle.

1. **Los filtros globales se aplican parcialmente (silencioso).** Con
   `useGlobalFilters` activo (líneas 242-248) solo se manda el **primer** valor:
   ```ts
   if (globalFilters.ccaas.length > 0)       filterExtras.ccaa = globalFilters.ccaas[0];
   if (globalFilters.tecnologias.length > 0) filterExtras.tecnologia = globalFilters.tecnologias[0];
   ```
   Si seleccionaste 3 CCAAs, **se descartan 2** sin avisar. Y **no** se reenvían
   rango de fechas, CPV ni importe. El toggle "usar filtros globales" da una falsa
   sensación de filtrado.
2. **Por defecto, la búsqueda ignora los filtros** (`useGlobalFilters: false`): el
   usuario filtró el resto de la app, pero los resultados de búsqueda no lo
   reflejan, sin que sea evidente.
3. **RAG sin cierre de bucle.** El prompt pide citar `[EXP-...]`, pero (a) las citas
   no se enlazan al detalle, y (b) no hay feedback ("¿útil?") sobre la respuesta ni
   sobre los resultados, pese a que el proyecto tiene infraestructura de
   active-learning/feedback.
4. **Historial/config en `localStorage`** (consistente con otras páginas; menor).

> Todo vía API (`/api/v1/search`, `/api/v1/ask`) — §3.8. Reenviar más filtros es
> compatible con el endpoint si los soporta; si no, es aditivo (§3.5).

## Decisión

1. **Fidelidad de filtros.** Reenviar **todos** los valores seleccionados
   (multi-CCAA, multi-tecnología, rango de fechas, CPV, importe) a `/api/v1/search`,
   no solo `[0]`. Si el endpoint hoy solo acepta un valor, ampliarlo a listas.
   Indicar en UI qué filtros están activos sobre la búsqueda (chips), para que la
   relación sea explícita.
2. **Citas clicables en el RAG.** Parsear los `[EXP-...]` de la respuesta y
   enlazarlos al detalle de esa licitación (deep-link `?lic=`). Convierte la
   respuesta en navegable.
3. **Feedback de relevancia.** Pulgar arriba/abajo en resultados y en la respuesta
   RAG → alimentar el feedback/active-learning existente para mejorar ranking/modelo.
4. **Claridad del toggle.** Dejar evidente si la búsqueda está filtrada o no (no un
   flag escondido en settings); idealmente, por defecto coherente con el resto de la
   app.

**Qué NO se hace:**

- **No** se cambia el motor híbrido (alpha/embeddings/FAISS).
- **No** se mueve el historial a server en este RFC (se puede unificar con saved
  searches en otro).
- **No** se altera el contrato de streaming del `/ask`.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo | Cero trabajo | Filtros parciales silenciosos; RAG sin navegación ni feedback | Engaña y deja valor sin capturar |
| Solo arreglar el `[0]` | Rápido, corrige el bug | Deja citas/feedback fuera | Mínimo; se prefiere cerrar el bucle |
| Fidelidad de filtros + citas + feedback (elegida) | Búsqueda fiel y RAG accionable y mejorable | Endpoint puede requerir listas; feedback nuevo | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Tipos generados si `/search` acepta listas / feedback | Regenerar OpenAPI; tipar |
| §3.5 Pydantic v2 DTOs | **Aditivo**: filtros multi-valor en `/search`, endpoint de feedback | Cambio consciente |
| §3.8 Frontend vía API | Sin cambios de acceso; mismas rutas | — |
| §3.2 / §3.3 / §3.4 / §3.6 | Ninguno (feedback puede reusar tabla existente) | — |

## Plan de implementación

1. `api/routes/search.py` — aceptar listas de ccaa/tecnología + rango/CPV/importe.
2. `investigador/page.tsx` — reenviar todos los filtros; chips de filtros activos;
   citas `[EXP-...]` clicables; controles de feedback.
3. `api/routes/feedback.py` (existente) — registrar feedback de búsqueda/RAG.
4. Regenerar `@/generated/api`.
5. Tests: multi-CCAA llega completo al endpoint; cita enlaza al detalle; feedback
   persiste.

**Archivos de partida**: `investigador/page.tsx:54-69,223-269`,
`api/routes/search.py`, `api/routes/ask.py`, `api/routes/feedback.py`,
`services/investigador/`.
**Riesgo estimado**: bajo-medio. El cambio del endpoint a listas debe mantener
compatibilidad.
**Tiempo estimado**: 1-1.5 días.

## Acceptance criteria

- [ ] Todos los valores de filtro seleccionados se aplican a la búsqueda (no solo el primero).
- [ ] La UI muestra qué filtros están activos sobre la búsqueda.
- [ ] Las citas `[EXP-...]` del RAG enlazan al detalle de la licitación.
- [ ] Hay feedback de relevancia que persiste (búsqueda y RAG).
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend) en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

2026-06-25 — **Implementado (criterios #1 y #2).** Al investigar el #1 apareció un
bug peor que el descrito: la búsqueda posteaba a `/api/v1/search` (**inexistente**;
el endpoint real es `/api/v1/search/semantic`) → modo búsqueda **roto** (404), y
además mandaba solo `ccaas[0]`/`tecnologias[0]` a un endpoint que de todas formas
ignoraba todo filtro.

- **Endpoint arreglado y con filtros.** `SemanticSearchRequest` acepta `ccaa`/
  `tecnologia` (multi-valor), `fecha_desde`/`fecha_hasta`. Cuando hay filtros, el
  endpoint calcula `allowed_ids` vía nueva `LicitacionRepository.ids_for_filters`
  (multi-valor con `IN`, AND entre dimensiones, acotado) y `_run` **filtra antes de
  recortar a top_k** (ampliando el pool de candidatos) para no quedarse corto. Sin
  filtros, comportamiento idéntico al previo.
- **Frontend.** Corregido el path → `/api/v1/search/semantic`; se mandan **todos**
  los valores seleccionados (multi-CCAA/tecnología + rango de fechas), no `[0]`;
  chips de "Filtros activos" para que la relación sea explícita (no un flag oculto).
- **#2 Citas clicables** ya existían (`renderAnswer` enlaza `[EXP-...]` al detalle).

Tests: `ids_for_filters` (multi-valor, combinación AND, rango de fechas, cap) en
`tests/test_licitaciones_filters.py`; y a nivel endpoint en `tests/test_search_route.py`
(los filtros restringen a `allowed_ids`; sin filtros devuelve todos). Verde:
pytest/mypy/ruff/codespell + `tsc`/`eslint`/`vitest` (285); el scanner no añade
hallazgos.

**Diferido:** feedback de relevancia (👍/👎) sobre resultados y respuesta RAG (#3) —
alimentaría el active-learning; y threading de filtros al `/ask` (RAG), que hoy
sigue ignorándolos. El historial sigue en `localStorage` (menor, #4).
