---
rfc: pendiente
title: "UX · Feature Flags — lista dirigida por backend (no hardcode), persistencia y auditoría"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: draft
area: web/feature-flags
---

## Contexto

`web/src/app/(dashboard)/feature-flags/page.tsx` administra flags, pero la lista
está **hardcodeada en el frontend**:

```ts
const LOCAL_FLAGS: FeatureFlag[] = [ /* 5 flags fijos */ ];   // líneas 33-59
// merge: solo actualiza los flags cuyo key coincide con LOCAL_FLAGS
setFlags(prev => prev.map(f => { const match = data.find(a => a.flag === f.key); ... }));  // línea 78-85
```

Problemas:

1. **Fuente de verdad duplicada y drift.** El merge mapea sobre `LOCAL_FLAGS`
   (`prev`), así que un flag que existe en el backend pero **no** está en
   `LOCAL_FLAGS` **no se muestra**; y un flag retirado del backend sigue apareciendo.
   La página no refleja el estado real de flags.
2. **Toggle/rollout posiblemente no persisten.** El estado se actualiza en local;
   un panel de admin de flags debe persistir server-side (con feedback de error) —
   `services/feature_flags.py` ya existe.
3. **Sin auditoría.** No registra quién activó/desactivó qué y cuándo — esperable en
   un control de admin con impacto en producción.

> Vía API (`/api/v1/feature-flags`) — §3.8. El backend ya tiene
> `services/feature_flags.py`; la página debe renderizar **lo que devuelve**, no una
> lista fija.

## Decisión

1. **Lista dirigida por backend.** Renderizar exactamente los flags que devuelve
   `/api/v1/feature-flags` (key, description, enabled, rollout_pct). Eliminar
   `LOCAL_FLAGS` como fuente; a lo sumo, fallback de descripción.
2. **Persistencia de toggle/rollout.** El toggle y el rollout hacen PUT/POST al
   backend con manejo de error/optimistic update; gating por `isAdmin` (ya está).
3. **Auditoría.** Registrar cambios de flag (actor, flag, valor, timestamp) vía
   `db/audit.py`/`services/audit.py`; mostrar el último cambio por flag.

**Qué NO se hace:**

- **No** se mueve la lógica de evaluación de flags al cliente (sigue en backend).
- **No** se añade segmentación avanzada (por usuario/tenant) en este RFC.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo (hardcode) | Cero trabajo | Flags backend invisibles; drift; sin persistencia/auditoría | No refleja la realidad |
| Sincronizar el hardcode a mano | Trivial | Vuelve a driftar | Frágil |
| Backend-driven + persistencia + auditoría (elegida) | Veraz, persistente, trazable | Endpoints de set/audit | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.5 Pydantic v2 DTOs | Aditivo (set flag, audit) | Cambio consciente |
| §3.8 Frontend vía API | **Refuerza** — elimina la lista hardcodeada | `services/feature_flags.py` |
| §3.6 auth | El set requiere admin (ya gateado) | `require_scope("admin")` en backend |
| §3.1 / §3.2 / §3.3 / §3.4 | Ninguno/mínimo | Tipar |

## Plan de implementación

1. `api/routes/` + `services/feature_flags.py` — GET (lista completa), set
   (enabled/rollout, admin-only), y audit del cambio.
2. `feature-flags/page.tsx` — renderizar la lista del backend; eliminar `LOCAL_FLAGS`
   como fuente; persistir toggles; mostrar último cambio.
3. Regenerar `@/generated/api`.
4. Tests: un flag solo-backend aparece; el toggle persiste y se audita; no-admin no puede.

**Archivos de partida**: `feature-flags/page.tsx:33-95`,
`services/feature_flags.py`, `api/routes/` (feature-flags), `db/audit.py`.
**Riesgo estimado**: bajo. Set de flags debe exigir admin (ya hay scopes).
**Tiempo estimado**: 0.5-1 día.

## Acceptance criteria

- [ ] La página muestra todos los flags del backend (incl. los que no estaban en el hardcode).
- [ ] Toggle y rollout persisten server-side con manejo de error.
- [ ] Cada cambio queda auditado (actor/flag/valor/fecha) y visible.
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend) en verde.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->
