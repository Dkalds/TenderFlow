"""Feed Atom/RSS de la watchlist de un usuario.

GET /api/v1/watchlist/feed.xml?token=<api_key>

Autenticación via query param ``token`` (compatible con lectores RSS que no
soportan cabeceras personalizadas). El token se valida igual que X-API-Key.
Requiere scope ``watchlist:read`` o ``*``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from api.auth import AuthContext, require_scope
from observability.logging import get_logger
from services.watchlist import generate_atom_feed

log = get_logger(__name__)

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


def _require_watchlist_read(
    _ctx: AuthContext = Depends(require_scope("watchlist:read")),
) -> AuthContext:
    return _ctx


@router.get(
    "/feed.xml",
    summary="Feed Atom con las últimas licitaciones que coinciden con tu watchlist",
    responses={
        200: {"content": {"application/atom+xml": {}}, "description": "Feed Atom 1.0"},
        401: {"description": "Token inválido o ausente"},
        403: {"description": "Scope watchlist:read requerido"},
    },
    include_in_schema=True,
)
async def watchlist_feed(
    ctx: AuthContext = Depends(_require_watchlist_read),
    limit: int = Query(default=50, ge=1, le=200, description="Máximo de entradas"),
) -> Response:
    """Devuelve un feed Atom 1.0 con las últimas licitaciones que coinciden
    con las entradas de la watchlist asociadas al API key autenticado.

    Compatible con cualquier lector RSS/Atom (Feedly, NewsBlur, etc.)
    usando la URL: ``/api/v1/watchlist/feed.xml`` con cabecera
    ``X-API-Key: <token>``.

    El ``user_key`` se deriva del ``key_hash`` de la API key autenticada,
    garantizando que cada key solo accede a su propia watchlist.
    """
    try:
        xml = generate_atom_feed(user_key=ctx.key_hash, limit=limit)
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
