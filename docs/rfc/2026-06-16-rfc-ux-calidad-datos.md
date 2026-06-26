---
rfc: pendiente
title: "UX/KPIs · Calidad de Datos — integridad completa (drops de escritura, fechas, tendencia, DLQ accionable)"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: draft
area: web/calidad-datos
---

## Contexto

`web/src/app/(dashboard)/calidad-datos/page.tsx` consume `/api/v1/analytics/quality`
y muestra: total de registros, completitud % por columna (CPV, importe, fecha,
título), cobertura NIF y módulo SAP, `dlq_count` y frescura del último scrape. Es
el dashboard de calidad — pero tiene **puntos ciegos** que los RFCs de integridad
backend (fechas, observabilidad de pérdida de filas, DLQ) dejan al descubierto:

1. **`dlq_count` infracuenta la pérdida real.** Per los RFCs de *observabilidad de
   pérdida de filas* y *DLQ de violaciones de integridad*: las adjudicaciones
   descartadas por `INSERT OR IGNORE` (violación de `CHECK`/FK) **no entran a la
   DLQ**. La card "DLQ" muestra N, pero las filas perdidas en el boundary de
   escritura no están en ese N. El dashboard de calidad **no ve** esa pérdida.
2. **Sin señal de consistencia de fechas.** El bug `DD/MM/YYYY` (RFC de
   normalización de fechas) no se refleja: la página mide NULLs (completitud) pero
   no **formato**. Una fila con fecha mal formada cuenta como "completa".
3. **Sin tendencia.** Las métricas son point-in-time. Un cambio de schema del PLACSP
   que dispare NULLs (justo lo que `parser_field_null_total` instrumenta en backend)
   no se ve como regresión; hace falta una serie temporal de completitud.
4. **`dlq_count` sin acción.** Es un número sin enlace para inspeccionar/reintentar
   la DLQ, pese a existir `dlq_retry.py` y el runbook `dlq-replay.md`.
5. **Sin desglose por fuente/conector.** Con múltiples conectores (PLACSP, TACRC) la
   calidad por fuente importa; hoy es agregada.

> Todo vía API (§3.8). Lo nuevo (drops de escritura, formato de fecha, tendencia)
> proviene de métricas que los RFCs backend ya producen; aquí se **exponen**
> (§3.5 aditivo en `/analytics/quality`).

## Decisión

Hacer de Calidad de Datos el **panel único de integridad**, alineado con las
métricas backend.

1. **Pérdida en el boundary de escritura.** Card "Filas descartadas (escritura)"
   desde `upsert_rows_dropped_total` (RFC de observabilidad). Que la pérdida
   silenciosa sea visible aquí, no solo en Prometheus.
2. **Consistencia de fechas.** KPI "% fechas en formato ISO" (o nº de no-ISO) por
   columna de fecha — detecta el `DD/MM/YYYY` legacy/regresión.
3. **Tendencia de completitud.** Mini-serie temporal de las métricas clave
   (completitud por columna, % no clasificado, drops) para ver mejoras/regresiones.
4. **DLQ accionable.** `dlq_count` enlaza a una vista de la DLQ (inspeccionar/
   reintentar) — apoyada en `list_unresolved`/`dlq_retry.py`.
5. **Desglose por fuente** (PLACSP/TACRC) cuando aplique.

**Qué NO se hace:**

- **No** se recalculan métricas en el cliente; se consumen del backend.
- **No** se implementa el replay desde esta página (solo enlaza a la vista/herramienta).
- **No** se duplica `observabilidad` (Grafana): esta página es el resumen producto,
  no el panel de SRE.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo | Cero trabajo | Punto ciego de pérdida de escritura y formato; sin tendencia ni acción | Un dashboard de calidad que no ve parte de la pérdida |
