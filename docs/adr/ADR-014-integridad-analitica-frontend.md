---
id: ADR-014
title: "Integridad analítica del frontend"
status: accepted
date: 2026-06-22
deciders: "Daniel Kalitovics"
related:
  - "[[ADR-007-services-domain-layer]]"
  - "[[ADR-013-jerarquia-materializaciones-analiticas]]"
  - "[[2026-06-16-rfc-meta-integridad-analitica-frontend]]"
tags: [adr]
---

# ADR-014 — Integridad analítica del frontend

* **Estado:** Aceptado
* **Fecha:** 2026-06-22
* **Deciders:** Daniel Kalitovics
* **Relacionados:** [[ADR-007-services-domain-layer|ADR-007]] (capa de servicios de dominio), [[ADR-013-jerarquia-materializaciones-analiticas|ADR-013]] (jerarquía de
  materializaciones analíticas), AGENTS.md §3.8 (frontend siempre vía API)
* **RFC origen:** [[2026-06-16-rfc-meta-integridad-analitica-frontend|docs/rfc/2026-06-16-rfc-meta-integridad-analitica-frontend.md]]

## Contexto

Un barrido página-por-página del dashboard (25 RFCs `2026-06-16-rfc-ux-*`) no
encontró bugs aislados sino **5 patrones sistémicos** que se repiten porque el
frontend asume responsabilidades que son del backend:

1. **Dato sintético presentado como real** — el cliente deriva granularidad o
   relaciones que el backend no entregó (heatmap Mes×Estado por producto de
   marginales; conteos diarios = serie semanal ÷ 7; "CCAA cubiertas" =
   `concentracion_top3 × 17`; aristas de grafo por "comparten CCAA").
2. **Agregación cliente sobre sample/lista parcial etiquetada como total** —
   sumar `?limit=500` o el top-50 y presentarlo como total del dataset.
3. **Estado de usuario en `localStorage` cuando necesita servidor** — reglas y
   frecuencias de alerta que ningún job puede leer → las alertas nunca se envían.
4. **Hardcode que rompe en despliegue** — `GRAFANA_URL="http://localhost:3001"`,
   `LOCAL_FLAGS`, `MOCK_USERS`.
5. **Señales infrautilizadas y falta de drill-down** — datos disponibles que no se
   usan para priorizar/accionar.

El invariante **§3.8** ("frontend siempre vía API") es necesario pero
insuficiente: una página puede consumir la API y aun así **fabricar** la analítica
que la API no le dio. Hace falta el corolario y un guardarraíl verificable.

## Decisión

Adoptar tres **invariantes de integridad analítica del frontend**, extensión
operativa de §3.8, y hacerlos **verificables en CI** (no solo documentados).

1. **El frontend no fabrica analítica.** Cross-tabs, grafos, agregados, totales y
   series temporales se calculan en **backend** sobre el dataset completo (distinct
   donde aplique). El frontend renderiza y compone; nunca deriva granularidad,
   relaciones ni totales que el endpoint no entregó. Si un valor es estimado, la UI
   lo etiqueta como "estimado" o lo oculta — nunca lo presenta como real.
2. **El estado de usuario es server-side.** Reglas, alertas, destacados y vistas
   guardadas persisten en servidor; `localStorage` solo caché/migración one-shot.
3. **Sin hardcode que el backend/entorno deben proveer.** Listas (flags, usuarios),
   URLs (Grafana) y datos vienen de API/config; prohibido `MOCK_*`/`LOCAL_*`/
   `localhost` en datos renderizados commiteados.

### Guardarraíles

* **Doc canónico:** [docs/frontend-data-invariants.md](../frontend-data-invariants.md)
  (3 invariantes, 5 anti-patrones con ejemplos reales, patrón correcto de
  Tecnologías, checklist de PR) + sección en `web/AGENTS.md`.
* **Check de CI:** [scripts/check_frontend_invariants.py](../../scripts/check_frontend_invariants.py)
  escanea `web/src/**` y detecta las 5 categorías. Corre en **modo aviso**
  (no bloqueante) y se endurece a **error por categoría** a medida que las páginas
  se migran (precedente: el lint progresivo del frontend). Allowlist por línea con
  `fdi-allow`.
* **El patrón correcto** ya existe en la página de Tecnologías (cross-tabs reales
  `cross_organo`/`cross_geo`) y es el modelo a replicar.

### Consecuencias

* **Positivas:** una herramienta de inteligencia deja de mostrar dato fabricado;
  el guardarraíl evita la reaparición del patrón; el grueso del trabajo es backend
  aditivo (agregados/grafos) reutilizando servicios ya existentes.
* **Coste:** cada página de Patrón 1/2 requiere exponer un agregado/cross-tab/grafo
  real (cambio de DTO aditivo, §3.5) y regenerar el cliente OpenAPI; las páginas se
  migran una a una con tests para no romperlas.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| Solo arreglar los 25 RFCs por página | Sin guardarraíl, el patrón reaparece en la página 26 |
| Lint duro (error) desde el día 1 | Bloquea hasta migrar 5+ páginas; se prefiere warning→error progresivo |
| No hacer nada sistémico | Deuda recurrente; dato falso en una herramienta de inteligencia |

## Cumplimiento

* `make check-frontend-invariants` (o `python scripts/check_frontend_invariants.py`).
* Wiring al job `frontend` de `.github/workflows/ci.yml`: **pendiente de OK humano**
  (AGENTS.md §6 — edición de workflows), añadir como paso en modo aviso.
