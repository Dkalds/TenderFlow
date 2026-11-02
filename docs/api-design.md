# Diseño de la API REST

Convenciones y contratos de la API REST de TenderFlow. Nota: los identificadores
`type` de RFC 7807 usan el namespace histórico `licitaciones-sap` (ver ejemplo
más abajo) — es un URI opaco, no una URL real, y no se ha renombrado porque
requeriría coordinar a los consumidores de la API (ver
[ADR-015](adr/ADR-015-identidad-tenderflow.md)).

## Qué parte de esta API es un contrato

`api/openapi.json` lleva las más de doscientas operaciones que la aplicación
expone, y la mayoría son internas: alimentan una pestaña de la consola, la
administración o el registro de modelos. Enseñarle ese fichero entero a un
integrador tiene dos efectos, los dos malos: cada endpoint se convierte en una
promesa que no se puede romper, y el cliente no sabe cuál usar.

La lista de lo que **sí** es contrato, con el motivo de cada línea, está en
[`api/contrato_publico.py`](../api/contrato_publico.py). Con ella,
`make openapi` produce dos ficheros:

| Fichero | Qué lleva | Para quién |
|---|---|---|
| `api/openapi.json` | todo, con `x-public: true` en las operaciones con contrato | el codegen del frontend, y quien necesite ver la superficie completa |
| `api/openapi-public.json` | sólo esas operaciones y los esquemas que alcanzan | **el que se publica** a integradores |

Añadir una operación al contrato es una línea. **Quitarla no**: retirar algo de
ahí rompe a quien lo use, y va por RFC con fecha —
`tests/test_contrato_publico.py` falla en las dos direcciones para que el
cambio sea visible en el diff y no un descuido.

## Base URL

```
/api/v1/
```

Arrancá el servidor con `make api` (uvicorn en `:8080` con reload).

## Autenticación

Las rutas protegidas declaran su mecanismo en OpenAPI. La mayoría acepta una
sesión web o el header:

```
X-API-Key: <token>
```

Las claves son credenciales de máquina ligadas a un usuario y deben tener el
scope que corresponde al método y a la ruta. Las operaciones sensibles de
cuenta exigen una sesión reciente; los feeds para clientes externos pueden ser
solo API key. Las rutas anónimas viven bajo `/publico`, `/health` y `/auth`.

### Scopes

Las API keys tienen scopes separados por coma (o `*` para acceso total). Se validan con `require_scope()`:

```python
from api.auth import require_api_key, require_scope

# Solo requiere key válida (cualquier scope)
@router.get("/datos")
async def datos(ctx: AuthContext = Depends(require_api_key)): ...

# Requiere scope específico
@router.delete("/webhooks/{id}")
async def delete(ctx: AuthContext = Depends(require_scope("webhooks:write"))): ...
```

Scopes usados en el proyecto:

<!-- BEGIN scopes (generado por scripts/gen_scopes_doc.py — no editar a mano) -->

Los scopes los resuelve `api/scopes.py::required_scope_for_request` a partir del método y la ruta; hoy son **32** familias. Esta tabla se genera con `python scripts/gen_scopes_doc.py` y CI la verifica con `--check`.

