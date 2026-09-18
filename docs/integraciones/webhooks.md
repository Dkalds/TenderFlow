---
tags: [integraciones, webhooks, seguridad]
---

# Webhooks: formatos (JSON, Slack, Teams), firma y rotación del secret

Cada entrega de TenderFlow —evento del catálogo, `ping` de prueba o reintento—
es un `POST` con cuerpo JSON y tres cabeceras de autenticidad calculadas con
el `secret` del webhook. El `secret` se devuelve **una sola vez**: al crear el
webhook (`POST /api/v1/webhooks`) y al rotarlo
(`POST /api/v1/webhooks/{id}/rotate-secret`). No se almacena en claro y no hay
forma de volver a leerlo ([RFC 049](../rfc/049-encrypt-webhook-secrets.md)).

## Formatos del cuerpo

Cada webhook tiene un `formato` que decide **cómo** se serializa el evento
(D13 del plan v2: plantillas sobre el webhook genérico, sin integración OAuth
por plataforma). Los tres valores y las plantillas viven en
[`shared/events.py`](../../shared/events.py) (`renderizar`); la lista vigente la
sirve `GET /api/v1/webhooks/event-types` en el campo `formatos`.

| `formato` | Para qué receptor | Cuerpo |
|---|---|---|
| `json` (por defecto) | Tu propio endpoint | `{event, data, timestamp}`: el payload del evento tal cual. |
| `slack_blocks` | Webhook entrante de un canal de Slack | Mensaje de Block Kit con `text` de respaldo. |
| `teams_adaptive_card` | Webhook entrante de un canal de Teams | Mensaje con una Adaptive Card 1.5 adjunta. |

Un webhook creado sin `formato` —o uno anterior a que existiera la columna—
recibe `json`. Si el valor guardado no se reconoce, la entrega **no se pierde**:
cae también a `json`. Las firmas y cabeceras son las mismas en los tres
formatos, aunque Slack y Teams no las verifican; solo le sirven a un receptor
propio.

### Crear un webhook con cada plantilla

Desde la vista de webhooks de `/ops` (selector «formato» del alta) o por API.
El `organization_id` es opcional: sin él, el webhook es de tu organización
personal. `event_types` acepta tipos del catálogo y comodines (`*`,
`pursuit.*`, `licitacion.*`…).

```bash
# Tu endpoint: JSON crudo (el formato por defecto; el campo puede omitirse)
curl -X POST https://<api>/api/v1/webhooks \
  -H "X-API-Key: <clave con scope admin>" -H "Content-Type: application/json" \
  -d '{"name": "erp", "url": "https://erp.example.com/hooks/tenderflow",
       "event_types": ["pursuit.*"], "formato": "json"}'

# Slack: la URL es la del webhook entrante que creas en la app de Slack del canal
curl -X POST https://<api>/api/v1/webhooks \
  -H "X-API-Key: <clave con scope admin>" -H "Content-Type: application/json" \
  -d '{"name": "canal-licitaciones", "url": "https://hooks.slack.com/services/...",
       "event_types": ["pursuit.*", "adjudicacion.*"], "formato": "slack_blocks"}'

# Teams: la URL es la del webhook entrante (o flujo de Workflows) del canal
curl -X POST https://<api>/api/v1/webhooks \
  -H "X-API-Key: <clave con scope admin>" -H "Content-Type: application/json" \
  -d '{"name": "equipo-ofertas", "url": "https://<url-del-webhook-entrante-del-canal>",
       "event_types": ["pursuit.*"], "formato": "teams_adaptive_card"}'
```

El formato se cambia después con `PATCH /api/v1/webhooks/{id}` y
`{"formato": "slack_blocks"}`. Antes de activarlo, `POST
/api/v1/webhooks/{id}/ping` envía un evento `ping` **en el formato del
webhook**: es la forma de comprobar que la tarjeta llega y se pinta.

**Allowlist en producción.** En `prod` y `staging` los webhooks salientes solo
van a hosts listados en `WEBHOOK_ALLOWED_HOSTS`; sin esa variable, el alta se
rechaza. Para Slack o Teams, el host de la URL que te da la plataforma
(`hooks.slack.com` en Slack) tiene que estar en la lista.

### Ejemplos de cuerpo

Los tres son el mismo evento —`pursuit.assigned` con el payload de
`tests/test_s4_plantillas_webhook.py`— renderizado por `renderizar`. Ese test
valida las dos plantillas contra `tests/fixtures/block_kit_schema.json` y
`tests/fixtures/adaptive_cards_schema.json`.

`json`:

```json
{
  "event": "pursuit.assigned",
  "data": {
    "pursuit_id": 42,
    "licitacion_id": "PLACSP:2026/000123",
    "titulo": "Servicios de mantenimiento SAP",
    "organization_id": 7,
    "responsible_user_id": 3,
    "actor_user_id": 1
  },
  "timestamp": "2026-09-06T08:00:00+00:00"
}
```

