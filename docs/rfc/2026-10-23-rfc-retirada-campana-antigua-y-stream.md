---
rfc: 2026-10-23-retirada-campana-antigua-y-stream
title: Retirada de lo que la campana dejó de usar (campos de mercado de `GET /notifications`, `POST /notifications/read`), del stream SSE y de `forecast/retendering`
issue: "(sin issue: flecos de la rama claude/funcionalidades-2026-10, docs/IMPROVEMENT_BACKLOG.md)"
author: agent:claude-code
date: 2026-10-23
status: review
retirada_propuesta: 2027-02-01
---

## Contexto

El 2026-10-12 la campana pasó a enseñar **solo lo tuyo**: lo que el canal
`in_app` del outbox y los productores directos dejan en `user_notifications`
(ver el docstring de `api/routes/notifications.py`). Las novedades del mercado
se quedaron en el Resumen. Con ese cambio, tres piezas del contrato se quedaron
sin consumidor y se conservaron solo porque quitarlas es un cambio incompatible
(AGENTS.md §5):

| Operación o campo | Qué hacía | Sucesora |
|---|---|---|
| `GET /api/v1/notifications` → `items` | Novedades del mercado desde la última visita. Siempre vacío desde que se retiró `get_resumen_novedades(user_id)`, que contaba desde una columna que ninguna migración crea. | `GET /api/v1/analytics/resumen/novedades` y `GET /api/v1/analytics/resumen/desde-mi-ultima-visita` |
| `GET /api/v1/notifications` → `unread_count` | Acompañaba a `items`. Siempre 0. | — (el distintivo es `sin_leer` de `GET /notifications/alerts`) |
| `GET /api/v1/notifications` → `hoy` | Contadores del mercado. Se siguen calculando en cada petición (una consulta de `get_resumen_hoy`) aunque nadie los pinte. | `GET /api/v1/analytics/resumen/hoy` |
| `POST /api/v1/notifications/read` | Marcaba novedades del mercado como leídas en `notification_reads`. | `POST /api/v1/notifications/alerts/read` (alertas) y `POST /api/v1/analytics/resumen/desde-mi-ultima-visita/visto` (la última visita) |
| `GET /api/v1/licitaciones/stream` | SSE con las licitaciones recién ingeridas. La campana dejó de abrir el `EventSource`; `web/src/components/__tests__/notification-bell.test.tsx` fija que no lo abre. | `GET /api/v1/licitaciones/cursor` (sondeo ordenado por publicación) |

Se añade una cuarta pieza que llevaba el mismo camino sin fecha:
`GET /api/v1/analytics/forecast/retendering` está `deprecated` desde el
2026-07-20 (sin consumidor en `web/` desde el rework de Pipeline y Alertas) y su
docstring decía «hasta confirmar ausencia de consumidores externos», que sin
fecha no ocurre nunca. La sucesora es `GET /api/v1/competitive/renovaciones`,
con un dataset más rico (`riesgo_cambio` y la puntuación de oportunidad).

Comprobado el 2026-10-23 sobre `web/src` y `web/e2e`:

```sh
grep -rn '"/api/v1/notifications"\|/notifications/read"\|licitaciones/stream\|forecast/retendering' web/src web/e2e --include=*.ts --include=*.tsx | grep -v generated/
```

Solo devuelve aserciones de tests que comprueban que **no** se llama a
`/api/v1/notifications` ni se abre el `EventSource`. La campana consume
`GET /notifications/alerts` y `POST /notifications/alerts/read`
(`web/src/components/campana/avisos.ts`).

## Por qué esto necesita un RFC

AGENTS.md §5: quitar campos de una respuesta y borrar operaciones son cambios
incompatibles del contrato público, con independencia de que el frontend no los
use: puede haber integraciones por API key fuera de nuestra vista.
`scripts/check_api_breaking.py` los detecta los dos.

## Decisión propuesta

Retirada en dos tiempos, con la ventana de 90 días de `DEPRECATION_WINDOW_DAYS`
(`api/errors.py`) entre el anuncio y el borrado.

