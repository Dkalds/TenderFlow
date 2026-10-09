---
rfc: 243
title: Recuperación segura de contraseña para cuentas locales
issue: https://github.com/Dkalds/TenderFlow/issues/243
author: agent:github-copilot
date: 2026-09-01
status: implemented
implemented_on: 2026-09-06
implemented_evidence: >
  Revisión `v96_password_reset_tokens`, `db/password_reset.py`,
  `services/password_reset.py` y las rutas `/password-reset/request` y
  `/password-reset/confirm` de `api/routes/auth.py`, con cuotas por IP y por
  hash del email (`_password_reset_rate_allowed`). Cada criterio de aceptación
  cita el test que lo prueba (`tests/test_password_reset.py`,
  `tests/test_password_reset_limites.py`). Revisado contra el código el
  2026-10-09: la auditoría de ese día encontró cinco huecos (política de
  confirm distinta de la del alta, tokens hermanos vivos tras el cambio, cubo
  de cuota compartido, canal temporal en request y token en el log del backend
  `console`) y se cerraron con sus tests.
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

Cada casilla marcada cita el test que la prueba. Los que llevan «(BD)» abren
Postgres: corren en CI (`Tests (Postgres)`), no en `make test-unit`.

- [x] Request responde igual exista o no la cuenta.
  - Cuerpo y estado: `tests/test_password_reset.py::test_request_response_does_not_enumerate_accounts`
    y `::test_request_rate_limit_keeps_generic_response`.
  - Tiempo: `::test_request_no_hace_en_linea_nada_que_dependa_de_la_cuenta`
    (antes de responder no se consulta la cuenta, no se audita y no se envía) y
    `::test_request_responde_igual_aunque_el_trabajo_aplazado_falle`.
  - Las cuotas no miran si la cuenta existe (se consultan antes, por IP y por
    hash del correo): `tests/test_password_reset_limites.py::test_pedir_el_enlace_consulta_el_cubo_de_ip_y_el_del_destinatario`.
- [x] El token válido cambia la contraseña exactamente una vez.
  - `tests/test_password_reset.py::test_token_is_single_use_and_revokes_sessions` (BD),
    `::test_consumir_un_enlace_invalida_los_demas_pendientes_del_usuario` (BD) y
    `::test_recorrido_completo_por_http` (BD), que además comprueba que un rechazo
    por política no gasta el enlace.
- [x] Token expirado/usado falla sin cambiar credenciales.
  - `::test_un_token_caducado_no_cambia_nada` (BD),
    `::test_pedir_un_enlace_nuevo_invalida_el_anterior` (BD) y
    `::test_confirm_rejects_invalid_or_expired_token`.
  - Cuentas que no pueden usarlo: `::test_una_cuenta_solo_oauth_no_recibe_enlace_ni_puede_consumirlo` (BD)
    y `::test_una_cuenta_de_baja_no_recibe_enlace_ni_consume_el_que_tenia` (BD).
- [x] El token bruto no se persiste ni se registra.
  - No se persiste: `::test_token_is_single_use_and_revokes_sessions` (BD) lee la
    fila y solo encuentra el SHA-256.
  - No se registra: `::test_el_registro_del_envio_no_lleva_el_token_ni_la_direccion`,
    `::test_el_fallo_aplazado_se_registra_sin_el_token_ni_el_correo`,
    `tests/test_mailer.py::test_console_no_deja_en_el_log_el_token_del_enlace_de_recuperacion`
    y `tests/test_observability_logging.py::test_redact_token_en_el_fragmento_de_un_enlace`.
- [x] Todas las sesiones previas se revocan.
  - `::test_token_is_single_use_and_revokes_sessions` (BD, por `validate_session`)
    y `::test_recorrido_completo_por_http` (BD, por `validate_session_principal`
    y `GET /auth/me`, que es el camino que recorre el SPA).
- [ ] `make lint && make typecheck && make test-unit` pasan.
  - No es una propiedad del flujo sino una puerta del cambio: la comprueba el CI
    de cada PR que lo toque. Se marca con el PR en verde, no antes.

Lo que la decisión promete y los criterios no nombran también tiene test:
las cuotas (`tests/test_password_reset_limites.py`), la política de contraseña
compartida con el alta (`tests/test_password_reset.py::test_alta_y_confirm_pasan_por_la_misma_funcion_de_politica`)
y la pantalla (`web/src/app/restablecer-contrasena/__tests__/page.test.tsx`).

## Desviaciones respecto a la decisión

- **La UI no ofrece un campo para pegar el token.** La decisión dice que la
  pantalla «permite pegar el token»; la que existe lo toma del fragmento del
  enlace (`#token=`) y no tiene campo. Lo que sí admite es pegar el **enlace**
  entero en la pestaña donde se pidió: la página escucha `hashchange` y pasa al
  formulario de confirmación. Se deja constancia; la decisión no se cambia.

## Notas de review

2026-09-01 human:user — Autorizada la creación del RFC, issue y migración.

2026-10-09 agent:claude — Revisión contra el código tras la auditoría del
issue #243. Se marcan los criterios con su test y se anota la desviación de la
UI. Lo que la auditoría dejó fuera del alcance (entrega del correo en
producción sin comprobar, límite por IP detrás del proxy de Vercel, cambio de
contraseña autenticado, API keys tras un reset, aviso al titular) está en
`docs/IMPROVEMENT_BACKLOG.md`.
