# Runbook: conceder acceso a quien lo ha solicitado

El acceso a TenderFlow es **por invitación** y se concede a mano. Este runbook
es el procedimiento completo, de la solicitud a la persona dentro.

Existe porque el embudo tenía el final sin escribir: el formulario de la landing
guardaba la petición, pero nadie avisaba al operador salvo por un webhook que
puede no estar configurado, y a quien pedía acceso no se le escribía **nunca**
—pese a que la página de gracias le promete literalmente que "la respuesta llega
por correo"—.

---

## 0. Antes de nada: ¿me entero de que hay solicitudes?

Hay dos canales, y conviene tener al menos uno vivo:

| Canal | Cómo se activa | Cómo comprobar que funciona |
|---|---|---|
| **Email** | `ALERT_EMAIL_TO` + `ALERT_SMTP_USER` + `ALERT_SMTP_PASSWORD` | Buscar `alert_email_sent` en los logs tras una solicitud |
| **Webhook** | Suscripción a `solicitud_acceso.creada` con su host en `WEBHOOK_ALLOWED_HOSTS` | `GET /api/v1/webhooks` y `POST /api/v1/webhooks/{id}/ping` |

Ninguno de los dos lleva el email ni el mensaje de quien escribe: dicen que hay
algo que atender y cuántas cosas hay. El dato de contacto se lee en la cola, que
exige ser administrador.

Si **ninguno** está configurado, la cola solo se descubre mirándola, y este
runbook empieza por el paso 1 cada mañana.

---

## 1. Ver la cola

```bash
curl -s -H "X-API-Key: $ADMIN_API_KEY" \
  "$API/api/v1/admin/solicitudes-acceso?estado=pendiente" | jq
```

Cada fila trae `id`, `email`, `empresa`, `mensaje`, `origen` y `created_at`.

---

## 2. Decidir, conceder y avisar

Lo que es atómico es **la concesión y el cambio de estado**: van en una misma
transacción, así que no puede quedar una solicitud atendida sin concesión ni una
concesión con la solicitud pendiente. La auditoría y el correo vienen después,
con la transacción ya confirmada, y los dos son best-effort:

- si el registro de auditoría falla, la concesión se queda hecha y el fallo va al
  log (`audit_log_persist_failed`), no a la respuesta;
- si el correo no sale, la respuesta lo dice (`notificado: false`).

`conceder` avisa siempre a la persona, se pase o no `notificar`.

Concesión a una sola dirección (opción normal):

```bash
curl -s -X PATCH -H "X-API-Key: $ADMIN_API_KEY" -H "Content-Type: application/json" \
  -d '{"estado":"atendida","conceder":"email","notificar":true}' \
  "$API/api/v1/admin/solicitudes-acceso/<id>" | jq
```

Concesión a todo el dominio (sólo tras aprobar al cliente completo):

```bash
curl -s -X PATCH -H "X-API-Key: $ADMIN_API_KEY" -H "Content-Type: application/json" \
  -d '{"estado":"atendida","conceder":"domain","notificar":true}' \
  "$API/api/v1/admin/solicitudes-acceso/<id>" | jq
```

La respuesta incluye `grant_id`, que identifica la concesión revocable. Las
variables `OAUTH_ALLOWED_EMAILS`/`OAUTH_ALLOWED_DOMAINS` se conservan como
bootstrap de emergencia y no se editan para altas normales.

**El dominio de un proveedor de correo público no se concede.** Si la solicitud
viene de `gmail.com`, `outlook.com`, `hotmail.com`, `yahoo.com`, `icloud.com` o
cualquier otro de la lista `DOMINIOS_DE_CORREO_PUBLICO`
(`services/access_grants.py`), `"conceder":"domain"` responde **422** con el
motivo y no cambia nada: ni concesión ni estado. Conceder ese dominio dejaría
entrar a cualquiera con una cuenta ahí, y el formulario de solicitud es público.
Para esas solicitudes se usa `"conceder":"email"`, que sigue funcionando.
También es 422 una solicitud cuyo correo no dé para la concesión pedida (por
ejemplo, un dominio sin punto).

