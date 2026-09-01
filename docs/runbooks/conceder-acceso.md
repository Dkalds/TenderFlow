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

La acción es atómica desde la API: persiste el grant dinámico, marca la solicitud
como atendida y sólo después intenta enviar el correo.

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

La respuesta trae `notificado`:

| Valor | Significado | Qué hacer |
|---|---|---|
| `true` | El correo salió | Nada |
| `false` | Se pidió y **no** salió (SMTP sin configurar, buzón que rechaza, o la solicitud ya estaba atendida) | Revisar `email_producto_failed` en los logs y escribir a mano |
| `null` | No se pidió aviso | Nada |

El orden lo impone el servidor: si no puede persistir la concesión, no marca la
solicitud como atendida ni envía el correo.

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
- Cada alta/baja dinámica deja `access_grant.granted`/`access_grant.revoked` sin
  copiar el email o dominio al detalle del audit log.
- El correo a la persona registra sólo el **dominio** del destinatario
  (`solicitud_acceso_aviso_persona`), nunca la dirección completa.
- Reenviar el formulario con el mismo email **no** crea una fila nueva mientras
  la anterior siga pendiente: se actualiza la que ya había.

## Ficheros

- `api/routes/admin_solicitudes.py` — la cola y el cambio de estado.
- `services/solicitudes_acceso.py` — qué dicen los avisos y a quién.
- `api/routes/publico_solicitudes.py` — la entrada del formulario y los dos avisos.
- `db/solicitudes_acceso.py` — la persistencia de la cola.
