---
rfc: 2026-10-21-alta-con-contrasena-tras-concesion
title: Alta con correo y contraseña para quien tiene el acceso concedido
issue: "(sin issue: petición directa del mantenedor, 2026-10-21)"
author: agent:claude-code
date: 2026-10-21
status: review
---

## Contexto

Pedir acceso (`POST /publico/solicitudes-acceso`) y concederlo desde el panel
(`PATCH /admin/solicitudes-acceso/{id}` con `conceder`, RFC 242) escribe una fila
en `access_grants`, por correo o por dominio. Hoy esa concesión **solo abre el
login OAuth**: el callback la consulta con
`services/access_grants.py::acceso_oauth_permitido` y crea el usuario al vuelo.

Quien prefiere correo y contraseña no tiene camino:

- `POST /auth/register` responde 403 fuera de `ENV=dev` porque
  `ALLOW_SELF_REGISTRATION` es `false` en producción, y además **no consulta**
  `access_grants`: cuando está abierto, lo está para cualquiera.
- `POST /auth/password-reset/request` solo emite enlace para cuentas con
  `password_hash` (`db/password_reset.py`). Una cuenta que nació por Google no
  puede crearse una contraseña.
- `POST /auth/login` no consulta la concesión: revocarla en el panel corta el
  OAuth pero no una contraseña.

El mantenedor fija el modelo: **pedir acceso es solo la entrada en una lista;
la persona se crea después su cuenta con correo y contraseña, y cada login
comprueba que la concesión siga viva.**

### Por qué el alta necesita verificar el buzón

Abrir `/auth/register` a los correos concedidos sin más abre dos agujeros:

1. **Invitaciones de equipo.** El alta activa las invitaciones pendientes de
   ese correo (`api/routes/auth.py::_activar_invitaciones`, cuyo comentario
   dice que registrarse «es la prueba de que se controla ese buzón»; sin
   verificación no lo es). Quien conozca el correo invitado entraría en la
   organización y vería sus datos.
2. **Vinculación con Google.** `db/users.py::get_or_create_oauth_user` vincula
   el login de Google a la cuenta que ya tenga ese correo. Si un atacante da de
   alta primero el correo de la víctima, cuando la víctima entre con Google se
   une a esa cuenta y el atacante conserva una contraseña válida. Con una
   concesión por dominio basta inventar cualquier `@empresa.example`.

## Decisión

### 1. Alta con verificación (modo cerrado, el de producción)

`POST /auth/register` (`email`, `password`, `display_name`):

- Si el correo **no** pasa `acceso_oauth_permitido` → **403** con
  `detail: "access_not_granted"`. La web enlaza a «Solicitar acceso». Esto
  revela si un correo tiene concesión; se acepta porque la persona necesita esa
  respuesta, y la cuota (abajo) acota el sondeo.
- Si lo pasa → **202** `{"detail": "Revisa tu correo para activar la cuenta."}`,
  igual exista o no la cuenta, y en segundo plano (como el reset de contraseña,
  para no distinguir por latencia):
  - **No existe** → crea el usuario con `password_hash` y
    `email_verified_at = NULL`, y envía el enlace de verificación.
  - **Existe sin verificar** → **sustituye** su `password_hash` por el nuevo e
    invalida los enlaces anteriores. Gana quien controla el buzón: un registro
    previo de un tercero queda inservible.
  - **Existe y está verificada** → no toca la contraseña. Envía «ya tienes una
    cuenta» con un enlace de restablecer contraseña (el de RFC 243, 30 min). Si
    la cuenta nació por Google y no tiene contraseña, ese mismo enlace sirve
    para **crear** la primera (§4).
- **No activa invitaciones ni abre sesión.** Las dos cosas pasan a la
  verificación.
- Cuota por IP y por hash del correo, con los mismos valores que
  `/auth/password-reset/request` (`_password_reset_rate_allowed`).

### 2. Verificación

Endpoint nuevo `POST /auth/verify-email` (`token`):