`slack_blocks` (campos del payload en orden alfabético; `text` es lo que Slack
enseña en la notificación del móvil y en los clientes que no pintan bloques):

```json
{
  "text": "Te han asignado una oportunidad: Servicios de mantenimiento SAP",
  "blocks": [
    {
      "type": "header",
      "text": {
        "type": "plain_text",
        "text": "Te han asignado una oportunidad: Servicios de mantenimiento SAP"
      }
    },
    {
      "type": "section",
      "fields": [
        {"type": "mrkdwn", "text": "*actor_user_id*\n1"},
        {"type": "mrkdwn", "text": "*licitacion_id*\nPLACSP:2026/000123"},
        {"type": "mrkdwn", "text": "*organization_id*\n7"},
        {"type": "mrkdwn", "text": "*pursuit_id*\n42"},
        {"type": "mrkdwn", "text": "*responsible_user_id*\n3"},
        {"type": "mrkdwn", "text": "*titulo*\nServicios de mantenimiento SAP"}
      ]
    },
    {
      "type": "context",
      "elements": [
        {
          "type": "mrkdwn",
          "text": "TenderFlow · pursuit.assigned · 2026-09-06T08:00:00+00:00"
        }
      ]
    }
  ]
}
```

`teams_adaptive_card`:

```json
{
  "type": "message",
  "attachments": [
    {
      "contentType": "application/vnd.microsoft.card.adaptive",
      "contentUrl": null,
      "content": {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
          {
            "type": "TextBlock",
            "text": "Te han asignado una oportunidad: Servicios de mantenimiento SAP",
            "weight": "Bolder",
            "size": "Medium",
            "wrap": true
          },
          {
            "type": "FactSet",
            "facts": [
              {"title": "actor_user_id", "value": "1"},
              {"title": "licitacion_id", "value": "PLACSP:2026/000123"},
              {"title": "organization_id", "value": "7"},
              {"title": "pursuit_id", "value": "42"},
              {"title": "responsible_user_id", "value": "3"},
              {"title": "titulo", "value": "Servicios de mantenimiento SAP"}
            ]
          },
          {
            "type": "TextBlock",
            "text": "TenderFlow · pursuit.assigned · 2026-09-06T08:00:00+00:00",
            "isSubtle": true,
            "spacing": "Small",
            "wrap": true
          }
        ]
      }
    }
  ]
}
```

En Slack y Teams los valores del payload se aplanan a texto (listas separadas
por comas, objetos como `clave=valor`), se omiten los vacíos, se recortan a
300 caracteres y se pintan como mucho ocho. El encabezado es el título del
evento en el catálogo seguido de `titulo`, `licitacion_id`, `id_externo` o
`rule_id` del payload, el primero que exista.

## Cabeceras

| Cabecera | Contenido | Para qué |
|---|---|---|
| `X-Webhook-Signature` | `sha256=<hex>`, con `hex = HMAC-SHA256(secret, cuerpo)` | Firma **v1**, sin cambios: la que ya verifican los receptores existentes. No protege contra replay. |
| `X-Webhook-Timestamp` | Segundos Unix (entero) de la entrega original | El sello que la firma v2 liga al cuerpo. |
| `X-Webhook-Signature-V2` | `v2=<hex>`, con `hex = HMAC-SHA256(secret, "{timestamp}." + cuerpo)` | Firma **v2**: la misma clave, pero sobre el sello y el cuerpo. Verificarla más la ventana de tiempo cierra el replay. |
| `X-Webhook-Event` | Tipo de evento (`pursuit.created`, `ping`…) | Enrutar sin parsear el cuerpo. |
| `X-Webhook-Delivery` | Identificador de la entrega (solo en eventos con reintento) | Deduplicar: un reintento repite el mismo valor. |

La firma v2 se calcula sobre los **bytes crudos** del cuerpo tal como llegan,
precedidos del sello y un punto (`.`), en ASCII. No re-serialices el JSON
antes de verificar: cualquier cambio de orden de claves o de espacios daría
otra firma.

### Reintentos

Una entrega que falla se reintenta con backoff (hasta seis intentos, ver
`services/webhook_retry.py`). El reintento reenvía **el mismo cuerpo, el mismo
`X-Webhook-Delivery` y el mismo `X-Webhook-Timestamp`** que el primer intento,
así que las dos firmas son idénticas en todos los intentos. Consecuencia para
la ventana de replay: un reintento tardío (el sexto cae a unos treinta minutos
del evento) llega con un sello más viejo que la ventana de cinco minutos. Si
quieres aceptar reintentos, deduplica por `X-Webhook-Delivery` y aplica la
ventana solo a identificadores que no hayas visto; si prefieres rechazarlos,
la ventana estricta es una decisión válida — TenderFlow los reintentará hasta
agotar el cupo y desactivará el webhook.

## Verificar una entrega