| Scope | Métodos | Familias de ruta |
|---|---|---|
| `account:delete` | DELETE | `/me` |
| `account:read` | GET | `/me/data` |
| `admin` | todos | `/admin/api-keys`, `/admin/dlq`, `/admin/ejecuciones`, `/admin/revision`, `/admin/solicitudes-acceso`, `/admin/users`, `/empresas/reviews`, `/feature-flags`, `/security/audit`, `/security/client-error`, `/security/client-errors`, `/security/csp-report`, `/security/leaked-key`, `/webhooks`, `/webhooks/event-types`, `/webhooks/global` |
| `analytics:read` | GET/POST | `/analytics/calendario`, `/analytics/clusters`, `/analytics/compare-periods`, `/analytics/competitors`, `/analytics/forecast`, `/analytics/geography`, `/analytics/organos`, `/analytics/overview`, `/analytics/pipeline`, `/analytics/proyectos-modulos`, `/analytics/quality`, `/analytics/resumen`, `/analytics/scoring`, `/analytics/source-freshness`, `/analytics/tecnologias`, `/analytics/trends`, `/analytics/trends-cpv`, `/analytics/utes` |
| `api_keys:read` | GET/POST/DELETE | `/me/keys` |
| `api_keys:rotate` | POST | `/me/keys` |
| `ask:read` | GET/POST | `/ask`, `/ask/models` |
| `audit:read` | GET | `/organizations` |
| `competitive:read` | GET | `/competitive/bajas`, `/competitive/cuota`, `/competitive/empresas`, `/competitive/hhi`, `/competitive/partners`, `/competitive/renovaciones`, `/competitive/watchlist` |
| `competitive:write` | POST/DELETE | `/competitive/watchlist` |
| `data:read` | GET | `/adjudicaciones`, `/auth/me`, `/auth/oauth`, `/eventos`, `/health`, `/health/live`, `/health/ready`, `/jobs`, `/me/notification-preferences`, `/me/sessions`, `/meta/filters`, `/meta/last-extraction`, `/predicciones/calibracion`, `/publico/cobertura`, `/publico/hubs`, `/publico/licitaciones`, `/publico/sitemap`, `/radar/dismissals`, `/radar/proximas`, `/resoluciones`, `/search/global`, `/tecnologias/keywords` |
| `data:write` | POST/PUT/DELETE | `/auth/dev-login`, `/auth/login`, `/auth/logout`, `/auth/logout-all`, `/auth/password`, `/auth/password-reset`, `/auth/register`, `/auth/totp`, `/auth/verify-email`, `/me/notification-preferences`, `/me/sessions`, `/publico/solicitudes-acceso`, `/radar/dismissals`, `/search/semantic`, `/tecnologias/keywords` |
| `empresas:read` | GET | `/empresas`, `/empresas/stats` |
| `exports:read` | GET | `/exports/calendario`, `/exports/calendario.ics`, `/exports/crm`, `/exports/descargas`, `/exports/download` |
| `feature_flags:read` | GET | `/feature-flags` |
| `feedback:read` | GET | `/feedback/asistente`, `/feedback/model-info`, `/feedback/queue`, `/feedback/stats`, `/feedback/taxonomia` |
| `feedback:write` | POST | `/feedback`, `/feedback/asistente` |
| `licitaciones:read` | GET/POST | `/licitaciones`, `/licitaciones/bulk-get`, `/licitaciones/cursor`, `/licitaciones/search`, `/licitaciones/stream` |
| `licitaciones:write` | POST | `/licitaciones`, `/licitaciones/comparar` |
| `models:read` | GET/POST | `/models` |
| `notifications:read` | GET | `/notifications`, `/notifications/alerts`, `/notifications/baja` |
| `notifications:write` | POST | `/notifications/alerts`, `/notifications/baja`, `/notifications/read` |
| `organizations:manage` | POST/PUT/DELETE | `/organizations`, `/organizations/invitations` |
| `profile:read` | GET | `/me/profile` |
| `profile:write` | POST/PUT/DELETE | `/me/profile` |
| `pursuits:read` | GET | `/cuentas`, `/cuentas/buscar-organos`, `/cuentas/resumen`, `/etiquetas`, `/organizations`, `/organizations/active`, `/organizations/go-no-go`, `/pursuits`, `/pursuits/actividad`, `/pursuits/adjuntos`, `/pursuits/agenda`, `/pursuits/cartera`, `/pursuits/direccion`, `/pursuits/metrics`, `/pursuits/mi-baja`, `/pursuits/tasks`, `/pursuits/weights-proposal` |
| `pursuits:write` | POST/PATCH/PUT/DELETE | `/cuentas`, `/cuentas/por-organo`, `/etiquetas`, `/etiquetas/aplicar`, `/etiquetas/por-objeto`, `/etiquetas/quitar`, `/organizations/go-no-go`, `/pursuits`, `/pursuits/adjuntos`, `/pursuits/cartera`, `/pursuits/weights-proposal` |
| `saved_filters:read` | GET | `/saved-filters` |
| `saved_filters:write` | POST/DELETE | `/saved-filters` |
| `watchlist:read` | GET | `/follows`, `/watchlist/feed.xml`, `/watchlist/items`, `/watchlist/rules` |
| `watchlist:write` | POST/PUT/DELETE | `/follows`, `/watchlist/items`, `/watchlist/rules` |
| `*` | — | Acceso total explícito. Solo para claves de operación. |

<!-- END scopes -->

## Convención de la API