- Token de 32 bytes, se guarda solo su SHA-256, es de un solo uso y caduca en
  **24 h**. El enlace es `<frontend>/verificar-correo#token=…`: en el fragmento,
  como el del reset, para que no llegue a logs de servidor ni a `Referer`.
- Al consumirlo, en una transacción: `email_verified_at = NOW()`, gasta todos
  los tokens pendientes de la cuenta y activa sus invitaciones. Después abre
  sesión (cookie) y devuelve `UserInfo`, igual que hoy el alta.
- Comprueba la concesión **también aquí**: si se revocó entre el alta y el
  clic, responde 403 `access_not_granted` y no abre sesión.
- Token inválido, caducado o gastado → 400 genérico. Cuota por IP.

Página nueva `/verificar-correo`: lee el token del fragmento, llama al endpoint
y entra en la consola, o explica qué ha pasado y ofrece volver a darse de alta
(que reenvía el enlace, ver §1).

### 3. Login con contraseña comprueba la concesión

`POST /auth/login`, después de validar la contraseña:

- `email_verified_at IS NULL` → **403** `detail: "email_not_verified"`. La web
  ofrece reenviar (volver a hacer el alta). Va **después** de la contraseña
  para no confirmar a un tercero que el correo existe.
- Usuario **no administrador** (`is_admin`) cuyo correo no pasa
  `acceso_oauth_permitido` → **403** `detail: "access_not_granted"`, con la
  misma regla que el callback OAuth. Los administradores quedan exentos para
  que nadie se quede fuera del panel desde el que se conceden los accesos.

### 4. Cuentas que se cruzan con OAuth y con el reset

- **Google/Microsoft sobre una cuenta local sin verificar**: el proveedor ya
  verificó el buzón. `get_or_create_oauth_user` marca `email_verified_at` y
  **borra el `password_hash`** de esa cuenta, porque una contraseña puesta por
  alguien que nunca demostró el buzón no puede sobrevivir a la vinculación.
  Sobre una cuenta ya verificada, la vinculación no cambia.
- **Reset de contraseña** (`/auth/password-reset/*`): consumir el enlace
  también prueba el buzón, así que marca `email_verified_at`. Pedirlo desde
  «¿Has olvidado tu contraseña?» sigue exigiendo una cuenta con contraseña,
  como hoy. La excepción es la rama «existe y está verificada» del alta (§1):
  ahí el enlace se emite también para una cuenta sin `password_hash`, y
  consumirlo le pone la primera contraseña. Así quien entró solo por Google
  puede añadir correo y contraseña sin que el endpoint público de reset revele
  qué cuentas son solo OAuth.

### 5. Modo abierto (dev y tests)

Con `ALLOW_SELF_REGISTRATION=true` o `ENV=dev`, `/auth/register` conserva el
comportamiento actual: 201, crea la cuenta verificada, activa invitaciones y
abre sesión. Lo usan los fixtures de `tests/` y la cuenta desechable de
`web/e2e/`. Los dos agujeros de arriba siguen existiendo en ese modo, igual que
hoy: es el modo donde cualquiera puede darse de alta, y **no** debe activarse
en producción. El recorrido cerrado tiene sus propios tests (ver criterios).

### 6. Correo de acceso concedido

`services/solicitudes_acceso.py::_cuerpo_acceso` deja de decir solo «entra con
Google»: ofrece las dos vías, «crea tu cuenta con esta dirección» (enlace a
`/login?modo=registro&email=…`) o «continuar con Google». La pestaña «Crear
cuenta» de `/login` se muestra siempre, y el formulario explica que el alta
requiere tener el acceso concedido.

### 7. Requisito previo: que el correo salga de verdad

Todo el recorrido depende del correo, y **hoy en producción no sale**:

- En el log del servicio `TenderFlow` de Render, la aprobación de la solicitud
  3 (2026-10-21 10:50 UTC, dominio `deloitte.es`) dejó
  `solicitud_acceso_aviso_persona` con `enviado: false` y ningún
  `mailer_failed` ni `*_network_error` alrededor. Es la firma de
  `motivo=not_configured`: el backend `smtp` no tiene `ALERT_SMTP_USER` y/o
  `ALERT_SMTP_PASSWORD`.
