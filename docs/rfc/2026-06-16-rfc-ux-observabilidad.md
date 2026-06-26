---
rfc: pendiente
title: "UX/KPIs · Observabilidad — URL de Grafana por config (no localhost), salud en vivo y rol vs calidad-datos"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: partially-implemented
area: web/observabilidad
---

## Contexto

`web/src/app/(dashboard)/observabilidad/page.tsx` muestra health checks (status,
versión, uptime, componentes redis/db/disk), `dlq_count` y enlaces a Grafana.
Problemas:

1. **URL de Grafana hardcodeada a localhost.** `const GRAFANA_URL =
   "http://localhost:3001"` (línea 48). En cualquier despliegue (staging/prod) ese
   enlace apunta al **localhost del propio usuario**, no al Grafana del servidor →
   **enlace roto**. Es un bug de configuración real (cruza con la deuda de
   `next.config`/env ya conocida en el repo).
2. **Salud point-in-time con refresco manual.** Una página de salud debería
   auto-refrescar (o stream); hoy hay que recargar. El proyecto ya tiene SSE
   (`api/routes/stream.py`).
3. **Solapamiento con calidad-datos.** Ambas muestran `dlq_count`; los roles
   (SRE/infra vs calidad de dato) conviene separarlos y enlazarlos (ver RFC de
   Calidad de Datos).

> Vía API (`/health`, `/quality`) — §3.8. La URL de Grafana debe venir de config
> (env/endpoint), no hardcodeada.

## Decisión

1. **Grafana por configuración.** Tomar la URL de Grafana de una variable de
   entorno/endpoint de config en runtime (p.ej. `NEXT_PUBLIC_GRAFANA_URL` o un
   `/api/v1/meta` que la exponga), con fallback que **oculte** el enlace si no está
   configurada, en vez de mostrar un localhost roto.
2. **Salud en vivo.** Auto-refresco (polling corto o SSE) del health; indicar la
   hora del último check y permitir refresh manual.
3. **Rol claro vs calidad-datos.** Observabilidad = salud de infra/SRE; calidad-datos
   = integridad del dato. Encabezados y enlaces cruzados; `dlq_count` enlaza a la
   vista de DLQ (consistente con el RFC de Calidad de Datos).

**Qué NO se hace:**

- **No** se reimplementa Grafana dentro de la app.
- **No** se duplican métricas de calidad-datos; se enlaza.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo (localhost hardcode) | Cero trabajo | Enlace roto fuera de local | Bug en despliegue |
| Hardcodear la URL de prod | Trivial | Frágil entre entornos | Mismo problema desplazado |
| URL por config + salud en vivo (elegida) | Funciona en todos los entornos; salud útil | Var de entorno/endpoint nuevos | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.8 Frontend vía API | La config se expone por env/endpoint, no hardcode | `/api/v1/meta` o `NEXT_PUBLIC_*` |
| §3.5 Pydantic v2 DTOs | Aditivo si la URL se sirve por `/meta` | Cambio consciente |
| §3.1 / §3.2 / §3.3 / §3.4 / §3.6 | Ninguno | — |

## Plan de implementación

1. Config: `NEXT_PUBLIC_GRAFANA_URL` (o `/api/v1/meta` con la URL); documentar en
   `.env.example`.
2. `observabilidad/page.tsx` — usar la config; ocultar el enlace si falta;
   auto-refresco del health; `dlq_count` enlaza a la vista de DLQ; encabezado de rol.
3. Tests vitest: sin config el enlace no aparece (no localhost); el health se
   refresca; el enlace de DLQ navega.

**Archivos de partida**: `observabilidad/page.tsx:43-90`, `api/routes/health.py`,
`api/routes/meta.py`, `web/next.config.ts`, `.env.example`.
**Riesgo estimado**: bajo. Cuidar que la config sea pública-segura (solo URL).
**Tiempo estimado**: 0.5 día.

## Acceptance criteria

- [ ] La URL de Grafana viene de config; sin config no se muestra un localhost roto.
- [ ] El health se auto-refresca e indica la hora del último check.
- [ ] Observabilidad y calidad-datos tienen roles claros y se enlazan; `dlq_count` enlaza a DLQ.
- [ ] `npm run typecheck && npm run lint && npm test` (web) en verde.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

2026-06-22 — **Implementado.** Grafana por config: `web/src/lib/runtime-config.ts`
(`getGrafanaUrl()` lee `NEXT_PUBLIC_GRAFANA_URL`; devuelve `null` si falta/blank).
La card oculta el enlace y muestra una nota de "no configurada" en vez del
`localhost:3001` roto. Salud en vivo: auto-refresh de 30s ya existente + botón
"Refrescar" manual (spinner con `isFetching`) + hora del último check. Rol claro:
subtítulo "infra/SRE" con cross-link a Calidad de Datos; `dlq_count` enlaza a
`/calidad-datos` ("Inspeccionar DLQ"). Tests: `runtime-config.test.ts` (3). Verde:
`tsc`/`eslint`/`vitest` (18 files, 279 tests). **Pendiente (§6):** añadir
`NEXT_PUBLIC_GRAFANA_URL` a `.env.example` (edición de `.env*` requiere OK humano).