| Solo añadir la card de drops | Rápido | Deja fechas/tendencia/DLQ fuera | Parcial |
| Panel de integridad completo (elegida) | Una sola fuente de verdad de calidad, accionable | Requiere exponer métricas nuevas en `/quality` | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Tipos generados (drops, formato, serie) | Regenerar OpenAPI; tipar |
| §3.5 Pydantic v2 DTOs | **Aditivo** en `/analytics/quality` | Cambio consciente; regenerar cliente |
| §3.8 Frontend vía API | Sin acceso directo a db | `services/analytics/quality.py` |
| §3.2 / §3.3 / §3.4 / §3.6 | Ninguno | — |

## Plan de implementación

1. `services/analytics/quality.py` + `api/routes/analytics.py` — exponer
   `upsert_rows_dropped`, % fechas no-ISO, serie temporal de completitud, desglose
   por fuente.
2. `calidad-datos/page.tsx` — cards/serie nuevas; `dlq_count` enlaza a vista de DLQ.
3. (Coordinar con) los RFCs backend de observabilidad/DLQ/fechas que producen los datos.
4. Regenerar `@/generated/api`.
5. Tests vitest: las cards reflejan las métricas; el enlace de DLQ navega.

**Archivos de partida**: `calidad-datos/page.tsx:27-115`,
`services/analytics/quality.py`, `observability/runtime_metrics.py`,
`db/dlq.py` (`list_unresolved`), `api/routes/analytics.py`.
**Riesgo estimado**: bajo-medio. Depende parcialmente de los RFCs backend de
métricas; las cards pueden landear incrementalmente.
**Tiempo estimado**: 1-1.5 días (tras/junto a las métricas backend).

## Acceptance criteria

- [ ] La página muestra filas descartadas en escritura (no solo `dlq_count`).
- [ ] Hay un indicador de consistencia de formato de fecha (no solo completitud).
- [ ] Hay tendencia temporal de las métricas de calidad clave.
- [ ] `dlq_count` enlaza a una vista para inspeccionar/reintentar la DLQ.
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend) en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

2026-06-25 — **Implementado (criterios #2 y parte de #1/#4).** Dos puntos ciegos
del panel, ambos del tipo "dato fabricado" (ADR-014):

1. **`dlq_count` era un stub fijo en 0.** `services/analytics/quality.py::_dlq_count`
   devolvía literalmente `0`: la card "Dead Letter Queue" mostraba 0 fallos aunque
   la cola tuviera registros (incluidas las violaciones de integridad de
   adjudicaciones que ya se enrutan a la DLQ). Ahora consulta la cola real vía
   nueva `db.dlq.count_unresolved()` (`COUNT(*)` con la misma condición que
   `list_unresolved`), best-effort (cae a 0 si la tabla no está). Cubre el grueso
   de #1 (la pérdida en escritura de adjudicaciones ya entra a la DLQ) y la base de
   #4.
2. **Sin señal de FORMATO de fecha (#2).** `pct_fecha` mide completitud (no nulos),
   así que una fecha presente pero `DD/MM/YYYY` legacy contaba como "completa". Se
   añaden `pct_fecha_iso` y `fechas_no_iso` (sobre `fecha_publicacion` presente,
   patrón ISO-8601 `^\d{4}-\d{2}-\d{2}`) y una card "Consistencia de formato de
   fecha" que avisa (ámbar + badge) si hay no-ISO. Detecta el legacy/regresión que
   la completitud oculta.

Tests: `tests/test_analytics_quality.py` (5: formato vs completitud, dlq real,
dataset vacío, best-effort ante fallo de DLQ, todo-ISO) y `count_unresolved` en
`tests/test_dlq.py` (con `tmp_db`). Verde: pytest/mypy/ruff/codespell +
`tsc`/`eslint`/`vitest` (285); el scanner no añade hallazgos.

**Diferido:** enlace accionable de `dlq_count` a una vista de la DLQ para
inspeccionar/reintentar (#4, requiere ruta/página nuevas); card de
`upsert_rows_dropped_total` como tal (#1 métrica Prometheus — hoy la pérdida de
adjudicaciones ya es visible vía DLQ); tendencia temporal de completitud (#3,
requiere persistir histórico de métricas); desglose por fuente/conector (#5).