- El aviso al operador de esa misma solicitud (10:01) tampoco tiene un
  `alert_email_sent`, y el webhook salió con `entregados: 0`. **Nadie recibe hoy
  ningún correo del producto**: ni el operador, ni quien pide acceso, ni el
  reset de contraseña, ni los digests.
- Ese fallo es invisible porque `mailer_not_configured` y
  `alert_smtp_not_configured` se registran a nivel `debug`, y
  `render.yaml` no declara ninguna variable de correo en el servicio de la API.

Parte de este RFC (va primero en el plan):

- Declarar en `render.yaml`, servicio de la API, `EMAIL_BACKEND` (`value: smtp`),
  `EMAIL_FROM`, `EMAIL_REPLY_TO`, `EMAIL_API_KEY`, `ALERT_EMAIL_TO`,
  `ALERT_SMTP_USER` y `ALERT_SMTP_PASSWORD` con `sync: false`, como pide
  `docs/runbooks/correo-transaccional.md` §2.6, para que aparezcan en el
  dashboard.
- Subir `mailer_not_configured` a `warning` y emitir al arrancar, en
  `ENV=prod`, un `email_backend_not_configured` a `warning` si el backend
  elegido no tiene credenciales. El proceso arranca igual: sin correo el
  producto funciona, pero tiene que verse.
- **Acción humana** (secretos; el agente no los pide ni los escribe): en Render
  → `TenderFlow` → *Environment*, poner las credenciales y redeploy. Mínimo
  para Gmail: `ALERT_SMTP_USER` (la cuenta), `ALERT_SMTP_PASSWORD` (contraseña
  de aplicación de 16 caracteres) y `ALERT_EMAIL_TO` (buzón del operador).
  Recomendado antes de escribir a dominios corporativos: un ESP con dominio
  propio (`EMAIL_BACKEND=resend`, `EMAIL_FROM`, `EMAIL_API_KEY` y el DNS del
  runbook §3). Con `From` en `gmail.com`, un buzón corporativo tiende a
  mandarlo a spam.

## Esquema

Revisión nueva (`v154_verificacion_email`), append-only:

- `users.email_verified_at TIMESTAMPTZ NULL`. Backfill
  `email_verified_at = NOW()` para **todas** las filas existentes: las OAuth las
  verificó el proveedor y las locales se respetan tal cual, para que nadie que
  hoy entra deje de poder hacerlo por este cambio.
- `email_verification_tokens`: misma forma que `password_reset_tokens` (`id`,
  `user_id` FK con `ON DELETE CASCADE`, `token_hash` único, `created_at`,
  `expires_at`, `used_at`), índice parcial de pendientes y la misma protección
  RLS de `v96`.
- `scheduler/retention.py`: purga de tokens como la de `password_reset_tokens`,
  y borrado de cuentas locales **sin verificar** con más de 7 días (sin
  `oauth_sub`, sin sesiones). Son altas que nadie confirmó.

## Alternativas consideradas

| Alternativa | Pros | Contras | Motivo de descarte |
|---|---|---|---|
| Abrir `/auth/register` a correos concedidos, sin verificar | Sin migración, cambio mínimo | Robo de invitaciones y de cuentas vía Google (Contexto) | Inseguro |
| Al aprobar, enviar un enlace «elige tu contraseña» y crear la cuenta en el clic | Un correo menos | No es «crearse la cuenta normal»; no sirve para concesiones por dominio ni para quien pierde el correo | No es el modelo pedido |
| Verificar sin tabla, con un enlace firmado sin estado | Sin tabla nueva | No es de un solo uso; replay hasta caducar | El reset (RFC 243) ya descartó lo mismo |
| Exigir la concesión también a administradores | Regla única | El admin que se revoque a sí mismo pierde el panel | Riesgo de bloqueo sin salida |

