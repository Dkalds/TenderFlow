---
id: ADR-037
title: "Un correo solo cuenta si el proveedor lo acredita, y no une cuentas de proveedores distintos"
status: accepted
date: 2026-10-23
deciders: "Daniel Kalitovics"
related:
  - "[[ADR-030-identidad-user-id-y-oidc]]"
  - "[[ADR-015-identidad-tenderflow]]"
tags: [adr]
---

# ADR-037 — Un correo solo cuenta si el proveedor lo acredita, y no une cuentas de proveedores distintos

- **Estado:** aceptado
- **Fecha:** 2026-10-23
- **Revisa:** [ADR-030](ADR-030-identidad-user-id-y-oidc.md) §C («dos
  proveedores que devuelven el mismo email normalizado son el mismo
  `users.id`») y la decisión D17 del
  [plan de arquitectura v2](../plans/2026-09-plan-arquitectura-v2.md)
  (Entra ID multi-tenant con la allowlist por dominio). El resto de ADR-030
  sigue vigente.
- **Cierra:** el ítem P1 «Microsoft/Entra: la allowlist se decide sobre un
  correo que puede no estar verificado» del
  [backlog](../IMPROVEMENT_BACKLOG.md), salvo la comprobación en Render que
  solo puede hacer el propietario.

---

## Contexto

D17 eligió Entra ID multi-tenant (`common`) y dejó que la allowlist por dominio
y `access_grants` decidieran quién entra, como con Google. Esa decisión da por
hecho que el dominio del correo dice de qué organización es la cuenta. Con
Google es verdad: el camino de Google exige `email_verified`. Con Entra no lo
era:

- `verify_oidc_id_token` no exigía ningún claim sobre el correo (Entra no emite
  `email_verified`).
- `_email_from_claims` tomaba `email`, y si faltaba `preferred_username` o
  `upn`. Los tres los puede escribir el administrador de **cualquier** tenant
  de Entra; Microsoft documenta `email` y `preferred_username` como mutables y
  no aptos para autorizar.
- `get_or_create_oauth_user` vinculaba por correo: si existía una cuenta con
  esa dirección, le reescribía `oauth_provider`/`oauth_sub` y devolvía su id.

Juntos: quien administrase un tenant cualquiera podía crear un usuario con el
correo de otra persona, pasar la allowlist como si fuera ella y quedarse con su
cuenta de TenderFlow. Es la clase de fallo que se conoce como «nOAuth».

ADR-030 §C empeoraba el alcance: al declarar que dos proveedores con el mismo
correo son el mismo `users.id`, convertía cualquier proveedor débil en una
llave de las cuentas de todos los demás.

## Decisión

### 1. La allowlist solo mira un correo que el proveedor acredita

Cada proveedor declara qué claim booleano del `id_token` acredita el correo
(`_OAuthProvider.claim_correo_verificado` en `api/routes/auth.py`), y
`verify_oidc_id_token` lo exige con valor exactamente `true`. El parámetro no
tiene valor por defecto: un proveedor nuevo tiene que decirlo.

- **Google:** `email_verified`, en su verificador propio
  (`shared/auth_core.py`). **No cambia.**
- **Microsoft Entra ID:** `xms_edov` — *email domain owner verified*: el
  dueño del dominio del correo lo tiene verificado en el tenant que emite el
  token. Un tenant no puede verificar un dominio que no controla, así que con
  `xms_edov` el correo dice de qué organización es la cuenta, que es lo que D17
  daba por hecho.

Además, el correo de Microsoft sale **solo** de `email`, que es el claim que
`xms_edov` acredita (`_OAuthProvider.claims_de_correo`). `preferred_username` y
`upn` dejan de servir de respaldo: una cuenta de trabajo cuyo tenant no puebla
`email` no entra (`email_not_allowed`). Es el precio de no decidir sobre algo
que nadie acredita.

Se valoraron las otras dos salidas que el backlog dejaba abiertas:

- **Una lista de `tid` permitidos.** Cierra el agujero, pero convierte el alta
  de cada cliente en un cambio de configuración, que es lo que D17 quería
  evitar.
- **Dejar de decidir sobre `email` y usar `oid`/`sub`.** Obligaría a dar de
  alta a cada persona a mano antes de su primer login; hoy el acceso se
  concede por correo o por dominio desde el panel.

### 2. Una identidad no se vincula a la cuenta de otro proveedor

`get_or_create_oauth_user`, cuando la identidad (proveedor, `sub`) no existe y
sí una cuenta con el mismo correo:

