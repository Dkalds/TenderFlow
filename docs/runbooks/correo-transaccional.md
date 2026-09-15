# Runbook: correo transaccional

**Propósito**: saber por dónde sale cada correo del producto, cómo cambiar de
transporte (SMTP de Gmail ↔ un ESP con dominio propio), qué tiene que estar en
el DNS para que llegue a la bandeja de entrada y no a spam, qué mirar cuando
deja de llegar, y qué **no** hace todavía el sistema (rebotes).

**Responsable**: el mantenedor.

**Última verificación contra el repositorio**: 2026-09-14 (Ola 1 · «Correo
como sistema»). Contrastado leyendo `observability/mailer.py`,
`observability/alerts.py`, `config/settings.py`, `scheduler/watchlist_alerts.py`
y `api/routes/watchlist_rules.py`. **No se contrastó contra Render ni contra
ningún proveedor**: lo que dependa de un dashboard va marcado como acción
humana.

---

## 1. Qué correo sale y por dónde

Todo el correo del proyecto —de operación y de producto— entra por
`observability/alerts.py::_entregar_email` y sale por
`observability/mailer.py::enviar`. No hay otra puerta; si aparece una
(`smtplib` fuera de `mailer.py`), es una regresión.

| Correo | Quién lo dispara | Función de entrada |
|---|---|---|
| Alertas de operación (`[TenderFlow] [WARN] …`) | `scheduler/*`, `services/ml/*`, healthcheck en GitHub Actions | `observability.alerts.notify` → `_send_smtp` |
| Digest de watchlist (diario / semanal / inmediato) | `scheduler/watchlist_alerts.py::send_pending_digests` | `enviar_email_transaccional(…, unsubscribe_url=…)` |
| Evento suelto (asignación, comentario) | `scheduler/jobs/event_dispatch.py` | `enviar_email_transaccional` |
| Invitación a una organización | `services/organizations.py` | `enviar_email_transaccional` |
| Recuperación de contraseña | `services/password_reset.py` | `enviar_email_transaccional` |
| Aviso de acceso concedido | `services/solicitudes_acceso.py` | `enviar_email_transaccional` |
| **Informe semanal de pipeline** (con PDF adjunto) | `scheduler/jobs/informes_programados.py` | `mailer.enviar(Mensaje(..., adjuntos=[...]))` |

Lo que el mailer garantiza a todos, sea cual sea el backend:

- **Texto + HTML siempre.** Si el llamante solo pasa HTML, el texto plano se
  deriva conservando los enlaces (`texto_desde_html`). Un correo solo-HTML es
  la señal de spam más barata de evitar.
- **`Message-ID` y `Date`** por SMTP (un relay no siempre los añade). Por HTTP
  los pone el proveedor: son su identificador para rebotes y quejas.
- **`List-Unsubscribe` + `List-Unsubscribe-Post`** (RFC 8058) cuando el
  llamante pasa una URL de baja. Hoy la pasa el digest, con la misma URL
  firmada del pie del correo (`services/email_digest.py::url_de_baja_alertas`).
  `GET /api/v1/watchlist/rules/baja` atiende a la persona que pulsa el enlace;
  `POST` en la misma ruta atiende al cliente de correo que ejecuta la baja en
  un clic (Gmail, Yahoo y Outlook mandan ese POST sin cookies y no siguen
  redirecciones, de ahí que el POST responda 200 y no 303).
- **Adjuntos** (`Mensaje.adjuntos`, desde 2026-09-15). Por SMTP el
  `multipart/alternative` de siempre pasa a ser la primera parte de un
  `multipart/mixed`; por los dos ESP el contenido viaja en base64 dentro del
  JSON. **Sin adjuntos el correo conserva la forma de siempre**, y eso es
  deliberado: cambiar la estructura MIME de todo el correo por una función que
  la mayoría de los mensajes no usa sería riesgo gratis.

  La trampa que esto evita: colgar texto, HTML y PDF como tres hermanos de un
  `mixed` hace que el cliente enseñe el texto plano **y** el HTML uno detrás de
  otro en vez de elegir. Las alternativas van juntas en su propio contenedor,
  y hay test que lo fija (`tests/test_informes_programados.py`).

  Un adjunto sin bytes o sin nombre se descarta antes de salir: por SMTP sería
  una parte vacía y por HTTP un 422 del ESP que tumbaría el correo entero.
- **Nunca propaga.** Un proveedor caído devuelve un `ResultadoEnvio` con
  `ok=False`; quien llama lo registra. No hay reintentos en esta capa.