## Impacto en invariantes (AGENTS.md §3)

| Invariante | Impacto | Mitigación |
|---|---|---|
| §3.1 Typing strict | Código nuevo en `db/`, `services/`, `api/` | Strict, sin `Any` nuevo |
| §3.3 Migraciones append-only | Columna + tabla | Revisión nueva; requiere OK del mantenedor (§6) |
| §3.4 Auto-marking | Tests de integración nuevos | Por nombre/fixture, sin markers manuales |
| §3.5 DTOs | `/auth/register` cambia respuesta en modo cerrado (202); `/auth/verify-email` nuevo | DTOs tipados, OpenAPI regenerado, entrada en `NUEVAS` de `check_api_surface.py` |
| §3.6 Auth | Nuevo token de verificación; login comprueba concesión | SHA-256, un uso, 24 h, cuotas, fragmento de URL |
| §3.10 SQL en `db/` | Repositorio nuevo `db/email_verification.py` | Todo el SQL ahí |

## Plan de implementación

1. **Correo visible**: `render.yaml` + niveles de log + aviso al arrancar (§7).
   Independiente del resto; puede ir en su propio PR y desplegarse antes.
2. Migración `v154_verificacion_email` y `db/email_verification.py` (emitir,
   consumir, reemplazar alta sin verificar), con la misma disciplina de
   bloqueo que `db/password_reset.py`.
3. `services/email_verification.py`: cuerpo de los dos correos (verificar; «ya
   tienes cuenta») y envío en segundo plano.
4. Rutas: `/auth/register` (modo cerrado), `/auth/verify-email`, comprobación
   en `/auth/login`, ajuste de `get_or_create_oauth_user` y del consumo del
   reset.
5. Web: pestaña «Crear cuenta» siempre visible, mensajes de 403/202, página
   `/verificar-correo`, texto del correo de acceso concedido.
6. Retención, `docs/casos-de-uso.md` (caso nuevo «Crearme la cuenta tras
   recibir acceso» con su test de escenario), `make status`.

**Riesgo estimado:** alto (autenticación y migración).

## Criterios de aceptación

- [ ] Alta de un correo sin concesión → 403 `access_not_granted`, sin usuario creado.
- [ ] Alta de un correo concedido → 202, usuario sin verificar, correo con enlace; sin sesión ni invitaciones activadas.
- [ ] Concesión por dominio: cualquier dirección del dominio puede darse de alta y verificar.
- [ ] Login de una cuenta sin verificar con la contraseña correcta → 403 `email_not_verified`; con la incorrecta → 401 como siempre.
- [ ] Verificar → sesión abierta, invitaciones activadas, token gastado; segundo uso → 400.
- [ ] Verificar con la concesión ya revocada → 403, sin sesión.
- [ ] Segunda alta sobre una cuenta sin verificar sustituye la contraseña e invalida el enlace anterior.
- [ ] Alta sobre una cuenta verificada → mismo 202; no cambia la contraseña; envía el correo «ya tienes cuenta».
- [ ] Alta sobre una cuenta solo Google → el enlace del correo le crea la primera contraseña y después entra con ella.
- [ ] Revocar la concesión → el siguiente login con contraseña de un no-admin da 403; un admin sigue entrando.
- [ ] Google sobre una cuenta local sin verificar → queda verificada y sin `password_hash`.
- [ ] Consumir un reset marca la cuenta como verificada.
- [ ] Modo abierto (`ENV=dev`): `/auth/register` responde 201 con sesión, como hoy.
- [ ] La migración deja verificadas todas las cuentas existentes.
- [ ] En `ENV=prod` sin credenciales de correo, el arranque deja `email_backend_not_configured` a nivel `warning`.

## Antes de desplegar

- Las credenciales de correo están puestas en Render (§7) y una prueba de
  extremo a extremo llega a un buzón externo.
- Revisar en el panel de usuarios las cuentas locales **no administradoras**
  existentes: si alguna no tiene concesión, el §3 la dejaría fuera. Concederla
  antes del despliegue.
