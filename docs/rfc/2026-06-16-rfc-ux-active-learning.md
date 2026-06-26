---
rfc: pendiente
title: "UX/KPIs · Active Learning — cerrar el bucle (impacto en el modelo) y etiquetado multi-clase"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: partially-implemented
area: web/active-learning
---

## Contexto

`web/src/app/(dashboard)/active-learning/page.tsx` es una cola de etiquetado bien
hecha: `feedback/queue?strategy=uncertainty&limit=20`, stats (`total_labels`,
`pct_relevant`) y envío de feedback (`relevante` sí/no + nota). Funciona, pero al
bucle de active-learning le faltan dos cosas:

1. **El payoff es invisible.** Se ve cuántas etiquetas hay, pero no **qué efecto
   tienen**: versión del modelo actual, cuándo reentrena (`ML_TECH_AUTO_RETRAIN`
   existe), tendencia de métricas (F1/PR-AUC) antes/después. Sin ver el impacto,
   etiquetar se siente gratis y baja la motivación.
2. **Etiquetado binario.** Solo `relevante` sí/no. Pero el clasificador de
   tecnologías necesita saber **qué tecnología** (ver RFC de Tecnologías:
   `sin_clasificar`). Enrutar las no clasificadas aquí no captura la clase. Falta
   un modo de etiquetado multi-clase (asignar tecnología/módulo).
3. **Estrategia fija** `uncertainty` (línea 61): active-learning se beneficia de
   alternar estrategias (uncertainty/diversity/random baseline).

> Todo vía API (`/feedback/*`) — §3.8. Lo nuevo (impacto, multi-clase, estrategia)
> es aditivo (§3.5) sobre la infra de feedback/registry existente.

## Decisión

1. **Cerrar el bucle.** Mostrar versión del modelo, fecha del último reentreno, nº
   de etiquetas desde entonces y tendencia de métricas (del model registry / drift
   ya existentes). "Tu etiquetado movió F1 de X a Y."
2. **Etiquetado multi-clase.** Además de relevante sí/no, permitir asignar
   tecnología/módulo cuando el item viene de la cola de "sin clasificar"
   (integración con el RFC de Tecnologías).
3. **Selector de estrategia.** Exponer `strategy` (uncertainty/diversity/random) y,
   opcionalmente, el tamaño de lote.

**Qué NO se hace:**

- **No** se cambia el algoritmo de sampling ni el registry (se **exponen**).
- **No** se fuerza multi-clase si el item es del clasificador binario; es según el
  origen del item.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo | Cero trabajo | Bucle sin payoff visible; sin multi-clase | Desmotiva y no alimenta el clasificador de tech |
| Solo mostrar impacto | Motiva | Sigue binario | Parcial |
| Impacto + multi-clase + estrategia (elegida) | Cierra el bucle y nutre tech | Exponer registry/estrategia | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.5 Pydantic v2 DTOs | Aditivo (impacto/modelo, label multi-clase, strategy) | Cambio consciente |
| §3.8 Frontend vía API | Reusa `/feedback/*` + model registry | — |
| §3.1 / §3.2 / §3.3 / §3.4 / §3.6 | Ninguno/mínimo | Tipar |

## Plan de implementación

1. `api/routes/feedback.py` + model registry — exponer versión/reentreno/tendencia;
   aceptar etiqueta multi-clase y `strategy`.
2. `active-learning/page.tsx` — panel de impacto; modo multi-clase según origen;
   selector de estrategia.
3. Regenerar `@/generated/api`.
4. Tests: el panel refleja la versión/tendencia; multi-clase persiste la clase;
   strategy cambia la cola.

**Archivos de partida**: `active-learning/page.tsx:29-90`,
`api/routes/feedback.py`, `services/ml/` (registry/drift),
`web/src/app/(dashboard)/tecnologias/page.tsx` (integración).
**Riesgo estimado**: bajo-medio.
**Tiempo estimado**: 1-1.5 días.

## Acceptance criteria

- [ ] La página muestra el impacto del etiquetado (versión/modelo, reentreno, tendencia de métricas).
- [ ] Existe etiquetado multi-clase para items de "sin clasificar".
- [ ] La estrategia de sampling es seleccionable.
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend) en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

2026-06-25 — **Implementado (criterios #1 y #3).**

- **#1 Cerrar el bucle (impacto visible).** La card "Modelo de clasificación" solo
  mostraba recuentos de feedback (`total_labels`, `pct_relevant`), no el efecto en
  el modelo. Nuevo `db.model_registry.active_model_summary()` (compone
  `get_active` + `list_versions` + `feedbacks_since_last_train`; **todo desde la BD,
  no carga el modelo ML**) expuesto en `GET /api/v1/feedback/model-info`. El front
  añade a la card: versión activa, fecha de reentreno, métrica titular
  (pr_auc/f1/…) con **delta vs la versión anterior** (▲/▼), y nº de etiquetas
  desde el último reentreno. "Tu etiquetado movió la métrica de X a Y" deja de ser
  invisible.
- **#3 Selector de estrategia.** El endpoint `/feedback/queue` ya soportaba
  `uncertainty | random`, pero el front lo hardcodeaba a `uncertainty`. Ahora hay
  un selector (Incertidumbre / Aleatoria) que re-consulta la cola; la estrategia
  forma parte del `queryKey`.

Tests: `active_model_summary` (compone versión activa + histórico + feedbacks; y
caso sin modelo) en `tests/test_model_registry.py`. Verde:
pytest/mypy/ruff/codespell + `tsc`/`eslint`/`vitest` (285); el scanner no añade
hallazgos.

**Diferido (criterio #2: etiquetado multi-clase).** Asignar tecnología/módulo a
los items de la cola de "sin clasificar" requiere el contrato multi-clase en
`/feedback` y la integración con el RFC de Tecnologías; el etiquetado sigue siendo
binario (relevante sí/no) por ahora.
