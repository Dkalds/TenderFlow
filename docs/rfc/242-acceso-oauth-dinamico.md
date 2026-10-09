---
rfc: 242
title: Conceder acceso OAuth desde el producto con auditoría
issue: https://github.com/Dkalds/TenderFlow/issues/242
author: agent:github-copilot
date: 2026-09-01
status: implemented
implemented_on: 2026-09-06
implemented_evidence: >
  Revisión `v95_access_grants` (tabla `access_grants`), `db/access_grants.py`,
  `services/access_grants.py`, las rutas de `api/routes/admin_solicitudes.py`
  (PATCH con `conceder`, `GET` y `DELETE /grants`) y el callback de
  `api/routes/auth.py` (`_oauth_access_allowed`). La evidencia son los tests
  citados junto a cada criterio de aceptación de este RFC; los de
  `tests/test_access_grants_integration.py` corren contra Postgres. Revisado el
  2026-10-09, al cerrar los huecos que encontró la auditoría del issue.
---

## Contexto

El formulario público y la cola administrativa existen, pero conceder acceso
sigue exigiendo editar `OAUTH_ALLOWED_EMAILS`/`OAUTH_ALLOWED_DOMAINS` en Render y
redesplegar. El sistema no puede saber si el acceso está activo, por lo que la
notificación es manual y la concesión no deja una traza propia.

## Decisión

Añadir una allowlist dinámica en Postgres, **aditiva** a la configuración
estática. Un email OAuth entra si cumple al menos una de estas condiciones:

1. figura en `OAUTH_ALLOWED_EMAILS`;
2. su dominio figura en `OAUTH_ALLOWED_DOMAINS`;
3. existe una concesión activa para ese email o dominio en `access_grants`.

La tabla almacena sólo valores normalizados, tipo (`email` o `domain`), estado,
actor y marcas temporales. No guarda tokens OAuth. El callback consulta la tabla
en el threadpool. Un fallo de BD es fail-closed y no degrada a acceso abierto.

El PATCH administrativo incorpora las acciones `grant` y `revoke`. `grant`
persiste primero, registra auditoría y sólo entonces puede notificar. La
configuración estática sigue siendo el mecanismo de bootstrap y no puede
revocarse desde la UI.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Mantener env vars | Sin schema | Redeploy, sin auditoría, notificación insegura | No cierra el flujo |
| Sustituir env por BD | Una sola verdad | Riesgo de bloquear bootstrap | Se elige composición aditiva |
| Conceder creando usuario | Simple | Usuario creado no equivale a autorización OAuth | Mezcla identidad y acceso |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Nuevos módulos tipados | Sin `Any` nuevo injustificado |
| §3.2 Upsert idempotente | Concesión repetible | `UNIQUE(kind, value)` + upsert |
| §3.3 Migraciones append-only | Nueva tabla | Revisión nueva; no se toca histórico |
| §3.4 Auto-marking tests | Integración Postgres | Fixtures existentes |
| §3.5 DTO Pydantic | Acción admin aditiva | OpenAPI regenerado |
| §3.6 Auth | Cambia autorización OAuth | Fail-closed, admin y audit log |

## Plan de implementación

1. Migración append-only `access_grants` con RLS/revokes.
2. Repositorio `db/access_grants.py` con grant/revoke/check/list.
3. Callback OAuth consulta configuración estática + concesión dinámica.
4. Endpoint admin concede/revoca y notifica sólo tras éxito.
5. Panel admin muestra estado y acciones.
6. Tests de fail-closed, idempotencia, scopes y auditoría.

**Riesgo estimado:** alto

## Acceptance criteria

Cada casilla marcada lleva el test que la prueba. Los de
`tests/test_access_grants_integration.py` necesitan Postgres (los corre CI).

- [x] Aprobar desde Admin concede acceso sin editar entorno.
  - `tests/test_access_grants_integration.py::test_conceder_desde_la_ruta_abre_el_login_y_deja_rastro`
    (el PATCH concede y el login, con la lista estática sin esa dirección, pasa
    de denegar a permitir).
  - `tests/test_access_grants_integration.py::test_conceder_la_solicitud_escribe_la_concesion_y_la_atiende`
    (concesión y solicitud atendida en una transacción).
  - `tests/test_auth_oauth_callback.py::test_callback_con_una_concesion_dinamica_deja_entrar`
    (sin BD: el callback entero con la concesión como única vía).
- [x] Revocar una concesión dinámica corta nuevos logins.
  - `tests/test_auth_dynamic_grants.py::test_dynamic_grant_is_normalized_idempotent_and_revocable`
  - `tests/test_access_grants_integration.py::test_revocar_desde_la_ruta_corta_los_logins_nuevos_y_deja_rastro`
  - `tests/test_access_grants_integration.py::test_volver_a_conceder_tras_revocar_reactiva_la_misma_fila`
- [x] Env vacío + tabla vacía sigue fail-closed en producción.
  - `tests/test_auth_core.py::TestOAuthEmailAllowed::test_listas_vacias_fuera_de_desarrollo_deniegan`
    (listas vacías en `prod` y `staging`: la mitad estática dice que no).
  - `tests/test_access_grants_integration.py::test_conceder_desde_la_ruta_abre_el_login_y_deja_rastro`
    (su primera comprobación: con la tabla vacía, el login deniega).
  - `tests/test_auth_oauth_callback.py::test_callback_sin_acceso_redirige_sin_crear_usuario_ni_sesion`
    (la negativa acaba en `/login?error=email_not_allowed`, sin usuario ni sesión).
  - `tests/test_config_settings.py::test_prod_oauth_without_static_allowlists_uses_dynamic_fail_closed_path`
    (producción arranca con las dos listas vacías).
- [x] Una caída de BD no abre acceso.
  - `tests/test_auth_dynamic_grants.py::test_dynamic_allowlist_failure_is_closed`
  - `tests/test_auth_oauth_callback.py::test_callback_con_la_tabla_de_concesiones_caida_no_deja_entrar`
- [x] Concesión/revocación quedan auditadas.
  - `tests/test_routes_admin_solicitudes.py::TestCambiarEstado::test_conceder_se_audita_con_actor_recurso_y_user_id`
  - `tests/test_routes_admin_solicitudes.py::TestAccessGrants::test_la_revocacion_se_audita_con_actor_recurso_y_user_id`
  - Las filas en `audit_log`, con su `user_id`, las comprueban los dos tests de
    ruta de `tests/test_access_grants_integration.py`.
  - Alcance: el evento se escribe tras confirmar la transacción y es
    best-effort, como toda la auditoría del producto. Que una concesión no
    pueda existir sin su fila de auditoría queda en
    `docs/IMPROVEMENT_BACKLOG.md`.
- [ ] `make lint && make typecheck && make test-unit` pasan. No lo prueba un
  test: es el gate de CI del PR que lleve el cambio.

## Notas de review

2026-09-01 human:user — Autorizada la creación del RFC, issue y migración.

2026-10-09 agent:claude-code — Auditoría de la implementación y cierre de sus
huecos, sin cambios en la decisión. Dos precisiones sobre cómo quedó
implementada: revocar es `DELETE /admin/solicitudes-acceso/grants/{id}` y no una
acción del PATCH, y «registra auditoría» es un `log_event` best-effort posterior
a la transacción, no parte de ella. Añadido en esa pasada: el dominio de un
proveedor de correo público no se concede (422, `services/access_grants.py`);
una dirección que no tenga exactamente un `@` se deniega en la lista estática,
en `access_grants` y al leer el token; y avisar sin conceder solo escribe a
quien ya puede entrar.
