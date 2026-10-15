---
rfc: 2026-10-15-baja-totp-con-codigo
title: Quitar el segundo factor exige un código (`DELETE /auth/totp` con `code` requerido)
issue: (sin issue: PR #471, línea A «Cuenta y acceso»)
author: agent:claude-code
date: 2026-10-15
status: implemented
evidence: api/routes/auth.py::remove_totp, tests/test_escenario_cuenta_y_acceso.py (CU-25)
---

## Contexto

`DELETE /api/v1/auth/totp` desactivaba el segundo factor sin cuerpo. Le bastaba
una sesión reciente (`require_recent_session_auth`) que ya hubiera pasado el
segundo factor. Quien se sentara delante de un navegador con la sesión abierta
podía quitarlo sin tener el móvil, que es justo lo que el segundo factor
protege.

La pantalla para activar y quitar el segundo factor (Ajustes › Seguridad, CU-25)
llega en la misma PR. Antes no existía, y la ruta no tenía ningún consumidor en
`web/`.

## Cambio

La petición lleva `{"code": "..."}`, que pasa a ser **requerido**:

- Un código TOTP vigente, o uno de los códigos de recuperación (que queda
  gastado). Quien perdió el móvil es quien más necesita quitarlo.
- El intento fallido cuenta en el mismo límite que el login
  (`_record_mfa_failure`). Si no, esta ruta serviría para adivinar códigos sin
  ventana de bloqueo.
- Sin segundo factor activo responde `409`, y eso no cuenta como intento
  fallido.

`scripts/check_api_breaking.py` lo marca como incompatible («el campo `code` de
la petición pasa a ser requerido»), y lo es: un cliente que llamara sin cuerpo
recibe `422` donde antes recibía `200`.

## Por qué sin ventana de deprecación

La política de 90 días (`docs/api-design.md`, «Política de deprecación») existe
para no convertir un cambio de quien depreca en un incidente de quien consume.
Aquí no hay consumidor al que avisar:

- La ruta exige sesión de cookie reciente: una clave de API no la puede llamar.
- No está en el contrato público (`api/openapi-public.json`).
- El único cliente posible es la consola, que empieza a usarla en esta misma PR
  y ya manda el código.

Mantener noventa días la variante sin código sería mantener abierto el hueco que
el cambio cierra.

## Alternativas descartadas

- **`code` opcional en el esquema y obligatorio en el handler**: esconde la
  ruptura al comparador de contratos sin quitarla. Es la misma
  incompatibilidad, sin rastro escrito.
- **Pedir la contraseña en vez del código**: no prueba la posesión del segundo
  factor, que es lo que se está quitando.
