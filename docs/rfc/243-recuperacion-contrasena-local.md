---
rfc: 243
title: Recuperación segura de contraseña para cuentas locales
issue: https://github.com/Dkalds/TenderFlow/issues/243
author: agent:github-copilot
date: 2026-09-01
status: approved
---

## Contexto

TenderFlow autentica cuentas locales con contraseña, pero no ofrece recuperación
ni cambio. El usuario que la olvida queda bloqueado y el login no puede ofrecer
una salida real.

## Decisión

Añadir un flujo de dos pasos:

1. `POST /auth/password-reset/request` acepta email y devuelve siempre la misma
   respuesta. Si existe una cuenta local activa, crea un token de 32 bytes,
   persiste sólo `SHA-256(token)`, expira en 30 minutos e invalida tokens
   pendientes anteriores del usuario. El correo es best-effort.
2. `POST /auth/password-reset/confirm` consume el token una sola vez, aplica la
   política de contraseña vigente, reemplaza el hash Argon2/bcrypt y revoca
   todas las sesiones del usuario.

El token bruto no se loguea ni se almacena. Request se limita por IP y por hash
del email; confirm por IP. La respuesta de request no permite enumerar cuentas.
La UI vive en `/restablecer-contrasena`, permite pegar el token y anuncia
errores programáticamente.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Soporte manual | Sin código | No escala, identidad difícil de verificar | No es autoservicio seguro |
| Enlace firmado stateless | Sin tabla | Difícil revocar/replay | Se necesita un solo uso |
| Reusar sesión/TOTP | Menos superficie | Quien olvidó contraseña no tiene sesión | No resuelve el bloqueo |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Nuevos módulos tipados | DTOs y repositorio strict |
| §3.2 Upsert idempotente | Request repetible | Tokens previos se invalidan transaccionalmente |
| §3.3 Migraciones append-only | Nueva tabla | Revisión nueva; sin modificar histórico |
| §3.4 Auto-marking tests | Unit + integración | Convención existente |
| §3.5 DTO Pydantic | Dos contratos nuevos | OpenAPI regenerado |
| §3.6 Auth | Cambia credencial local | Política vigente, token hash, revocación de sesiones |

## Plan de implementación

1. Migración `password_reset_tokens` con índices de hash/expiración y RLS.
2. Repositorio transaccional para emitir y consumir tokens.
3. Servicio de correo transaccional sin enumeración.
4. Endpoints request/confirm con rate limiting.
5. Página accesible de solicitud/confirmación.
6. Tests de expiración, replay, no enumeración y revocación.

**Riesgo estimado:** alto

## Acceptance criteria

- [ ] Request responde igual exista o no la cuenta.
- [ ] El token válido cambia la contraseña exactamente una vez.
- [ ] Token expirado/usado falla sin cambiar credenciales.
- [ ] El token bruto no se persiste ni se registra.
- [ ] Todas las sesiones previas se revocan.
- [ ] `make lint && make typecheck && make test-unit` pasan.

## Notas de review

2026-09-01 human:user — Autorizada la creación del RFC, issue y migración.