Fijada el 2026-10-25, antes de que más consumidores externos (claves de CU-14,
el SDK de `release-sdk.yml`) dependan de la forma de hoy. Rige para **toda
operación nueva**; lo heredado que no cumple está congelado, con su motivo, en
`scripts/check_api_convencion.py` (`make check-api-convencion`, y dentro de la
suite por `tests/test_unit_ratchet_api_convencion.py`). Esas listas solo
encogen: una ruta nueva se ajusta a la convención, no se añade a la lista.

| Tema | Regla | Dónde vive |
|---|---|---|
| Idioma de paths y campos | Español en lo nuevo (`/licitaciones`, `fecha_limite`) | revisión |
| Idioma de mensajes | `detail` en español, para la persona; `title`, frase HTTP estándar | `api/errors.py` |
| Error | Uno solo: `ProblemDetail`, RFC 9457, `application/problem+json` | `shared/dto/errores.py` |
| Paginación | Una sola: `limit`/`offset` y `Pagina[T]` | `shared/dto/paginacion.py`, `api/pagination.py` |

### Idioma

Lo nuevo —paths, parámetros y campos— va en español, que es el idioma del
dominio y el de la mayoría de la superficie (`/licitaciones`, `/adjudicaciones`,
`/cuentas`, `/etiquetas`, `/resoluciones`, `/publico`). Lo que ya existe en
inglés (`/pursuits`, `/organizations`, `/follows`, `/saved-filters`,
`/feature-flags`) **no se renombra en la versión 1 de la API**: renombrar es quitar una ruta,
que es incompatible y va por RFC con alias y `Sunset` (política de
deprecación, abajo). Las claves de los dos sobres comunes (`items`, `total`,
`limit`, `offset`; `type`, `title`, `status`, `detail`) se quedan como están: son
el contrato que el cliente generado ya parsea, y la RFC 9457 fija las del error.

Los mensajes para personas (`detail`) van en español. El `type` del error es un
URI opaco y estable por condición —es lo que un cliente compara, nunca el
texto— y conserva el namespace histórico `licitaciones-sap` (ver la nota del
principio y [ADR-015](adr/ADR-015-identidad-tenderflow.md)).

### Errores: RFC 9457 `application/problem+json`

Toda respuesta de error tiene esta forma (RFC 9457 sustituye a la 7807 sin
cambiar el formato):

```json
{
  "type": "https://licitaciones-sap/errors/not-found",
  "title": "Not Found",
  "status": 404,
  "detail": "No encontrada.",
  "instance": "/api/v1/publico/licitaciones/xyz"
}
```

El 422 añade `errors`, un elemento por campo (`ErrorDeValidacion`: `loc`,
`msg`, `type`):

```json
{
  "type": "https://licitaciones-sap/errors/validation-error",
  "title": "Unprocessable Entity",
  "status": 422,
  "detail": "La solicitud contiene datos inválidos.",
  "errors": [{"loc": ["query", "limit"], "msg": "...", "type": "less_than_equal"}]
}
```

- **El tipo** es `ProblemDetail` (alias `Error`) en `shared/dto/errores.py`.
- **Un solo manejador**: `api/errors.py::register_exception_handlers`. Una ruta
  lanza `HTTPException(status_code=..., detail="motivo en español")` (o una
  subclase con `tipo` propio, como `ReautenticacionRequerida`) y el manejador
  la convierte; no construye una `JSONResponse` de error a mano. Los cuerpos
  crudos del middleware ASGI (413, NUL, 429) emiten la misma forma.
- **El esquema lo declara**: `api/errors.py::documentar_errores` —enganchado a
  `app.openapi()`— pone `ProblemDetail` en `application/problem+json` en el 422,
  en todo 4xx/5xx que una ruta declare solo con `description`, y como `default`
  de cada operación. Hasta esta fecha el cliente generado solo conocía el 422
  que inventa FastAPI (`HTTPValidationError`, `{"detail": [...]}`), una forma
  que la API nunca emitía.
- **Tipos con significado propio** para el cliente: `query-timeout` (503, no
  reintentar) y `reauthentication-required` (403 que se arregla volviendo a
  entrar). Constructores: `problem_400` … `problem_503`.

### Paginación: `limit`/`offset` y `Pagina[T]`

```
GET /api/v1/adjudicaciones?limit=50&offset=100
```

```json
{"items": [...], "total": 1234, "limit": 50, "offset": 100}
```