**Fase 1 — anuncio, 2026-10-23.** Entra con este RFC y no cambia ninguna
respuesta:

- `POST /notifications/read`, `GET /licitaciones/stream` y
  `GET /analytics/forecast/retendering` salen `deprecated` en el OpenAPI, con
  `[DEPRECADO 2027-02-01]` en el `summary`, y envían `Deprecation: true`,
  `Sunset: Mon, 01 Feb 2027 00:00:00 GMT` y un `Link` a su sucesora y a este
  RFC (`deprecate_route`). Las fechas se declaran con `sunset_anunciado(...,
  anunciado=date(2026, 10, 23))`, así que una fecha que no respete la ventana
  rompe el arranque y no una petición.
- Los tres campos de `GET /notifications` ya estaban marcados `deprecated` en el
  esquema; su descripción dice ahora la fecha. La operación **no** envía
  `Deprecation`/`Sunset`: esas cabeceras dicen que el recurso entero deja de
  responder (RFC 8594), y `GET /notifications` seguirá respondiendo con `alerts`
  y `alerts_unread_count`. La marca por campo viaja en el esquema, que es donde
  un cliente generado la ve.

**Fase 2 — a partir del 2027-02-01.** En una PR propia con la etiqueta
`api-breaking` que cite este RFC:

- Se quitan `items`, `unread_count` y `hoy` de `NotificationsResult`, y con ellos
  la consulta de `get_resumen_hoy` del handler y los modelos
  `NotificationItem` y `HoyCounters` si no les queda uso.
- Se borran `POST /notifications/read` y `GET /licitaciones/stream` (con
  `_SignalWatcher` y el resto de `api/routes/stream.py`, y su router en
  `api/app.py`), y `GET /analytics/forecast/retendering` con
  `get_retendering_forecast` si no le quedan llamadores.
- Las líneas correspondientes salen de `api/superficie_congelada.txt`, que solo
  encoge.

`db.notifications.mark_read`/`mark_all_read` siguen vivos tras la fase 2 si
`notification_reads` sigue guardando la última visita (`marcar_visita`); lo que
se retira es la ruta, no la tabla.

## Alternativas descartadas

- **Borrarlo ya.** El frontend no lo usa, pero el contrato es público. Es la
  misma razón por la que D19 (`2026-09-06-rfc-retirada-endpoints-analitica.md`)
  anunció antes de borrar.
- **Retirar `GET /notifications` entero.** Lo que le queda (`alerts`,
  `alerts_unread_count`) duplica la primera página de `GET /notifications/alerts`,
  y sería el paso lógico siguiente. No entra aquí porque nadie lo ha pedido y
  amplía el alcance de un cambio incompatible sin necesidad; se puede proponer
  con este mismo formato cuando se quiera.
- **Dejar el stream como canal de empuje.** Un SSE por proceso con conexiones
  de cinco minutos no sirve a un integrador externo: el canal de empuje del
  producto son los webhooks (`docs/integraciones/webhooks.md`), con firma,
  reintentos y DLQ.

## Consecuencias

- Hasta el 2027-02-01 todo responde igual que hoy; solo cambian las cabeceras y
  el OpenAPI.
- Si antes de la fecha aparece un consumidor real (los registros de acceso de la
  API key lo dirían), este RFC se revisa: la fecha es un compromiso, no un
  automatismo.
- Si el RFC se rechaza, la fase 1 se revierte quitando las tres llamadas a
  `deprecate_route` y las marcas `deprecated=True`: anunciar no rompe nada.

## Verificación

- `tests/test_deprecacion_cabeceras.py`: cada operación `deprecated` del OpenAPI
  tiene fecha de apagado, la fecha del `summary` coincide con la de `Sunset`, y
  las cabeceras llegan de verdad por HTTP (en las de analítica, también desde la
  caché de `cache_response`).
- `python scripts/check_api_surface.py` y `python scripts/check_openapi_contract.py`
  siguen verdes: la fase 1 no añade ni quita operaciones.
