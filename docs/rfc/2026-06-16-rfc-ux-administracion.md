---
rfc: pendiente
title: "UX · Administración — usuarios reales (no MOCK_USERS) y gestión funcional"
issue: pendiente (crear issue y renumerar si no coincide)
author: agent:architect
date: 2026-06-16
status: implemented
area: web/administracion
---

## Contexto

`web/src/app/(dashboard)/administracion/page.tsx` administra usuarios, API keys y
operaciones (DLQ). Pero la sección de **usuarios usa datos falsos**:

```ts
const MOCK_USERS = [
  { email: "admin@empresa.com", ... },
  { email: "analista@empresa.com", ... },
  { email: "operador@empresa.com", ... },
];   // líneas 51-73
```

El panel muestra estos 3 usuarios **hardcodeados** en vez de los usuarios reales
del backend. Existe el dato real (`db/users.py::list_users`, `services/users.py`),
así que la **gestión de usuarios es no-funcional**: el admin no ve a los usuarios
reales ni puede gestionarlos (activar/desactivar/promover). En cambio, la sección
de API keys sí usa una query real (`/api/v1/...api-keys`) — la inconsistencia
delata que usuarios quedó mockeado.

Esto además bloquea el frontend del RFC backend de *soft-delete/anonimización de
usuarios* (no hay UI real donde desactivar).

> Vía API (§3.8). El backend ya expone usuarios; falta conectarlo (§3.5 si hace
> falta un endpoint de listado/gestión).

## Decisión

1. **Usuarios reales.** Reemplazar `MOCK_USERS` por una query a
   `/api/v1/.../users` (`list_users`): email, display_name, is_admin, estado,
   último acceso. Eliminar el mock.
2. **Gestión funcional.** Acciones admin reales (gateadas por `isAdmin` y scope
   backend): promover/degradar admin, **desactivar** (cuando aterrice el soft-delete
   del RFC backend, mapear a esa operación, no a hard-delete), con confirmación.
3. **Auditoría.** Registrar las acciones admin (actor/target/acción/fecha) vía
   `db/audit.py`.

**Qué NO se hace:**

- **No** se implementa el borrado/anonimización aquí: se **consume** la operación
  del RFC backend de soft-delete; mientras tanto, la acción de desactivar se
  deshabilita o se marca como pendiente, no se cablea a un hard-delete.
- **No** se toca la sección de API keys (ya real).

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Status quo (MOCK_USERS) | Cero trabajo | Gestión de usuarios falsa/no-funcional | Inaceptable en un panel de admin |
| Listar usuarios sin acciones | Rápido | Ve pero no gestiona | Medio camino |
| Usuarios reales + acciones + auditoría (elegida) | Admin funcional y trazable | Endpoints de gestión (algunos ya existen) | — |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.5 Pydantic v2 DTOs | Aditivo si falta DTO de listado/gestión de usuarios | Reusar `services/users.py` |
| §3.8 Frontend vía API | **Refuerza** — elimina datos mock | `services/users.py` |
| §3.6 auth | Acciones admin gateadas por scope | `require_scope("admin")` |
| §3.1 / §3.2 / §3.3 / §3.4 | Ninguno/mínimo | Tipar |

## Plan de implementación

1. `api/routes/` + `services/users.py` — GET usuarios; acciones de promover/
   desactivar (esta última mapeada al soft-delete del RFC backend cuando exista),
   admin-only + audit.
2. `administracion/page.tsx` — reemplazar `MOCK_USERS` por la query real; acciones
   con confirmación; gating `isAdmin`.
3. Regenerar `@/generated/api`.
4. Tests: la lista muestra usuarios reales; las acciones requieren admin y se
   auditan; desactivar no hace hard-delete.

**Archivos de partida**: `administracion/page.tsx:51-95`, `db/users.py`,
`services/users.py`, `api/routes/` (admin/users), `db/audit.py`.
**Riesgo estimado**: bajo-medio. Coordinar la acción de desactivar con el RFC de
soft-delete para no cablear un hard-delete.
**Tiempo estimado**: 1 día.

## Acceptance criteria

- [ ] La sección de usuarios muestra usuarios reales del backend (sin `MOCK_USERS`).
- [ ] Las acciones admin (promover/desactivar) funcionan, requieren admin y se auditan.
- [ ] Desactivar no ejecuta hard-delete (se alinea con el RFC de soft-delete).
- [ ] `npm run typecheck && npm run lint && npm test` (web) y `make ...` (backend) en verde.

## Notas de review

<!-- YYYY-MM-DDTHH:MMZ agent:reviewer — comentario -->

2026-06-24 — **Implementado (frontend).** El backend ya existía
(`api/routes/admin_users.py`: `GET /api/v1/admin/users` con `list_users`, `PUT
/{id}/admin` con `set_admin` + `log_event`, soft-delete), pero la página seguía con
`MOCK_USERS`. Frontend: eliminado `MOCK_USERS`; nueva query a `/api/v1/admin/users`
(mapea `deactivated_at`→activo, `last_access`→último login), con loading/skeleton y
mensaje honesto si la sesión no es admin (403). La acción "Toggle admin" se cablea a
`PUT /{id}/admin` (mutación con invalidación + toast), gateada por el backend
(`is_admin`) y auditada (`log_event`). Verde: `tsc`/`eslint`/`vitest` (285),
codespell. `check_frontend_invariants`: `mock-data` 1→**0** (cerrados los dos mocks).
**Diferido:** acción de desactivar/anonimizar con diálogo de confirmación (el backend
`POST /{id}/deactivate` ya existe; falta la UI con confirmación).