1. Lee el cuerpo como bytes, sin decodificar ni parsear todavía.
2. Toma `X-Webhook-Timestamp`; rechaza si no es un entero o si
   `|ahora - timestamp| > 300` segundos.
3. Calcula `HMAC-SHA256(secret, f"{timestamp}." + cuerpo)` y compáralo con el
   hex de `X-Webhook-Signature-V2` (sin el prefijo `v2=`) con una comparación
   de tiempo constante.
4. Solo entonces parsea el JSON y procesa el evento. Responde `2xx` rápido:
   la entrega tiene un timeout de cinco segundos.

Un receptor que solo verifique `X-Webhook-Signature` (v1) sigue funcionando,
pero no está protegido contra replay: migra a la v2 cuando puedas.

### Python

```python
import hashlib
import hmac
import time

VENTANA_S = 300


def verificar(secret: str, cabeceras: dict[str, str], cuerpo: bytes) -> bool:
    """True si la entrega es auténtica y reciente. `cuerpo` son los bytes crudos."""
    try:
        timestamp = int(cabeceras["X-Webhook-Timestamp"])
    except (KeyError, ValueError):
        return False
    if abs(time.time() - timestamp) > VENTANA_S:
        return False
    esperada = hmac.new(
        secret.encode("utf-8"), f"{timestamp}.".encode("ascii") + cuerpo, hashlib.sha256
    ).hexdigest()
    recibida = cabeceras.get("X-Webhook-Signature-V2", "").removeprefix("v2=")
    return hmac.compare_digest(esperada, recibida)
```

Con FastAPI: `cuerpo = await request.body()`; con Flask: `request.get_data()`.
Las cabeceras HTTP no distinguen mayúsculas — normaliza el acceso si tu
framework no lo hace.

### Node

```js
const crypto = require("node:crypto");

const VENTANA_S = 300;

// `cuerpo` es un Buffer con los bytes crudos (express.raw({ type: "*/*" })).
function verificar(secret, cabeceras, cuerpo) {
  const timestamp = Number.parseInt(cabeceras["x-webhook-timestamp"], 10);
  if (!Number.isInteger(timestamp)) return false;
  if (Math.abs(Date.now() / 1000 - timestamp) > VENTANA_S) return false;

  const esperada = crypto
    .createHmac("sha256", secret)
    .update(`${timestamp}.`)
    .update(cuerpo)
    .digest();
  const recibida = Buffer.from(
    String(cabeceras["x-webhook-signature-v2"] || "").replace(/^v2=/, ""),
    "hex",
  );
  return recibida.length === esperada.length && crypto.timingSafeEqual(esperada, recibida);
}
```

No uses `express.json()` delante del verificador: parsea y descarta los
bytes originales. Monta `express.raw()` en la ruta del webhook y parsea el
JSON después de verificar.

## Rotar el secret

```
POST /api/v1/webhooks/{id}/rotate-secret
→ 200 {"id": 42, "secret": "<nuevo>", "rotated_at": "2026-09-14T10:00:00+00:00"}
```

Mismo alcance que `PATCH` y `DELETE`: el webhook tiene que pertenecer a la
organización activa (`?organization_id=` opcional; por defecto, la personal) y
el principal necesita permiso de escritura en ella. Con API key, el scope es
`admin`, como el resto de `/webhooks`. La rotación queda en el registro de
auditoría como `webhook.secret_rotated`.

**El secret anterior deja de valer en el mismo instante.** No hay periodo de
gracia ni doble firma: la entrega siguiente ya sale firmada con el nuevo.
Orden recomendado para no perder eventos:

1. `PATCH /api/v1/webhooks/{id}` con `{"active": false}` (opcional; las
   entregas que fallen la verificación entrarían en reintento igualmente).
2. `POST /api/v1/webhooks/{id}/rotate-secret` y carga el `secret` de la
   respuesta en el receptor.
3. `POST /api/v1/webhooks/{id}/ping` para comprobar que el receptor verifica
   con el nuevo — el ping sale con las mismas cabeceras que una entrega real.
4. `PATCH` con `{"active": true}`.

Un webhook anterior a la derivación de secretos (RFC 049, secret en claro en
la base de datos) sale de la rotación ya derivado: es la «rotación manual»
que aquel RFC dejaba pendiente.

### Cómo se guarda

La rotación no introduce columnas. La derivación original
(`HMAC(clave_maestra, "webhook-v1:{id}")`) es determinista y por eso no se
podía rotar: la rotación añade **material aleatorio por webhook**, guardado en
la misma columna `secret` dentro del sentinel (`derived:v2:<material>`), y lo
mete en el contexto de derivación (`"webhook-v2:{id}:{material}"`). El material
solo no firma nada —hace falta la clave maestra, que sigue fuera de la base de
datos—, así que la garantía de RFC 049 se conserva. Helpers en
`shared/crypto.py`; el `UPDATE` en `db/repositories/webhooks.py::rotate_secret`.
