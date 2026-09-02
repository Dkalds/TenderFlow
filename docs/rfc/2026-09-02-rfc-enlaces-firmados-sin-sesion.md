---
rfc: 2026-09-02-enlaces-firmados
title: Enlaces firmados sin sesión para el calendario ICS y la baja de correos
issue: (sin issue: decisión tomada en sesión con el mantenedor)
author: agent:claude-code
date: 2026-09-02
status: approved
---

## Contexto

Dos superficies del producto necesitan autenticar a una persona que **no tiene
sesión** en el momento de usarlas:

1. **Suscripción al calendario de compromisos.** `GET /api/v1/exports/calendario.ics`
   existía desde julio y exigía la cabecera `X-API-Key`. Google Calendar, Apple
   Calendar y Outlook no envían cabeceras personalizadas al suscribirse a una URL,
   así que el endpoint era inservible para los tres clientes que importan, y
   ningún componente del frontend lo enlazaba. Su docstring anterior rechazaba
   explícitamente un `?token=` porque «acaba en los access logs y en el `Referer`
   y de ahí no se puede revocar».
2. **Baja de los correos de watchlist.** El digest no llevaba pie de baja. Quien
   quiere dejar de recibir correo no quiere antes hacer login, y un enlace que
   exija sesión es un enlace que no se pulsa.

AGENTS.md §5 exige RFC para «decisiones de seguridad/auth (nuevos mecanismos)».
Esto lo es, aunque el alcance sea mínimo.

## Decisión

Usar **URLs de capacidad firmadas con HMAC** (`shared/signing`, con `kid` y
rotación), acotadas cada una a su endpoint:

- Calendario: `?u=<user_id>&t=<firma>` con `firma = sign(b"calendario-ics:" + user_id)`.
  El endpoint sigue aceptando `X-API-Key` para clientes que sí mandan cabeceras.
  Devuelve **solo** fechas de compromisos (plazos de pursuits abiertos y de
  favoritos): no abre sesión, no lee el corpus, no escribe nada.
- Baja: `?k=<user_key>&t=<firma>` con `firma = sign(b"baja-alertas:" + user_key)`.
  Pausa las reglas de watchlist del `user_key` (`active = 0`); no borra nada y se
  revierte desde Mi Watchlist. `user_key` es un hash opaco, no un dato personal.

Cada prefijo de firma es distinto, así que una firma no sirve para el otro
endpoint ni para ninguna otra cosa. **Revocación:** rotar `SIGNING_KEY`
(`SIGNING_KEYS_JSON` + `SIGNING_KEY_ACTIVE`) invalida todos los enlaces emitidos
con la clave retirada. Es revocación global, no por usuario, y se acepta por el
alcance de lo expuesto.

Lo que **no** se hace: tokens por usuario en base de datos (una tabla, una
migración y un ciclo de vida más para revocar algo que hoy no justifica ese
peso), ni reutilizar la API key del usuario en la URL (esa sí abre toda la API).

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Solo `X-API-Key` (estado anterior) | Sin superficie nueva | Inservible para Google/Apple/Outlook; el ICS quedaba muerto | No cumple el objetivo |
| API key del usuario en la query | Sin código nuevo | Un enlace filtrado abre la API entera | Riesgo desproporcionado |
| Token por usuario en BD, revocable | Revocación individual | Tabla + migración + ciclo de vida; gate humano aparte | Coste alto para exponer fechas |
| Enlace firmado stateless acotado (elegida) | Sin estado; alcance mínimo; rotación ya existente | Revocación global; `user_id` en logs | Riesgo acotado y aceptado |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Ninguno | mypy verde |
| §3.2 Upsert idempotente | Ninguno | — |
| §3.3 Migraciones append-only | Ninguno | Sin tabla nueva |
| §3.4 Auto-marking tests | Unit (firma, render) | `tests/test_unit_email_digest.py` |
| §3.5 DTO Pydantic | `CalendarioEnlace` nuevo, `StatusOk` reutilizado | OpenAPI regenerado |
| §3.6 HMAC/argon2 auth | **Nuevo camino sin sesión** | Firma HMAC con `kid`; prefijo por endpoint; alcance de solo lectura o reversible; `verify` con `compare_digest` |

## Plan de implementación

Implementado en la rama `worktree-producto-mejoras` (2026-09-02):

1. `api/routes/exports.py`: `calendario_ics` acepta `X-API-Key` o `?u&t`;
   `GET /exports/calendario/enlace` (con sesión) devuelve la ruta firmada.
2. `services/email_digest.py`: `token_de_baja`, `verificar_token_de_baja`,
   `url_de_baja_alertas`; el digest lleva el enlace en el pie.
3. `api/routes/watchlist_rules.py`: `GET /watchlist/rules/baja` verifica y pausa;
   redirige a `/mi-watchlist?baja=<n>`.
4. `web/src/components/pursuits/calendario-suscripcion.tsx`: la UI entrega la
   URL con una nota de privacidad explícita («quien lo tenga ve tus plazos»).

**Riesgo estimado:** medio.

## Acceptance criteria

- [x] Una firma del calendario no verifica como firma de baja ni viceversa.
- [x] Firma manipulada o de otro usuario → 401 (calendario) / 403 (baja).
- [x] La baja no borra reglas: `active = 0`, reversible desde la UI.
- [x] El calendario no devuelve nada que no sea fecha, título y enlace público.
- [x] `make lint && make typecheck && make test-unit` en verde.
- [x] Runbook de rotación menciona que invalida estos enlaces
      (`docs/runbooks/incident-playbooks.md`, playbook 8).

## Notas de review

2026-09-02 human:user — «Si te doy el ok a todo, quita todos los blockers».
Aprobado en sesión; se registra aquí para que la decisión tenga huella.
