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

Todas las rutas protegidas requieren el header:

```
X-API-Key: <token>
```

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

| Scope              | Rutas                        |
|--------------------|------------------------------|
| `webhooks:read`    | GET webhooks                 |
| `webhooks:write`   | POST/PATCH/DELETE webhooks   |
| `watchlist:read`   | GET watchlist feed           |
| `admin`            | POST rollback modelos, verificar auditoría |
| `*`                | Acceso total (default al crear key) |

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
| `search`           | `/search`                   | Búsqueda full-text (FTS5/tsvector) y semántica    |
| `security`         | `/security`                 | TOTP, CSRF, auditoría                            |
| `stream`           | `/stream`                   | SSE streaming genérico                           |
| `watchlist_feed`   | `/watchlist`                | Feed de watchlist                                |
| `watchlist_items`  | `/watchlist/items`          | CRUD de items de watchlist                       |
| `watchlist_rules`  | `/watchlist/rules`          | Reglas de alertas de watchlist                   |

## Convenciones de naming

- Sustantivos en plural para colecciones: `/licitaciones`, `/webhooks`, `/exports`.
- IDs en la ruta: `/webhooks/{id}`, `/exports/{job_id}`.
- Acciones como sub-recurso: `/webhooks/{id}/test`, `/models/{name}/rollback`.
- Verbos HTTP semánticos: GET=leer, POST=crear/acción, PATCH=actualizar, DELETE=eliminar.
