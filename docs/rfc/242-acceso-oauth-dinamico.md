---
rfc: 242
title: Conceder acceso OAuth desde el producto con auditoría
issue: https://github.com/Dkalds/TenderFlow/issues/242
author: agent:github-copilot
date: 2026-09-01
status: approved
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

- [ ] Aprobar desde Admin concede acceso sin editar entorno.
- [ ] Revocar una concesión dinámica corta nuevos logins.
- [ ] Env vacío + tabla vacía sigue fail-closed en producción.
- [ ] Una caída de BD no abre acceso.
- [ ] Concesión/revocación quedan auditadas.
- [ ] `make lint && make typecheck && make test-unit` pasan.

## Notas de review

2026-09-01 human:user — Autorizada la creación del RFC, issue y migración.
