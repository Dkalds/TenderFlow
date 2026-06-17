---
rfc: pendiente
title: "UX/KPIs · Órganos — totales reales (no sobre el top-50) y drill-down al listado"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: draft
area: web/organos
---

## Contexto

`web/src/app/(dashboard)/organos/page.tsx` es la página mejor construida del set:
búsqueda server-side con debounce, KPIs, barras top-20/top-15 clicables, treemap
órgano→tipo→importe, tabla completa con filas accesibles (teclado) y un Sheet de
drill-down rico (KPIs con lead-time mediano, top adjudicatarios, estacionalidad,
top-30 por score).

Pero tiene un **bug de correctitud de KPIs**. El propio comentario lo dice
(líneas 114-116): *"sin q el API devuelve solo el top-50 por actividad"*. Es
decir, `data.organos` es **el top-50**, no todos los órganos. Y dos KPIs se
calculan sumando esa lista truncada y se etiquetan como totales del dataset:

```tsx
// líneas 142-147 — denominador = suma de SOLO el top-50
const top10Concentration = (top10Count / totalCountDelTop50) * 100;
// líneas 149-152 — suma de SOLO el top-50, pero la card dice "Importe Total"
const totalImporte = items.reduce((s, i) => s + i.importe, 0);
```

Consecuencias:

1. **"Concentración Top 10" se sobreestima**: el denominador (suma del top-50) es
   menor que el total real, así que el % sale inflado.
2. **"Importe Total" se subestima**: ignora todo el importe de los órganos fuera
   del top-50; la card miente sobre la magnitud del mercado.

(En cambio "Total Órganos" sí usa `data.total_organos`, un conteo de backend —
correcto. El problema es solo en los dos agregados derivados de la lista parcial.)

Gaps de UX:

3. **Sin puente al listado.** El Sheet muestra analítica del órgano y enlaza cada
   licitación scoreada al PLACSP externo, pero no hay un "ver todas las
   licitaciones de este órgano en el listado" con el filtro de la app.
4. **`fecha_adjudicacion` se pinta cruda** (línea 701, `📅 {s.fecha_adjudicacion}`)
   sin `formatDate`: una fila legacy `DD/MM/YYYY` se ve inconsistente (cruza con
   el RFC de normalización de fechas).

> La página consume vía API (§3.8). El arreglo correcto mueve los totales al
> backend, donde ya se conoce el dataset completo.

## Decisión

1. **Totales reales desde el backend.** `/api/v1/analytics/organos` ya devuelve
   `total_organos`; añadir `importe_total` y `concentracion_top10` calculados sobre
   **todos** los órganos (no solo el top-50) en `services/analytics/organos.py`. El
   frontend muestra esos valores en vez de sumar `items`. (El top-50 sigue usándose
   para los charts/tabla, que sí son "top".)

2. **Drill-down al listado.** En el Sheet, acción "Ver licitaciones del órgano" que
   navega al listado (`investigador`/`detalle`) con el filtro de órgano aplicado
   (y respetando el rango si lo hubiera). Cierra el bucle análisis→acción.

3. **Formatear fechas.** Usar `formatDate` en `fecha_adjudicacion` (Sheet) para
   robustez ante datos legacy, consistente con el resto del frontend.

**Qué NO se hace:**

- **No** se trae la lista completa de órganos al cliente (seguiría siendo caro);
  los totales se calculan en backend y los charts se quedan en top-N.
- **No** se cambia la búsqueda server-side ni el treemap.
- **No** se aplican filtros globales al detalle del órgano (su historia completa es
  deseable); se evaluará el rango por separado.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Mantener sumas sobre el top-50 | Cero trabajo | KPIs incorrectos (concentración inflada, importe subestimado) | Engaña sobre la magnitud del mercado |
| Pedir todos los órganos y sumar en cliente | Sin endpoint nuevo | Transfiere todo el dataset; lento; sigue siendo cálculo de presentación | Ineficiente; va contra §3.8 |
| Totales en backend + drill-down (elegida) | Correcto, ligero, accionable | Campos DTO nuevos | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Tipos generados nuevos (`importe_total`, `concentracion_top10`) | Regenerar OpenAPI; tipar |
| §3.5 Pydantic v2 DTOs | **Aditivo** en el DTO de órganos | Cambio consciente; regenerar cliente |
| §3.8 Frontend vía API | **Refuerza** — los totales se calculan en backend | `services/analytics/organos.py` |
| §3.2 / §3.3 / §3.4 / §3.6 | Ninguno | — |

## Plan de implementación

1. `services/analytics/organos.py` + `api/routes/analytics.py` — `importe_total` y
   `concentracion_top10` sobre todos los órganos.
2. `organos/page.tsx` — usar los totales del backend en las KPI cards; acción "ver
   en listado" en el Sheet; `formatDate` en `fecha_adjudicacion`.
3. Regenerar `@/generated/api`.
4. Tests vitest: las cards de total reflejan el backend (no la suma del top-50);
   acción de drill-down navega con filtro de órgano.

**Archivos de partida**: `organos/page.tsx:110-152,511-732`,
`services/analytics/organos.py`, `services/analytics/organo_detail.py`,
`api/routes/analytics.py`.
**Riesgo estimado**: bajo. Agregados backend aditivos + un enlace.
**Tiempo estimado**: 0.5-1 día.

## Acceptance criteria

- [ ] "Importe Total" y "Concentración Top 10" reflejan el dataset completo (backend),
      no la suma del top-50.
- [ ] El Sheet permite navegar al listado filtrado por el órgano.
- [ ] `fecha_adjudicacion` se muestra con `formatDate`.
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend) en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->