## 2. Backends y cómo cambiar

`EMAIL_BACKEND` elige el transporte. Variables (todas en `config/settings.py`,
documentadas en `.env.example`):

| Variable | Default | Uso |
|---|---|---|
| `EMAIL_BACKEND` | `smtp` | `smtp` · `resend` · `postmark` · `console` |
| `EMAIL_FROM` | `""` → `ALERT_SMTP_USER` | Dirección remitente. Con un ESP, **obligatoria** y de un dominio verificado |
| `EMAIL_FROM_NAME` | `TenderFlow` | Nombre que se muestra: `TenderFlow <no-reply@…>` |
| `EMAIL_REPLY_TO` | `""` | Reply-To global (un buzón de soporte, por ejemplo) |
| `EMAIL_API_KEY` | `""` | Clave del ESP. Secreto: solo por variable de entorno, nunca en el repo |
| `ALERT_SMTP_*` | Gmail, 587 | Solo el backend `smtp` |

En `ENV=prod` con `resend` o `postmark`, `EMAIL_API_KEY` y `EMAIL_FROM` son
obligatorias y el proceso **no arranca** sin ellas (validador
`_validate_prod_email_backend`). Con el default `smtp` nada cambia respecto a
antes.

### 2.1 `smtp` (el que hay)

Es el código que siempre existió: STARTTLS contra `ALERT_SMTP_HOST:PORT` con
la contraseña de aplicación de Gmail. Limitaciones que motivan el resto de
este runbook: Gmail reescribe el `From` a la cuenta autenticada (salvo alias
verificado), así que `EMAIL_FROM` no sirve para enviar desde un dominio propio;
el límite diario de una cuenta normal es bajo; y no hay ninguna señal de rebote
ni de queja.

### 2.2 `resend`

`POST https://api.resend.com/emails` con `Authorization: Bearer <EMAIL_API_KEY>`.

1. En Resend: **Domains → Add domain** con el dominio de `EMAIL_FROM` (o un
   subdominio, `mail.tudominio.es`, que aísla la reputación del dominio
   principal). Publicar los registros que te da (§3) y esperar a «Verified».
2. **API Keys → Create**: permiso *Sending access* y, si lo ofrece,
   restringido a ese dominio. Copiar la clave: es `EMAIL_API_KEY`.
3. Render (dashboard): `EMAIL_BACKEND=resend`, `EMAIL_FROM=no-reply@…`,
   `EMAIL_API_KEY=<clave>`. Redeploy.
4. Prueba de humo (§5).

Las etiquetas (`tags`) del mensaje salen como `{"name": "category", "value":
…}`; Resend solo admite `[A-Za-z0-9_-]` y el mailer normaliza el resto a `-`.

### 2.3 `postmark`

`POST https://api.postmarkapp.com/email` con `X-Postmark-Server-Token:
<EMAIL_API_KEY>`.

1. En Postmark: **Sender Signatures → Domains → Add domain** y publicar DKIM
   y Return-Path (§3). Sin dominio verificado, al menos una *Sender Signature*
   confirmada para la dirección exacta de `EMAIL_FROM`.
2. **Servers → (tu server) → API Tokens**: copiar el *Server API token*. Es
   `EMAIL_API_KEY`. Se usa el *message stream* por defecto (`outbound`).
3. Render: `EMAIL_BACKEND=postmark`, `EMAIL_FROM`, `EMAIL_API_KEY`. Redeploy.
4. Prueba de humo (§5).

Postmark admite **una** etiqueta por mensaje: el mailer manda la primera.
Responde `200` con `ErrorCode: 0` cuando acepta; cualquier otro `ErrorCode`
se trata como rechazo aunque el HTTP sea 200.

### 2.4 `console`

No envía nada: escribe el correo entero (dominio del destinatario, asunto,
encabezados y cuerpo en texto) al log estructurado. Para desarrollo —ver el
enlace de un reset o de una invitación sin buzón— y para tests. **Nunca en
producción**: el validador no lo impide porque un entorno de staging sin salida
de correo es un uso legítimo.

### 2.5 Vuelta atrás

`EMAIL_BACKEND=smtp` (o borrar la variable) y redeploy. Las credenciales
`ALERT_SMTP_*` no se tocan al pasar a un ESP precisamente para que la vuelta
atrás sea un cambio de una variable.

### 2.6 Dónde viven las variables

- **Render (API y worker)**: dashboard → *Environment*. `render.yaml` hoy no
  declara `EMAIL_*`; conviene añadirlas con `sync: false` (`EMAIL_BACKEND`
  puede llevar `value: smtp`) para que aparezcan en el dashboard sin buscarlas.
