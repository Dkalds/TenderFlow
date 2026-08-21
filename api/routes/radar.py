"""Rutas /api/v1/radar — estado de triaje del Radar, persistido por usuario.

El descarte de señales vivía en ``React.useState``: el usuario triaba las 24
señales de la bandeja, recargaba, y volvían las 24 (invariante 2 de
``docs/frontend-data-invariants.md``). Estas rutas son su respaldo server-side.

CRUD simple sobre una tabla user-scoped: llaman a ``db.*`` directamente sin
capa de servicio intermedia, según ADR-024 (una capa que no transforma nada no
se añade).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from db import radar_dismissals
from observability.logging import get_logger
from shared.cache import invalidate_user_scoped

log = get_logger(__name__)

router = APIRouter(prefix="/radar", tags=["radar"])


def _user_key(ctx: dict[str, Any]) -> str:
    """Clave opaca y estable por usuario (la adjunta ``require_any_auth``)."""
    return str(ctx["user_key"])


def _invalidar_ranking(user_key: str) -> None:
    """Tira la caché del scoring de este usuario tras cambiar sus descartes.

    El Radar pide el ranking con ``exclude_dismissed=true`` y la respuesta se
    cachea 300 s: sin invalidar, descartar una señal la dejaría en pantalla
    hasta que expirase el TTL, y el hueco no lo ocuparía la siguiente.
    """
    invalidate_user_scoped("analytics", "scoring", user_key)


class RadarDismissalBody(BaseModel):
    """Cuerpo del descarte de una señal."""

    id_externo: str = Field(max_length=120)


class RadarDismissalsResult(BaseModel):
    """``id_externo`` que el usuario tiene descartados, recientes primero."""

    ids: list[str]


@router.get("/dismissals", summary="Listar las señales descartadas por el usuario")
async def get_dismissals(
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> RadarDismissalsResult:
    ids = await run_db(radar_dismissals.list_ids, _user_key(ctx))
    return RadarDismissalsResult(ids=ids)


@router.post(
    "/dismissals",
    status_code=status.HTTP_201_CREATED,
    summary="Descartar una señal del Radar",
)
async def post_dismissal(
    body: RadarDismissalBody,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> RadarDismissalsResult:
    await run_db(radar_dismissals.add, _user_key(ctx), body.id_externo)
    log.info("radar_dismissal_created", id_externo=body.id_externo)
    _invalidar_ranking(_user_key(ctx))
    ids = await run_db(radar_dismissals.list_ids, _user_key(ctx))
    return RadarDismissalsResult(ids=ids)


@router.delete(
    # ``:path`` y no el conversor por defecto: hay ``id_externo`` de PLACSP
    # con barras (p.ej. ``PA-S 2026/000058``). Con ``[^/]+`` este DELETE no
    # casaba y devolvía 404 antes del handler, así que esas señales quedaban
    # descartadas para siempre: el POST recibe el id en el body y sí las
    # acepta, de modo que se podían descartar pero nunca deshacer.
    "/dismissals/{id_externo:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deshacer el descarte de una señal",
)
async def delete_dismissal(
    id_externo: str,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> None:
    ok = await run_db(radar_dismissals.remove, _user_key(ctx), id_externo)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La señal no estaba descartada.",
        )
    _invalidar_ranking(_user_key(ctx))