- Los parámetros salen de `Depends(api.pagination.pagina(default_limit))`, con
  `MAX_PAGE_LIMIT` como tope único; la respuesta es `Pagina[T]`
  (`shared/dto/paginacion.py`). `Pagina` es un alias de `PaginatedResponse`: el
  componente OpenAPI sigue siendo `PaginatedResponse_<T>_`, así que adoptarla no
  cambia nada para el cliente.
- `total` vale `-1` cuando la ruta admite `with_total=false` y no se pidió.

**Por qué offset y no cursor.** Es lo que domina: de las 13 operaciones que
paginaban el 2026-10-25, 11 lo hacen por offset y 2 por cursor, y todas las
listas del contrato público salvo una (`/adjudicaciones`, `/empresas`,
`/licitaciones/search`, `/publico/licitaciones`) ya son offset. Además es la que
un integrador entiende sin documentación, permite saltar a una página y dar
«de N». El coste conocido del offset —un `OFFSET` profundo sobre una tabla de
cientos de miles de filas— solo se paga en el volcado del corpus entero, y para
ese caso existe ya `GET /licitaciones/cursor`.

**El cursor queda congelado donde está**: `GET /licitaciones/cursor` (la
sucesora del listado por offset del corpus, decidida en la
[RFC 2026-09-06](rfc/2026-09-06-rfc-retirada-endpoints-analitica.md), que sigue
vigente con su `Sunset`) y `GET /organizations/{id}/audit` (log append-only).
Una ruta nueva no pagina por cursor; si un listado nuevo crece sin techo y se
vuelca entero, eso se decide en una RFC, no en la PR.

```
GET /api/v1/licitaciones/cursor?limit=50
GET /api/v1/licitaciones/cursor?cursor=<opaque>&limit=50
```

El cursor es un token opaco (base64) sobre `(fecha_publicacion, id_externo)`;
la respuesta es `{items, next_cursor, has_more, limit}` más `total` si se pide
`with_total=true`.

### Rutas fuera de la convención (congeladas)

Están en `scripts/check_api_convencion.py` con su motivo. Migrarlas cambia el
nombre del componente o la forma de la respuesta que el frontend consume
(`web/src/lib/api-types.ts`), así que cada una pide RFC (AGENTS.md §5):

| Operación | Qué incumple |
|---|---|
| `GET /licitaciones/cursor`, `GET /organizations/{id}/audit` | cursor (ver arriba) |
| `GET /empresas`, `GET /pursuits`, `GET /pursuits/{id}/comments`, `GET /radar/proximas`, `GET /notifications/alerts`, `GET /competitive/empresas/{id}/adjudicaciones` | offset con sobre propio (`EmpresasListResult`, `PursuitListResponse`…) en vez de `Pagina[T]` |
| `GET /competitive/renovaciones` | `offset` sin `total` ni `offset` en el sobre |
| `GET /publico/sitemap/entradas` | lista desnuda con offset (la trocea el sitemap del sitio) |
| `GET /health/ready` | su 503 lleva el `HealthResponse` completo para el balanceador |

## Rutas disponibles

