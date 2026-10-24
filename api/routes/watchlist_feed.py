"""Feed Atom de las alertas de un usuario.

GET /api/v1/watchlist/feed.xml?token=<api_key>

La clave viaja en ``?token=`` porque los lectores de feeds (Feedly, NewsBlur,
Thunderbird…) solo saben guardar una URL: no mandan cabeceras. ``X-API-Key``
sigue valiendo. En los dos casos la clave se valida por el mismo núcleo que el
resto de la API (``validate_api_key_credential``) y tiene que llevar el scope
``watchlist:read`` (o ``*``): la clave por defecto, ``data:read``, no abre lo
personal.

Hasta 2026-10 la ruta solo leía la cabecera aunque este docstring ya prometía
``?token=``, y buscaba las reglas bajo el ``key_hash`` de la clave cuando se
guardan bajo la identidad de su titular: el feed salía siempre vacío. La
identidad sale ahora del **titular** de la clave, igual que en
``api/routes/dual_auth.py``.

**El token no se escribe en ningún log.** El access log propio
(``api/middleware.py::_registrar_acceso``) guarda la plantilla de la ruta sin
query y Sentry la quita (``observability/sentry.py::_strip_pii``), pero la
línea de acceso de uvicorn lleva la URL entera. La redacta
``observability/logging.py::AccessLogQueryRedactor``, que ``configure_logging``
instala sobre el logger ``uvicorn.access`` para todas las rutas.
"""

from __future__ import annotations

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Security,
    status,
)
from fastapi.responses import Response
from fastapi.security import APIKeyHeader

from api.auth import AuthContext, validate_api_key_credential
from api.concurrency import run_db
from api.tenancy import resolve_organization_ctx
from db.users import get_user_by_id
from observability.logging import get_logger
from services.watchlist import generate_atom_feed
from shared.identity import user_key_from_email

log = get_logger(__name__)

router = APIRouter(prefix="/watchlist", tags=["watchlist"])

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
_SCOPE = "watchlist:read"

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="API key ausente o inválida.",
    headers={"WWW-Authenticate": "ApiKey"},
)


async def _clave_del_feed(
    request: Request,
    background_tasks: BackgroundTasks,
    api_key_raw: str | None = Security(_API_KEY_HEADER),
    token: str | None = Query(
        default=None,
        max_length=256,
        description=(
            "La API key, para lectores de feeds que no envían cabeceras. "
            "Equivale a `X-API-Key` y exige el mismo scope."
        ),
    ),
) -> AuthContext:
    """La clave de la cabecera o, si no viene, la de ``?token=``."""
    crudo = api_key_raw or token
    if not crudo:
        raise _UNAUTHORIZED
    ctx = await validate_api_key_credential(
        crudo,
        method=request.method,
        path=request.url.path,
        background_tasks=background_tasks,
    )
    # `validate_api_key_credential` ya aplica el scope que `api/scopes.py`
    # asigna a la ruta; se repite aquí para que el feed no dependa de que ese
    # mapa siga diciendo lo mismo.
    if not ctx.has_scope(_SCOPE):
        log.warning("watchlist_feed_scope_denied", key_id=ctx.key_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado. Scope watchlist:read requerido.",
        )
    return ctx


def _feed_del_titular(user_id: int, organization_id: int, limit: int) -> str:
    """Lee al titular y genera el feed en un solo salto al threadpool."""
    titular = get_user_by_id(user_id)
    if titular is None:
        raise _UNAUTHORIZED
    user_key = user_key_from_email(titular.get("email"), user_id)
    return generate_atom_feed(user_key, limit, user_id=user_id, organization_id=organization_id)


@router.get(
    "/feed.xml",
    summary="Feed Atom con las últimas licitaciones que casan tus alertas",
    # response_class=Response evita el content application/json {} por defecto:
    # este endpoint es XML y su contrato lo declara `responses` (el checker de
    # operaciones opacas solo mira application/json).
    response_class=Response,
    responses={
        200: {"content": {"application/atom+xml": {}}, "description": "Feed Atom 1.0"},
        401: {"description": "Clave inválida, ausente o sin titular"},
        403: {"description": "Scope watchlist:read requerido, o la organización no es tuya"},
    },
    include_in_schema=True,
)
async def watchlist_feed(
    ctx: AuthContext = Depends(_clave_del_feed),
    organization_id: int | None = Query(
        default=None,
        ge=1,
        description="Organización cuyas alertas se leen; por defecto la personal.",
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Máximo de entradas"),
) -> Response:
    """Feed Atom 1.0 con lo que casan las alertas activas del titular de la clave.

    Mismo resultado que ``GET /watchlist/rules/{id}/matches`` regla a regla,
    juntado y ordenado por fecha de publicación. Compatible con cualquier
    lector de feeds: basta pegar la URL con ``?token=<clave>``.
    """
    if ctx.user_id is None:
        # Solo existen en desarrollo y tests (`api/auth.py` las rechaza en prod
        # y staging): sin titular no hay alertas que leer.
        raise _UNAUTHORIZED
    # La organización la resuelve `api/tenancy.py`, como en el resto de rutas:
    # sin membresía, 403; sin parámetro, la personal del titular.
    ambito = await resolve_organization_ctx({"user_id": ctx.user_id}, organization_id)
    try:
        xml = await run_db(_feed_del_titular, ctx.user_id, int(ambito["organization_id"]), limit)
    except HTTPException:
        raise
    except Exception as exc:
        log.error("watchlist_feed_error", error=str(exc), key_id=ctx.key_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error generando el feed.",
        ) from exc

    return Response(
        content=xml,
        media_type="application/atom+xml; charset=utf-8",
        headers={"Cache-Control": "private, max-age=300"},
    )
