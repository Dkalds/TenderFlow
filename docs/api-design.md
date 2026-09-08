# Diseño de la API REST

Convenciones y contratos de la API REST de TenderFlow. Nota: los identificadores
`type` de RFC 7807 usan el namespace histórico `licitaciones-sap` (ver ejemplo
más abajo) — es un URI opaco, no una URL real, y no se ha renombrado porque
requeriría coordinar a los consumidores de la API (ver
[ADR-015](adr/ADR-015-identidad-tenderflow.md)).

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

Los scopes los resuelve `api/scopes.py::required_scope_for_request` a partir del método y la ruta; hoy son **30** familias. Esta tabla se genera con `python scripts/gen_scopes_doc.py` y CI la verifica con `--check`.

| Scope | Métodos | Familias de ruta |
|---|---|---|
| `account:delete` | DELETE | `/me` |
| `account:read` | GET | `/me/data` |
| `admin` | todos | `/admin/solicitudes-acceso`, `/admin/users`, `/empresas/reviews`, `/feature-flags`, `/security/audit`, `/security/client-error`, `/security/client-errors`, `/security/csp-report`, `/security/leaked-key`, `/webhooks`, `/webhooks/event-types`, `/webhooks/global` |
| `analytics:read` | GET | `/analytics/clusters`, `/analytics/compare-periods`, `/analytics/competitors`, `/analytics/forecast`, `/analytics/geography`, `/analytics/organos`, `/analytics/overview`, `/analytics/pipeline`, `/analytics/proyectos-modulos`, `/analytics/quality`, `/analytics/resumen`, `/analytics/scoring`, `/analytics/source-freshness`, `/analytics/tecnologias`, `/analytics/trends`, `/analytics/trends-cpv`, `/analytics/utes` |
| `api_keys:read` | GET/POST | `/me/keys` |
| `api_keys:rotate` | POST | `/me/keys` |
| `ask:read` | GET/POST | `/ask`, `/ask/models` |
| `competitive:read` | GET | `/competitive/bajas`, `/competitive/cuota`, `/competitive/empresas`, `/competitive/hhi`, `/competitive/partners`, `/competitive/renovaciones`, `/competitive/watchlist` |
| `competitive:write` | POST/DELETE | `/competitive/watchlist` |
| `data:read` | GET | `/adjudicaciones`, `/auth/me`, `/auth/oauth`, `/cuentas`, `/etiquetas`, `/eventos`, `/health`, `/health/live`, `/health/ready`, `/jobs`, `/me/notification-preferences`, `/me/sessions`, `/meta/filters`, `/meta/last-extraction`, `/predicciones/calibracion`, `/publico/hubs`, `/publico/licitaciones`, `/publico/sitemap`, `/radar/dismissals`, `/resoluciones`, `/search/global`, `/tecnologias`, `/tecnologias/impacto` |
| `data:write` | POST/PUT/DELETE | `/auth/dev-login`, `/auth/login`, `/auth/logout`, `/auth/logout-all`, `/auth/password-reset`, `/auth/register`, `/auth/totp`, `/cuentas`, `/etiquetas`, `/etiquetas/aplicar`, `/etiquetas/por-objeto`, `/etiquetas/quitar`, `/me/notification-preferences`, `/me/sessions`, `/publico/solicitudes-acceso`, `/radar/dismissals`, `/search/semantic`, `/tecnologias/keywords` |
| `empresas:read` | GET | `/empresas`, `/empresas/stats` |
| `exports:read` | GET | `/exports/calendario`, `/exports/calendario.ics`, `/exports/descargas`, `/exports/download` |
| `feature_flags:read` | GET | `/feature-flags` |
| `feedback:read` | GET | `/feedback/asistente`, `/feedback/model-info`, `/feedback/queue`, `/feedback/stats` |
| `feedback:write` | POST | `/feedback`, `/feedback/asistente` |
| `licitaciones:read` | GET/POST | `/licitaciones`, `/licitaciones/bulk-get`, `/licitaciones/cursor`, `/licitaciones/search`, `/licitaciones/stream` |
| `licitaciones:write` | POST | `/licitaciones`, `/licitaciones/comparar` |
| `models:read` | GET/POST | `/models` |
| `notifications:read` | GET | `/notifications` |
| `notifications:write` | POST | `/notifications/alerts`, `/notifications/read` |
| `profile:read` | GET | `/me/profile` |
| `profile:write` | PUT/DELETE | `/me/profile` |
| `pursuits:read` | GET | `/organizations`, `/organizations/active`, `/organizations/gonogo`, `/pursuits`, `/pursuits/actividad`, `/pursuits/agenda`, `/pursuits/attachments`, `/pursuits/baja-propia`, `/pursuits/cartera`, `/pursuits/direccion`, `/pursuits/metrics`, `/pursuits/tasks`, `/pursuits/weights-proposal` |
| `pursuits:write` | POST/PATCH/PUT/DELETE | `/organizations`, `/organizations/gonogo`, `/organizations/invitations`, `/pursuits`, `/pursuits/attachments`, `/pursuits/weights-proposal` |
| `saved_filters:read` | GET | `/saved-filters` |
| `saved_filters:write` | POST/DELETE | `/saved-filters` |
| `watchlist:read` | GET | `/watchlist/feed.xml`, `/watchlist/items`, `/watchlist/rules` |
| `watchlist:write` | POST/PUT/DELETE | `/watchlist/items`, `/watchlist/rules` |
| `*` | — | Acceso total explícito. Solo para claves de operación. |