| Módulo             | Prefijo                    | Descripción                                    |
|--------------------|-----------------------------|-------------------------------------------------|
| `licitaciones`     | `/licitaciones`             | CRUD, búsqueda y cursor de licitaciones          |
| `ask`              | `/ask`                      | Asistente RAG — pregunta en NL, resumen, modelos disponibles (SSE) |
| `analytics`        | `/analytics`                | KPIs, pipeline, tendencias, scoring, forecast    |
| `competitive`      | `/competitive`              | Bajas anómalas, cuota de mercado, renovaciones   |
| `empresas`         | `/empresas`                 | Perfil y ficha de empresas licitadoras           |
| `eventos`          | `/licitaciones/{id}/eventos`, `/eventos` | Eventos/hitos de contratos              |
| `predicciones`     | `/licitaciones/{id}/prediccion-baja`, `/predicciones/calibracion` | Predicción de baja anómala y calibración |
| `resoluciones`     | `/resoluciones`             | Resoluciones de recursos contractuales (TACRC)   |
| `auth`             | `/auth`                     | Login password/OAuth, sesión, logout             |
| `admin_users`      | `/admin/users`              | Administración de usuarios (scope `admin`)       |
| `feature_flags`    | `/feature-flags`            | Feature flags                                    |
| `saved_filters`    | `/saved-filters`            | Filtros de búsqueda guardados                    |
| `webhooks`         | `/webhooks`                 | Gestión de webhooks; firma de entregas y rotación del secret en [integraciones/webhooks.md](integraciones/webhooks.md) |
| `exports`          | `/exports`                  | Exportación asíncrona (jobs)                     |
| `feedback`         | `/feedback`                 | Feedback de clasificación ML                     |
| `notifications`    | `/notifications`            | Notificaciones in-app del usuario                |
| `health`           | `/health`                   | Health, liveness, readiness                      |
| `me`               | `/me`, `/me/profile`        | Perfil, API keys y export/delete GDPR del usuario autenticado |
| `organization_audit` | `/organizations/{id}/audit` | Rastro de auditoría de la organización, JSON o CSV (owner/admin; scope `audit:read`) |
| `meta`             | `/meta`                     | Metadata del sistema (opciones de filtros)       |
| `models`           | `/models`                   | Versiones de modelos ML, rollback (`admin`)      |
| `search`           | `/search`                   | Búsqueda full-text (`tsvector` + GIN) y semántica    |
| `security`         | `/security`                 | TOTP, CSRF, auditoría                            |
| `stream`           | `/licitaciones/stream`      | SSE de licitaciones nuevas (no existe un prefijo /stream propio)  |
| `watchlist_feed`   | `/watchlist`                | Feed de watchlist                                |
| `watchlist_items`  | `/watchlist/items`          | CRUD de items de watchlist                       |
| `watchlist_rules`  | `/watchlist/rules`          | Reglas de alertas de watchlist                   |

## Política de deprecación

Una ruta no se apaga: se deprecia, se anuncia y **después** se apaga. Hasta
2026-09 el listado por offset emitía `Deprecation: true` sin decir para cuándo,
que le pide al cliente que se prepare sin darle fecha.

### La ventana es de 90 días

`api/errors.py::DEPRECATION_WINDOW_DAYS`. Es la ventana del **contrato**, no la
del calendario de quien deprecia: `deprecate_route()` lanza `ValueError` si la
fecha de apagado cae más cerca. Un aviso más corto convierte el problema de
quien deprecia en un incidente de quien consume.

### Las tres cabeceras

`deprecate_route(response, sunset=..., successor=..., rfc=...)` escribe:

| Cabecera | Valor | Qué dice |
|---|---|---|
| `Deprecation` | `true` (RFC 8594) | La ruta está deprecada. |
| `Sunset` | fecha HTTP (RFC 8594) | **Cuándo** deja de responder. |
| `Link` | `rel="successor-version"` y `rel="deprecation"` | Qué usar en su lugar, y la RFC de retirada. |

`Sunset` va en formato de fecha HTTP (IMF-fixdate), no ISO-8601: lo exige
RFC 8594 y un cliente que parsee la cabecera espera ese formato.

### Qué exige retirar una ruta

1. **RFC de retirada** con fecha, enlazada desde la cabecera `Link`.
2. `deprecate_route()` en la operación, con `sunset` ≥ hoy + 90 días.
3. La sucesora existiendo y sirviendo el mismo dato **antes** del anuncio.
4. La etiqueta `api-breaking` en la PR que finalmente la borre, con la RFC
   enlazada — lo verifica el job `api-breaking-check`
   (`scripts/check_api_breaking.py`).

### Qué cuenta como cambio incompatible

No solo borrar una ruta. `scripts/check_api_breaking.py` compara el OpenAPI de
`master` con el de la PR y considera incompatible:

- Quitar una ruta o un método.
- Quitar un campo de una respuesta, o cambiarle el tipo.
- Añadir un campo **requerido** a una petición, o hacer requerido uno que no lo era.
- Quitar un parámetro, o estrechar su rango (`le`, `ge`, `maxLength`, `enum`).
- Quitar un código de estado documentado.

Añadir un campo opcional a una respuesta, una ruta nueva o un parámetro
opcional **no** es incompatible: un cliente que los ignora sigue funcionando.

### Rutas deprecadas hoy