- **GitHub Actions** (`healthcheck.yml` y los jobs que llaman a `notify`):
  llevan su propio bloque `env:` con `ALERT_*`. Si se quiere que las alertas de
  esos jobs también salgan por el ESP hay que añadir ahí `EMAIL_BACKEND`,
  `EMAIL_FROM` y `EMAIL_API_KEY` (como secret). Mientras no se haga, esos jobs
  siguen por SMTP: no es un fallo, es el default.
- **Rotación de `EMAIL_API_KEY`**: 90 días (tabla de `docs/SECURITY.md`).
  Crear la clave nueva en el proveedor → sustituirla en Render → redeploy →
  revocar la vieja. No hay periodo de solape que gestionar porque el mailer
  lee la clave en cada envío.

## 3. Checklist DNS del dominio remitente (SPF / DKIM / DMARC)

Sin esto un ESP entrega, pero Gmail y Yahoo lo mandan a spam o lo rechazan:
desde febrero de 2024 exigen SPF **y** DKIM alineados con el dominio del
`From`, DMARC publicado, `List-Unsubscribe` de un clic y una tasa de quejas
por debajo del 0,3 %. El mailer cubre los encabezados; el DNS lo pone el
mantenedor. Los valores exactos los da cada proveedor al añadir el dominio;
esto es la lista de lo que tiene que quedar publicado.

- [ ] **DKIM**: el registro (TXT o CNAME según proveedor, selector tipo
      `resend._domainkey` / `<hash>._domainkey`) publicado y marcado como
      verificado en el proveedor. Es el que **alinea** con el `From`: sin él
      DMARC falla aunque SPF pase.
- [ ] **SPF**: el `include:` del proveedor en el TXT del dominio (o del
      subdominio de envío / Return-Path que el proveedor configure). Un solo
      registro SPF por nombre, máximo 10 lookups; si ya hay uno (Google
      Workspace…), se **amplía**, no se duplica.
- [ ] **Return-Path / bounce domain**: el CNAME que pide el proveedor
      (`pm-bounces.` en Postmark; `send.` o el que indique Resend). Es donde
      vuelven los rebotes y lo que hace que SPF alinee.
- [ ] **DMARC**: `_dmarc.<dominio>` TXT `v=DMARC1; p=none;
      rua=mailto:<buzón-informes>` para empezar; subir a `p=quarantine` y luego
      `p=reject` cuando los informes muestren que todo el correro legítimo
      alinea. Sin DMARC publicado, Gmail trata el dominio como sospechoso.
- [ ] **`EMAIL_FROM` en ese dominio** (o subdominio) y **no** en `gmail.com`:
      con un `From` de Gmail, DMARC de Google (`p=none` pero con alineación
      exigida por los receptores) hace que el correo vaya a spam.
- [ ] **Registro PTR / reverse DNS**: lo gestiona el ESP para sus IPs; no hay
      nada que hacer salvo que se envíe desde IP propia (no es el caso).
- [ ] **Verificación**: `dig TXT <selector>._domainkey.<dominio>`, `dig TXT
      <dominio>` (SPF) y `dig TXT _dmarc.<dominio>`; después un envío de
      prueba a una cuenta de Gmail y «Mostrar original» → `SPF: PASS`,
      `DKIM: PASS`, `DMARC: PASS`. Google Postmaster Tools con el dominio dado
      de alta para ver reputación y tasa de spam.

## 4. Qué monitorizar

- **Métrica**: `alert_delivery_failed_total{canal="email", motivo=…}`
  (`observability/runtime_metrics.py`). Motivos: `not_configured` (faltan
  credenciales o remitente), `smtp`, `network` (no se pudo hablar con el
  transporte: DNS, TLS, timeout de 15 s), `provider` (el ESP respondió con
  error: clave revocada, remitente no verificado, cuota), `invalid` (mensaje
  sin destinatario o sin cuerpo). Un `provider` sostenido tras un cambio de
  clave es la firma de una rotación a medias. Solo cubre los procesos
  scrapeables (API y worker); los jobs de GitHub Actions mueren al terminar y
  ahí solo queda el log.
- **Log** (structlog): `mailer_failed` (backend, motivo, error del proveedor
  recortado a 300 caracteres), `mailer_not_configured`, y los eventos del
  llamante que ya existían: `alert_email_sent|failed|network_error`,
  `email_producto_sent|failed|network_error`, `watchlist_digest_sent`. Todos
  llevan `backend` y `provider_id`. Ninguno lleva la dirección completa de una
  persona (dominio solo) ni la clave del ESP (`EMAIL_API_KEY` está en la lista
  de redacción de `observability/logging.py`).
