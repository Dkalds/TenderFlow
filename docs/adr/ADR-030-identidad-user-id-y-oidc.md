# ADR-030 — La identidad interna es `user_id`; los proveedores OIDC son intercambiables

- **Estado:** aceptado
- **Fecha:** 2026-09-06
- **Relacionado:** [ADR-015](ADR-015-identidad-tenderflow.md) (identidad del
  *producto*, no del usuario), [ADR-022](ADR-022-frontera-de-persistencia.md)
- **Implementa:** S1.2 y S1.4 de
  [docs/plans/2026-09-plan-arquitectura-v2.md](../plans/2026-09-plan-arquitectura-v2.md),
  T4 de ese mismo plan, y fija la regla de propiedad del dato que
  C2.2 del [plan complementario](../plans/2026-09-plan-arquitectura-v2-complementario.md)
  necesita para borrar una organización

---

## Contexto

Hoy conviven dos identificadores de usuario:

- **`users.id`**, la clave real, que usan sesiones, membresías y auditoría.
- **`user_key`**, la clave opaca `sha256(email o key_hash)[:16]` que
  `shared/identity.user_key_from_email` deriva y que usan `watchlist_items`,
  `watchlist_rules`, `user_profiles`, `competitive` y compañía.

`user_key` se eligió cuando no había tabla de usuarios y la única identidad era
el email de una API key. Hoy tiene tres consecuencias:

1. **Cambiar de email pierde los datos.** Un usuario que cambia de correo
   estrena `user_key` y con él favoritos, reglas, vistas y descartes.
2. **El borrado GDPR es por derivación**, no por clave. `services/gdpr.py`
   documenta el bug que costó descubrirlo.
3. **Colisiona con OAuth.** El mismo humano entrando por Google y por
   contraseña puede resolver a dos claves si el email difiere en mayúsculas o
   en alias.

En paralelo, el login OAuth está cableado a Google dentro de
`api/routes/auth.py`: los `client_id`, el documento de descubrimiento y el
mapeo de claims viven en el flujo, no en una tabla. Añadir Microsoft Entra ID
—que un partner ya pidió— significaría duplicar el flujo entero.

---

## Decisión

### A. `users.id` es la identidad interna. `user_key` está en retirada

Toda tabla con dato de usuario tiene o tendrá `user_id INTEGER REFERENCES
users(id)`. La migración es en tres tiempos, y este ADR fija los tres:

| Fase | Qué | Dónde |
|---|---|---|
| 1 | Ratchet: la lista de ficheros que usan `user_key` solo encoge; `user_key_from_email` marcada `@deprecated` | S1.4 |
| 2 | Columna `user_id` + backfill por email + **lectura dual** | T4 |
| 3 | `user_key` deja de escribirse; GDPR anonimiza por id; el ratchet llega a cero | T4 |

La lectura dual de la fase 2 no es opcional: el backfill por email no puede
resolver el 100 % (API keys sin usuario, filas huérfanas), y una lectura que
solo mire `user_id` perdería en silencio lo que no resolvió.

### B. El proveedor de identidad es dato, no código

Los proveedores viven en una tabla (`google`, `microsoft`), cada uno con su
documento de descubrimiento OIDC. PKCE, `nonce` y `state` son idénticos para
todos; `access_grants` y la allowlist por dominio aplican igual.
`users.oauth_provider` guarda con cuál entró.

Un proveedor nuevo es una fila y un secreto, no un flujo nuevo.

**Solo OIDC.** SAML y SCIM quedan fuera de forma explícita: el
aprovisionamiento automático espera a que exista una organización que lo pida.

### C. Un email es un humano, normalizado antes de comparar

El email se normaliza (minúsculas, sin espacios) antes de resolver identidad,
en el único sitio donde se resuelve. Dos proveedores que devuelven el mismo
email normalizado son el mismo `users.id`.

### D. Dato personal y dato corporativo tienen dueños distintos

Esta es la regla que el borrado de organización (C2.2) y el export GDPR
necesitan, y hasta hoy no estaba escrita:

| Clase | Ejemplos | Dueño | Al borrar el usuario | Al borrar la organización |
|---|---|---|---|---|
| **Personal** | perfil de scoring, favoritos, reglas, notas privadas, notificaciones, sesiones, API keys personales | el usuario | se anonimiza o se borra | sobrevive (se queda con el usuario) |
| **Corporativo** | oportunidades, comentarios, tareas, capacidades de la organización, plantillas go/no-go, API keys de organización | la organización | **sobrevive**, con el autor anonimizado | se borra con ella |
| **Auditoría** | `audit_log` | la plataforma | se conserva con actor anonimizado | se conserva |

Motivo: una oportunidad trabajada por tres personas no es dato personal de la
que se va, y borrarla al darse de baja destruiría trabajo de la organización.
Simétricamente, borrar la organización sí se lleva su dato corporativo, porque
sin ella no tiene dueño.

`audit_log` registra actor y objetivo **sin copiar emails**: guarda ids. Un log
de auditoría que replica el dato personal que el borrado eliminó no es un log,
es una copia.

---

## Consecuencias

**A favor.** Cambiar de email deja de perder datos. El borrado GDPR es un
`DELETE`/`UPDATE` por clave, no una derivación. Un proveedor OIDC nuevo cuesta
una fila. El borrado de organización tiene una regla que no hay que inventar
caso a caso.

**En contra.** La fase 2 es una migración larga con lectura dual, y durante
ella hay dos caminos de lectura vivos. El ratchet de fase 1 es lo que impide
que esa ventana se haga permanente.

**Riesgo.** El backfill por email no resuelve el 100 %. Mitigación: lectura
dual mientras el ratchet no esté en cero, y un test de cambio de email que
comprueba que favoritos, reglas, vistas, descartes, notificaciones y
oportunidades sobreviven.