| La cuenta existente… | Qué pasa | Por qué |
|---|---|---|
| no tiene proveedor (alta con contraseña, o creada a mano) | se vincula, como antes | el proveedor acaba de acreditar el correo, que es lo mismo que demuestra un enlace de recuperación: quien controla el buzón ya podía ponerle contraseña a esa cuenta |
| es del mismo proveedor, con otro `sub` | se vincula, como antes | el proveedor responde de sus propias identidades (Google recrea cuentas; Microsoft da un `sub` por aplicación) |
| es de **otro** proveedor | **no** se vincula: `CuentaDeOtroProveedorError` | un tenant de Entra no responde de una cuenta de Google, ni al revés |

El callback convierte ese error en `/login?error=account_other_provider`
(«Ese correo ya tiene cuenta con otro proveedor: entra con el que usaste la
primera vez»), deja `auth.login_failed` con `reason=account_other_provider` en
el rastro de la cuenta afectada —un intento así puede ser una suplantación— y
no toca la cuenta.

**La cuenta local sin proveedor** era el caso dudoso. Se vincula también con
Microsoft porque, con el punto 1, Microsoft solo llega aquí con `xms_edov`, y
entonces quien entra es alguien a quien el dueño del dominio reconoce esa
dirección: la organización que controla el buzón. Esa organización ya podía
quedarse la cuenta pidiendo un enlace de recuperación, así que vincular no
añade ningún poder. Lo que se borra al vincular es, como antes, la contraseña
de una cuenta **sin verificar** (RFC 2026-10-21 §4).

Esto revisa ADR-030 §C: el correo sigue normalizándose antes de comparar y
sigue siendo cómo se encuentra una cuenta, pero dos proveedores con el mismo
correo **no** son el mismo `users.id` por eso solo. Unir dos identidades de
proveedores distintos en una cuenta, si algún día hace falta, será una acción
explícita de quien ya está dentro, no un efecto del login.

### 3. Qué tiene que configurar quien active Microsoft

`xms_edov` es un claim **opcional**: Entra no lo emite si no se pide. Antes de
poner `OAUTH_MICROSOFT_CLIENT_ID` en producción:

1. Portal de Azure → *Microsoft Entra ID* → *App registrations* → la
   aplicación de TenderFlow → *Token configuration* → *Add optional claim* →
   tipo **ID** → marcar `email` y `xms_edov`. Equivale a añadir al manifiesto,
   en `optionalClaims.idToken`, `{"name": "email"}` y `{"name": "xms_edov"}`.
2. Entrar una vez con una cuenta de trabajo real y comprobar en el log de la
   API que no aparece `oidc_id_token_email_not_verified`. Si aparece con una
   cuenta legítima, el claim no llega (paso 1) o llega en otro formato: el
   verificador solo acepta el booleano JSON `true`, y cualquier otra cosa
   —ausente, `false`, `"true"`, `1`— se rechaza. No se ha probado contra un
   tenant real; hasta hacerlo, la forma exacta del claim es una suposición
   apoyada en la documentación de Microsoft.

Sin el paso 1 nadie entra con Microsoft: el fallo es cerrado, se ve en ese log
y la persona lee «No se pudo completar el inicio de sesión».

## Consecuencias

- **Positivas.** Se cierra la suplantación de una cuenta existente desde un
  tenant ajeno, y también el alta indebida de un correo de un dominio
  concedido. La regla de vinculación es la misma para cualquier proveedor que
  venga.
- **Negativas.** Las cuentas de trabajo sin `email` poblado en su tenant no
  pueden entrar con Microsoft. Quien entró primero con Google y quiere entrar
  con Microsoft (o al revés) no puede, y no hay pantalla para unir las dos
  identidades: tendrá que seguir con el primero.
- **Pendiente del propietario.** Comprobar en Render qué valor tiene
  `OAUTH_MICROSOFT_CLIENT_ID` y, antes de activarlo, el paso 3.

## Dónde está

- `shared/identity.py::verify_oidc_id_token` (parámetro `email_verified_claim`).
- `api/routes/auth.py`: `_OAuthProvider.claim_correo_verificado`,
  `claims_de_correo`, `_email_from_claims` y el `except` de
  `CuentaDeOtroProveedorError` en `_oauth_callback_impl`.
- `db/users.py::get_or_create_oauth_user` y `CuentaDeOtroProveedorError`.
- Tests: `tests/test_oauth_vinculacion_entre_proveedores.py` (token de Entra
  firmado de verdad contra un JWKS simulado y la BD real),
  `tests/test_s1_oidc_verify.py` y `tests/test_s1_oauth_providers.py`.
