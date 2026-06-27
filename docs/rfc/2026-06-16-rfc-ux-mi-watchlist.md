---
rfc: pendiente
title: "UX/KPIs · Mi Watchlist — persistir reglas en servidor y alertas reales (hoy localStorage)"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: implemented
area: web/mi-watchlist
---

## Contexto

`web/src/app/(dashboard)/mi-watchlist/page.tsx` deja al usuario crear reglas de
seguimiento (keyword, CPV, importe mínimo, CCAA, **frecuencia de alerta**:
inmediata/diaria/semanal). Pero la implementación es **100 % cliente** y eso rompe
la promesa de la página:

1. **Las reglas viven solo en `localStorage`** (`STORAGE_KEY = "watchlist_rules"`,
   `loadRules`/`saveRules`, líneas 65-79). Consecuencias:
   - No sincronizan entre dispositivos/navegadores; se pierden al limpiar datos.
   - **La frecuencia de alerta es no-funcional**: ningún job del backend puede leer
     el `localStorage` del navegador, así que las alertas "inmediata/diaria/semanal"
     **nunca se envían**. La página parece un sistema de alertas pero es una
     búsqueda guardada local. (Nota: la watchlist de **empresas** sí es server-side
     — `services/watchlist.py`, `notifications`, `api/routes/watchlist_feed.py`; esta
     watchlist de keyword/CPV no lo es. Hay dos conceptos divergentes.)

2. **`cpvFilter` se recoge pero no se usa.** El form guarda `cpvFilter`, pero el
   fetch de matches (líneas 170-184) solo manda `q` (keyword) y `ccaa`; el filtro
   CPV no entra en la query **ni** en el filtrado cliente. Es un control muerto que
   silenciosamente no hace nada.

3. **`minImporte` se filtra en cliente tras `limit=20`.** Cada regla pide solo las
   20 licitaciones más recientes (`limit=20`, línea 174) y luego descarta en cliente
   las que no llegan al importe (líneas 192-198). Si los matches por importe están
   más atrás que el top-20 reciente, no aparecen. Conteos de match poco fiables.

> La watchlist de empresas ya prueba que el patrón server-side existe
> (`services/watchlist.py` + `notifications`). Este RFC unifica las reglas de
> keyword/CPV en ese modelo (§3.8) con contrato aditivo (§3.5).

## Decisión

Mover las reglas de watchlist al **servidor** y conectar la **alerta real**,
reutilizando la infraestructura existente.

1. **Persistencia server-side.** Tabla/endpoint de reglas de watchlist por usuario
   (keyword, cpv, min_importe, ccaa, frequency, active) — extendiendo
   `services/saved_filters.py`/`services/watchlist.py`. El frontend hace CRUD vía
   API; `localStorage` queda solo como caché/migración one-shot de reglas previas.
2. **Alertas reales.** Un job (el scheduler ya corre jobs; ver `scheduler/`) evalúa
   las reglas activas según su `frequency` y emite a `notifications`/email
   (infra de alertas de watchlist ya existente). La frecuencia pasa a significar
   algo.
3. **Aplicar el CPV.** El matching server-side aplica keyword **y** CPV **y**
   min_importe **y** ccaa — no solo keyword/ccaa. Se elimina el control muerto.
4. **Matching completo, no top-20 cliente.** El conteo de matches por regla se
   calcula en backend sobre el dataset filtrado (no un `limit=20` + filtro cliente).

**Qué NO se hace:**

- **No** se elimina la vista de matches en vivo (se mantiene, pero servida por un
  endpoint de "matches de la regla" con los filtros aplicados).
- **No** se fusiona forzadamente con la watchlist de empresas (son ejes distintos:
  empresa vs criterio); pero ambas comparten `notifications`.
- **No** se migran reglas ajenas: la migración es del `localStorage` del propio
  usuario, una sola vez.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo (localStorage) | Cero backend | Alertas no funcionan; sin sync; CPV muerto | Rompe la promesa de la página |
| Mantener reglas locales pero "enviar" al server solo para alertas | Menos cambios | Estado partido cliente/servidor; difícil de razonar | Fuente de verdad ambigua |
| Persistir reglas server-side + job de alertas (elegida) | Alertas reales, sync, CPV aplicado, conteos fiables | Tabla/endpoint + job nuevos | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Tipos generados (reglas, matches) | Regenerar OpenAPI; tipar |
| §3.3 Migraciones append-only | **Nueva** tabla de reglas → nueva revisión Alembic | Revisión nueva; **OK humano §6** |
| §3.5 Pydantic v2 DTOs | **Aditivo**: DTO de regla y de match | Cambio consciente; regenerar cliente |
| §3.8 Frontend vía API | **Refuerza** — reglas y matching pasan a API | `services/watchlist.py`/`saved_filters.py` |
| §3.2 / §3.4 / §3.6 | Ninguno | — |

## Plan de implementación

1. Migración Alembic (gated §6): tabla `watchlist_rules` por usuario.
2. `services/watchlist.py`/`saved_filters.py` + `api/routes/watchlist_feed.py` —
   CRUD de reglas; endpoint de matches con todos los filtros (incl. CPV/importe);
   job de evaluación por frecuencia → `notifications`/email.
3. `mi-watchlist/page.tsx` — CRUD vía API; migración one-shot del `localStorage`;
   aplicar CPV; conteos desde backend.
4. Regenerar `@/generated/api`.
5. Tests: CPV se aplica; min_importe no se pierde por el top-20; una regla "diaria"
   genera notificación en el job; migración de reglas locales.

**Archivos de partida**: `mi-watchlist/page.tsx:65-249`, `services/watchlist.py`,
`services/saved_filters.py`, `services/notifications.py`,
`api/routes/watchlist_feed.py`, `scheduler/jobs/`.
**Riesgo estimado**: medio — añade tabla + job; el matching server-side debe
respetar `_escape_like` (ya existe) para los keywords.
**Tiempo estimado**: 2-2.5 días.

## Acceptance criteria

- [ ] Las reglas persisten server-side y sincronizan entre sesiones/dispositivos.
- [ ] Una regla con frecuencia diaria/semanal genera alerta real vía el job.
- [ ] El filtro CPV se aplica (deja de ser un control muerto).
- [ ] El conteo de matches por regla no depende de un `limit=20` cliente.
- [ ] Migración one-shot de reglas en `localStorage`.
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend) en verde.
- [ ] diff-cover ≥ 80% en líneas nuevas.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

**2026-06-27 — Implementado (backend + frontend), motor por increments:**

- Persistencia server-side (criterio 1): tabla `watchlist_rules` (migración v43),
  CRUD en `services/watchlist_rules.py`, API `api/routes/watchlist_rules.py`.
- Alerta real por frecuencia (criterio 2): `scheduler/watchlist_rules_alerts.py::check_rules_and_notify`
  (immediate/daily/weekly → `notify`), enganchado al pipeline en `_run_watchlist_notify`.
- CPV aplicado (criterio 3) y conteo sobre el dataset completo, no top-20 (criterio 4):
  `count_matches`/`list_matches` (SQLAlchemy Core + `_escape_like`).
- Migración one-shot del `localStorage` (criterio 5): `mi-watchlist/page.tsx` reescrita
  a la API con React Query; sube las reglas legacy y limpia el storage.
- Tests: 23 (servicio + API + job). Verificado: ruff/mypy/pytest + tsc/eslint.