| Ruta | Sunset | Sucesora |
|---|---|---|
| `GET /licitaciones` (paginación por offset) | 2027-01-15 | `GET /licitaciones/cursor` |
| `GET /analytics/compare-periods`, `GET /analytics/resumen/sankey`, `GET /analytics/resumen/top` | 2027-01-15 | — (sin consumidor; [RFC D19](rfc/2026-09-06-rfc-retirada-endpoints-analitica.md)) |
| `GET /analytics/forecast/retendering` | 2027-02-01 | `GET /competitive/renovaciones` |
| `POST /notifications/read` | 2027-02-01 | `POST /notifications/alerts/read` |
| `GET /licitaciones/stream` | 2027-02-01 | `GET /licitaciones/cursor` |
| Campos `items`, `unread_count` y `hoy` de `GET /notifications` (la operación sigue) | 2027-02-01 | `GET /notifications/alerts`, `GET /analytics/resumen/hoy` |
| Un `id_externo` anterior a una re-key (los ids PLACSP sin prefijo, `2026/LIC/0049`, desde `v164`) en toda ruta bajo `/licitaciones/{id_externo}` y `/licitaciones/{licitacion_id}`, en `DELETE /radar/dismissals/{id_externo}`, `DELETE /watchlist/items/{id_externo}`, `PUT /watchlist/items/{id_externo}/nota`, `POST /admin/revision/duplicados/{id_externo}/resolver` y en los cuerpos que lo traen (`POST /pursuits`, `POST /pursuits/cartera/{cartera_id}/renovacion`, `POST /follows` de una licitación, `POST /radar/dismissals`, `POST /watchlist/items`, `POST /feedback`, `POST /feedback/asistente`, `POST /ask`) (resuelto por `licitaciones_id_anterior` en `api/identidad.py`; la operación sigue y guarda el id vigente) | 2027-04-30 | El `id_externo` vigente, que va en `Link rel="successor-version"` ([RFC identidad PLACSP](rfc/2026-10-24-rfc-identidad-placsp-organo-expediente.md)) |

Las cuatro últimas filas las propone
[2026-10-23-rfc-retirada-campana-antigua-y-stream](rfc/2026-10-23-rfc-retirada-campana-antigua-y-stream.md).
`tests/test_deprecacion_cabeceras.py` fija que toda operación `deprecated` del
OpenAPI tiene fecha de apagado declarada y la envía en `Sunset`.


## Convenciones de naming

- Sustantivos en plural para colecciones: `/licitaciones`, `/webhooks`, `/exports`.
- IDs en la ruta: `/webhooks/{webhook_id}`, `/licitaciones/{id_externo}`.
- Acciones como sub-recurso: `/webhooks/{webhook_id}/ping`,
  `/models/{name}/activate/{version}`.
- Verbos HTTP semánticos: GET=leer, POST=crear/acción, PATCH=actualizar, DELETE=eliminar.

### Un expediente se nombra `{id_externo:path}`, siempre

Los `id_externo` de PLACSP llevan **barras y espacios** (`PA-S 2026/000058`).
El servidor ASGI decodifica el `%2F` antes del enrutado, así que el conversor
por defecto de Starlette (`[^/]+`) no ve el identificador entero y la ruta
devuelve un 404 que no depende de los datos sino de cómo se declaró.

Por eso toda ruta que direccione un expediente —esté en el paquete
`api/routes/licitaciones/` o en `eventos.py`, `predicciones.py` o `ask.py`—
declara `{id_externo:path}`, con ese nombre. Lo comprueba
`tests/test_licitaciones_identificador.py`, que falla ante cualquier variante.

El campo `licitacion_id` sigue existiendo en **cuerpos** de respuesta
(`TimelineResult`, `SimilaresResult`): lo que se unificó es cómo se direcciona
el expediente, no cómo se llama dentro del JSON.

**El detalle es glotón.** `GET /licitaciones/{id_externo:path}` casa también
con todo lo que cuelga de él —`/licitaciones/{id_externo}/eventos` y el resto—,
y Starlette se queda con la primera ruta que case. Vive por eso en su propio `router_detalle` que `api/app.py` incluye el
último de todos. Si añadís un router que cuelgue de `/licitaciones/{...}`,
inclúyelo **antes** de esa línea.

### Los routers grandes se parten por familias

`api/routes/licitaciones/` es un paquete, no un módulo: `listado`, `ficha`,
`documentos`, `pliegos`, `analitica` y `adjudicaciones`, más `_base` (lo que
comparten) y `modelos` (los DTO que usa más de una). El criterio para partir no
es el número de líneas: es que el orden de declaración dentro del fichero
decidiera el comportamiento sin que se viera. El orden de inclusión está
escrito en el `__init__.py` del paquete y hay un test que comprueba que ninguna
familia se queda fuera.