<!-- END scopes -->

## Contrato de errores (RFC 7807)

Todas las respuestas de error usan el formato [RFC 7807 Problem Details](https://datatracker.ietf.org/doc/html/rfc7807) con `Content-Type: application/problem+json`.

```json
{
  "type": "https://licitaciones-sap/errors/not-found",
  "title": "Not Found",
  "status": 404,
  "detail": "Recurso no encontrado.",
  "instance": "/api/v1/licitaciones/xyz"
}
```

Errores de validación (422) incluyen un campo `errors` con detalle por campo:

```json
{
  "type": "https://licitaciones-sap/errors/validation-error",
  "title": "Unprocessable Entity",
  "status": 422,
  "detail": "La solicitud contiene datos inválidos.",
  "errors": [{"loc": ["body", "limit"], "msg": "...", "type": "..."}]
}
```

Constructores disponibles: `problem_400`, `problem_401`, `problem_403`, `problem_404`, `problem_409`, `problem_422`, `problem_429`, `problem_500`, `problem_503`.

## Paginación

### Offset/limit (deprecated)

```
GET /api/v1/licitaciones?offset=0&limit=50
```

Respuesta incluye header `Link` apuntando al endpoint cursor como sucesor.

### Cursor (recomendado)

```
GET /api/v1/licitaciones/cursor?limit=50
GET /api/v1/licitaciones/cursor?cursor=<opaque>&limit=50
```

El cursor es un token opaco (base64) basado en `(fecha_publicacion, id_externo)`. Más eficiente que offset: no requiere `COUNT(*)` y no se ve afectado por inserciones concurrentes.

Respuesta:

```json
{
  "data": [...],
  "total": 1234,
  "next_cursor": "eyJmZWNoYS..."
}
```

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
| `webhooks`         | `/webhooks`                 | Gestión de webhooks                              |
| `exports`          | `/exports`                  | Exportación asíncrona (jobs)                     |
| `feedback`         | `/feedback`                 | Feedback de clasificación ML                     |
| `notifications`    | `/notifications`            | Notificaciones in-app del usuario                |
| `health`           | `/health`                   | Health, liveness, readiness                      |
| `me`               | `/me`, `/me/profile`        | Perfil, API keys y export/delete GDPR del usuario autenticado |
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


## Convenciones de naming

- Sustantivos en plural para colecciones: `/licitaciones`, `/webhooks`, `/exports`.
- IDs en la ruta: `/webhooks/{webhook_id}`, `/licitaciones/{licitacion_id}`.
- Acciones como sub-recurso: `/webhooks/{webhook_id}/ping`,
  `/models/{name}/activate/{version}`.
- Verbos HTTP semánticos: GET=leer, POST=crear/acción, PATCH=actualizar, DELETE=eliminar.