- **En el proveedor**: tasa de rebote, quejas de spam y estado del dominio.
  Resend y Postmark los muestran por etiqueta (`watchlist-digest` ya sale
  etiquetado). Es la única fuente de esa información: el proyecto no la lee
  (§5).
- **Google Postmaster Tools**: tasa de spam por debajo del 0,3 % y reputación
  de dominio «alta». Si baja, lo primero que se revisa es la baja en un clic
  (§1) y que nadie reciba digests que no pidió.

## 5. Rebotes y quejas: hoy no se gestionan

Estado real: **ningún componente lee rebotes ni quejas.** Un hard bounce
(buzón inexistente) o una queja de spam se quedan en el dashboard del
proveedor y el sistema sigue encolando digests para esa dirección hasta que la
persona use el enlace de baja o un administrador pause sus reglas. Con SMTP de
Gmail los rebotes llegan como correo al buzón remitente y nadie los procesa.
Es tolerable hoy porque el volumen es bajo y todo destinatario es alguien que
pidió acceso o creó una regla, pero es lo que degradará la reputación del
dominio a medida que crezca la lista.

**TODO — webhook de rebotes** (no está hecho; esto es la forma que debería
tener):

1. Endpoint `POST /api/v1/webhooks/email/{proveedor}` en `api/routes/`, sin
   sesión, que verifique la firma del proveedor (Resend firma con Svix:
   `svix-id`/`svix-timestamp`/`svix-signature` y un secreto de webhook;
   Postmark ofrece usuario/contraseña HTTP básica y allowlist de IPs). El
   secreto de verificación es una variable nueva (`EMAIL_WEBHOOK_SECRET`).
2. Eventos a tratar: `email.bounced` y `email.complained` (Resend); `Bounce`
   con `Type` `HardBounce`/`SpamComplaint` y `SpamComplaint` (Postmark). Los
   rebotes blandos (`Transient`, buzón lleno) no pausan nada.
3. Acción: localizar el `user_key` por email y pausar sus reglas con
   `services/watchlist_rules.py::deactivate_all_for_user` (la misma que usa la
   baja), dejar constancia en `audit_log` y guardar la dirección en una lista
   de supresión (tabla nueva, migración Alembic) que el mailer consulte antes
   de enviar. El correo de acceso concedido y el reset de contraseña **no**
   deben respetar la supresión de quejas sin más: son correos que la persona
   acaba de pedir; sí deben respetar un hard bounce.
4. Métrica `email_bounces_total{proveedor, tipo}` y alerta si la tasa supera
   el 2 % en 24 h (umbral con el que Postmark suspende el envío).

Hasta que exista, la revisión es manual: una vez por semana, mirar rebotes y
quejas en el proveedor y pausar a mano las reglas de las direcciones afectadas
desde la consola.

## 6. Prueba de humo

En local, sin buzón:

```bash
EMAIL_BACKEND=console python -c "
from observability.mailer import Mensaje, enviar
print(enviar(Mensaje(to='prueba@example.com', subject='Humo', html='<p>hola <a href=\"https://x.example\">x</a></p>')))
"
```

Debe imprimir `ResultadoEnvio(ok=True, …, backend='console')` y dejar en el
log un evento `mailer_console` con el texto derivado del HTML
(`hola x (https://x.example)`).

Contra un ESP recién configurado, lo mismo con `EMAIL_BACKEND=resend|postmark`,
`EMAIL_FROM` y `EMAIL_API_KEY` en el entorno y un destinatario propio en Gmail;
después «Mostrar original» en Gmail y comprobar `SPF/DKIM/DMARC: PASS` y los
encabezados `List-Unsubscribe` si se pasó `unsubscribe_url`. Un `ok=False` con
`motivo='provider'` trae el mensaje del proveedor en `error`: remitente sin
verificar y clave sin permiso de envío son los dos habituales.

## 7. Referencias

- `observability/mailer.py` — el transporte y sus garantías.
- `observability/alerts.py` — contrato de fallo, log y métrica de entrega.
- `services/email_digest.py` — cuerpo del digest y token de baja firmado.
- `docs/runbooks/observability-alerts.md` — los dos planos de alertas.
- `docs/SECURITY.md` — rotación de `EMAIL_API_KEY` y `ALERT_SMTP_PASSWORD`.
- RFC 8058 (baja en un clic); requisitos de Google/Yahoo para remitentes
  (febrero 2024).
