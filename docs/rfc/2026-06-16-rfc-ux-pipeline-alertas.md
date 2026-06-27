---
rfc: pendiente
title: "UX/KPIs · Pipeline/Alertas — alertas reales suscribibles y clarificar IA vs renovaciones/calendario"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: partially-implemented
area: web/pipeline-alertas
---

## Contexto

`web/src/app/(dashboard)/pipeline-alertas/page.tsx` es el tracker de oportunidades
por plazo: en plazo, vencen 7d/30d, upcoming, por horizonte/trimestre, scatter
urgencia-vs-valor y forecast de re-tendering. Es backend-driven y rico. Dos
problemas:

1. **"Alertas" en el nombre, pero es un panel pasivo.** Muestra urgencia
   (vencen_7d/30d, scatter) pero **no entrega alertas**: no hay suscripción ni
   notificación cuando una licitación de alto valor entra en plazo crítico. La
   promesa del nombre no se cumple — mismo hueco que `mi-watchlist` (reglas sin
   alerta real).
2. **Solapamiento de IA.** "Plazos/oportunidades que vienen" se reparte entre
   **pipeline-alertas** (tenders activos cerrando + forecast), **renovaciones**
   (contratos ganados que vencen) y **calendario** (vista calendario de plazos).
   Tres páginas en el mismo territorio; el usuario no sabe cuál es su "qué hago
   hoy".

> Existe infra de notificaciones/watchlist (`services/notifications.py`,
> `watchlist_feed`). Vía API (§3.8); la suscripción es aditiva (§3.5).

## Decisión

1. **Alertas reales suscribibles.** Permitir suscribirse a un criterio/umbral
   (p.ej. "alto valor venciendo en ≤7d en mi nicho") que dispare notificación
   (`notifications`/email) — reusando la misma infra que el RFC de Mi Watchlist.
   La página deja de ser solo visual.
2. **Clarificar IA.** Definir un rol claro por página y enlazarlas: pipeline-alertas
   = oportunidades **activas** cerrando + suscripción; renovaciones = **vencimientos
   de contratos ganados** (riesgo de cambio); calendario = vista temporal de plazos.
   Un encabezado en cada una y navegación cruzada que evite confusión.
3. **Drill-down.** Scatter/tablas enlazan al detalle de la licitación.

**Qué NO se hace:**

- **No** se fusionan las tres páginas (tienen ángulos distintos); se diferencian y
  enlazan.
- **No** se duplica el motor de alertas: se reusa el del RFC de Mi Watchlist.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo | Cero trabajo | "Alertas" que no alertan; IA confusa con 2 páginas más | No cumple la promesa |
| Solo renombrar | Trivial | Pierde la oportunidad de alertar de verdad | Cosmético |
| Alertas reales + IA clara (elegida) | Cumple la promesa; reusa infra | Suscripción + coordinación con Mi Watchlist | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.5 Pydantic v2 DTOs | Aditivo (suscripción de alerta) | Reusar el modelo del RFC de Mi Watchlist |
| §3.8 Frontend vía API | Reusa `notifications`/`watchlist_feed` | — |
| §3.3 Migraciones | Si la suscripción persiste, reusa la tabla del RFC Mi Watchlist | OK humano §6 |
| §3.1 / §3.2 / §3.4 / §3.6 | Ninguno/mínimo | Tipar |

## Plan de implementación

1. Coordinar con el RFC de Mi Watchlist (motor de reglas/alertas): exponer
   suscripción desde pipeline-alertas.
2. `pipeline-alertas/page.tsx` — botón "alertarme de esto"; encabezado de rol +
   enlaces a renovaciones/calendario; drill-down.
3. Tests: suscribir un criterio genera notificación; drill-down navega.

**Archivos de partida**: `pipeline-alertas/page.tsx:42-95`,
`services/notifications.py`, `api/routes/watchlist_feed.py`,
`renovaciones/page.tsx`, `calendario/page.tsx` (IA).
**Riesgo estimado**: bajo-medio (depende del motor de alertas del RFC Mi Watchlist).
**Tiempo estimado**: 1 día (sobre el motor de alertas existente).

## Acceptance criteria

- [ ] Se puede suscribir un criterio/umbral y recibir notificación real.
- [ ] Cada una de pipeline-alertas/renovaciones/calendario declara su rol y enlaza a las otras.
- [ ] Scatter/tablas enlazan al detalle.
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend) en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

**2026-06-27 — Implementado parcialmente (frontend puro, sin migración):**

- **Clarificar IA** (criterio 2) ✅: nuevo componente
  `web/src/components/pipeline-role-nav.tsx` declara el rol de
  pipeline-alertas / renovaciones / calendario y las enlaza entre sí; añadido a las
  tres páginas bajo su título.
- **Drill-down** (criterio 3) ✅: la lista de urgentes y la tabla de forecast enlazan
  al detalle (`/detalle?lic=…`); el scatter Urgencia×Valor navega al hacer click en un
  punto (`PipelineUrgencyScatter` con prop `onPointClick`).
- Test: `web/src/components/__tests__/pipeline-role-nav.test.tsx`.

**Diferido** (criterio 1 — alertas reales suscribibles): requiere persistir la
suscripción server-side → **tabla nueva + migración Alembic (gated §6, OK humano)** +
job del scheduler, compartido con el RFC `ux-mi-watchlist`. No se aborda hasta aprobar
esa migración. Por eso el status es `partially-implemented`, no `implemented`.
