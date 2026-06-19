---
rfc: pendiente
title: "UX/KPIs · Renovaciones — priorizar por riesgo de cambio (modelo de retención), no solo importe"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: draft
area: web/renovaciones
---

## Contexto

`web/src/app/(dashboard)/renovaciones/page.tsx` lista contratos adjudicados que
vencen pronto, con un endpoint bien hecho
(`/api/v1/competitive/renovaciones?months=...`) que ya trae la señal clave:
`riesgo_cambio` (predicción del modelo de retención, `retencion_model_version`),
`dias_restantes` y `fecha_fin_efectiva`. El subtítulo de la propia página enmarca
el valor: *"o los defiende el adjudicatario actual o se los disputa quien llegue
primero"* — es decir, **contestabilidad**, que es justo lo que `riesgo_cambio`
predice.

El problema: **la señal más decisiva no se usa para priorizar**.

1. Los 4 KPIs (líneas 111-117, 168-189) son `contratos`, `importe`, `vencen en 30
   días`, `empresas` — puros conteos/importe. Ninguno usa `riesgo_cambio`.
2. El ranking "Cartera en juego por empresa" (`topCartera`, líneas 119-129) ordena
   por **importe** únicamente. Un contrato de alto importe pero casi seguro de
   renovarse por el actual (riesgo bajo) no es oportunidad; uno de riesgo alto y
   vencimiento próximo sí — y el orden actual no lo distingue.
3. **`useQuery`, no `useFilteredQuery`** (línea 85): la página ignora los filtros
   globales (CCAA/CPV), así que no se puede enfocar en tu nicho.
4. KPIs sumados en cliente desde `limit=1000` (líneas 88, 111-117): el "importe en
   juego" puede truncarse si hay > 1000 vencimientos en la ventana.

> El dato ya viene del backend (modelo de retención). Falta usarlo para ordenar y
> resumir. Aditivo (§3.5) si se expone un score; consumo vía API (§3.8).

## Decisión

Reorientar Renovaciones a **oportunidad primero**, usando `riesgo_cambio`.

1. **Score de oportunidad.** Ordenar (y opcionalmente colorear) por una
   combinación de `riesgo_cambio × importe × urgencia(dias_restantes)`, en vez de
   solo importe. Calcularlo en backend para consistencia (o, si se hace en front,
   solo con campos ya presentes — sin DTO nuevo).
2. **KPIs de oportunidad.** Añadir/replantear: "Importe en juego en **alto riesgo**
   de cambio", "Oportunidades calientes (riesgo alto + ≤30 días)". Mantener los
   conteos como contexto.
3. **Respetar filtros globales.** Migrar a `useFilteredQuery` para CCAA/CPV (nicho),
   conservando el selector de horizonte (`months`) y la búsqueda por empresa.
4. **Totales del backend.** Que `importe en juego`/`contratos` vengan agregados del
   backend (no suma de `limit=1000` cliente).

**Qué NO se hace:**

- **No** se toca el modelo de retención (es otro RFC); aquí solo se **usa** su
  salida.
- **No** se elimina el ranking por importe; se añade el eje de riesgo.
- **No** se cambia el endpoint base (solo se enriquece con score/agregados).

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo (orden por importe) | Cero trabajo | Desaprovecha el modelo; prioriza contratos no contestables | El valor está en el riesgo |
| Score solo en frontend | Sin backend | Totales siguen client-side; lógica de score duplicable | OK como mínimo, pero los totales quedan truncados |
| Score + KPIs de riesgo + filtros + totales backend (elegida) | Prioriza oportunidad real; coherente con filtros | Agregados/score en backend | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Tipos generados si se añade score/agregados | Regenerar OpenAPI; tipar |
| §3.5 Pydantic v2 DTOs | **Aditivo**: `score_oportunidad`/agregados (si backend) | Cambio consciente; regenerar cliente |
| §3.8 Frontend vía API | Score/totales en `services/competitive/`; sin db directa | Endpoint enriquecido |
| §3.2 / §3.3 / §3.4 / §3.6 | Ninguno | — |

## Plan de implementación

1. `services/competitive/` + `api/routes/competitive.py` — score de oportunidad y
   agregados (importe/contratos por banda de riesgo) sobre el dataset completo.
2. `renovaciones/page.tsx` — `useFilteredQuery`; ordenar por score; KPIs de riesgo;
   resaltar oportunidades calientes; columna/sort de `riesgo_cambio`.
3. Regenerar `@/generated/api`.
4. Tests: orden por score (riesgo×importe×urgencia); KPI de alto riesgo; filtros
   globales aplican.

**Archivos de partida**: `renovaciones/page.tsx:81-129,167-189`,
`services/competitive/` (renovaciones), `services/ml/retencion_model.py` (solo
lectura), `api/routes/competitive.py`.
**Riesgo estimado**: bajo. Usa una señal ya disponible; agregados aditivos.
**Tiempo estimado**: 1 día.

## Acceptance criteria

- [ ] La lista/ranking se ordena por oportunidad (riesgo × importe × urgencia), no solo importe.
- [ ] Hay KPI de "importe en juego en alto riesgo" y de "oportunidades calientes".
- [ ] La página respeta los filtros globales (CCAA/CPV).
- [ ] Los totales vienen del backend, no de la suma de `limit=1000`.
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend) en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->