La respuesta trae `notificado`:

| Valor | Significado | Qué hacer |
|---|---|---|
| `true` | El correo salió | Nada |
| `false` | Se pidió y **no** salió: SMTP sin configurar, buzón que rechaza, la solicitud ya estaba atendida, o se pidió avisar **sin conceder** a una dirección que no tiene acceso (`solicitud_acceso_aviso_sin_acceso` en los logs) | Revisar `email_producto_failed` en los logs y escribir a mano. En el último caso falta además conceder; como la solicitud ya quedó atendida, concederla ahora no reenvía el correo |
| `null` | No se pidió aviso | Nada |

El orden lo impone el servidor: si no puede persistir la concesión, no marca la
solicitud como atendida ni envía el correo.

`notificar: true` **sin** `conceder` no habilita a nadie: marca la solicitud como
atendida y solo escribe a la persona si su dirección ya entra (lista estática o
una concesión anterior, por ejemplo la de su dominio). Si no entra, el estado
cambia igual y la respuesta lleva `notificado: false`.

Marcar `notificar: true` sobre una solicitud **que ya estaba `atendida`** no
reenvía nada (devuelve `notificado: false`): pulsar dos veces no puede escribir
dos veces a la misma persona.

---

## 3. Revocar una concesión dinámica

```bash
curl -s -H "X-API-Key: $ADMIN_API_KEY" \
  "$API/api/v1/admin/solicitudes-acceso/grants" | jq
curl -s -X DELETE -H "X-API-Key: $ADMIN_API_KEY" \
  "$API/api/v1/admin/solicitudes-acceso/grants/<grant_id>" | jq
```

Revocar impide nuevos logins. Las sesiones ya abiertas mantienen su política de
caducidad; para cortar una cuenta existente, desactívala desde Administración.
Una entrada estática de entorno no puede revocarse desde este endpoint.

---

## 4. Descartar

```bash
curl -s -X PATCH -H "X-API-Key: $ADMIN_API_KEY" -H "Content-Type: application/json" \
  -d '{"estado":"descartada"}' "$API/api/v1/admin/solicitudes-acceso/<id>"
```

Un descarte **nunca** envía correo, aunque se pase `notificar: true`: el aviso
dice "ya puedes entrar", y mandárselo a alguien a quien se ha rechazado sería
peor que el silencio.

---

## Comprobaciones

- Todo cambio de estado queda en el log de auditoría encadenado
  (`solicitud_acceso.estado`), verificable con `scripts/verify_audit_chain.py`.
- Cada alta/baja dinámica deja `access_grant.granted`/`access_grant.revoked` con
  el `user_id` del administrador y el id de la concesión, sin copiar el email o
  dominio al detalle del audit log. Quién **revocó** solo consta ahí: la tabla
  `access_grants` guarda quién concedió (`granted_by`), no quién revocó.
- El correo a la persona registra sólo el **dominio** del destinatario
  (`solicitud_acceso_aviso_persona`), nunca la dirección completa.
- Reenviar el formulario con el mismo email **no** crea una fila nueva mientras
  la anterior siga pendiente: se actualiza la que ya había.

## Ficheros

- `api/routes/admin_solicitudes.py` — la cola, el cambio de estado, conceder y revocar.
- `db/access_grants.py` — las concesiones: conceder (con la solicitud, en una
  transacción), revocar, listar y la consulta que hace el login.
- `services/access_grants.py` — qué no se puede conceder (proveedores de correo público).
- `services/solicitudes_acceso.py` — qué dicen los avisos y a quién.
- `api/routes/publico_solicitudes.py` — la entrada del formulario y los dos avisos.
- `db/solicitudes_acceso.py` — la persistencia de la cola.
