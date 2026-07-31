"""Rutas /api/v1/watchlist/items — favoritos de licitaciones individuales.

Marcar/desmarcar una licitación concreta (``id_externo``) como favorita,
persistido server-side. Sustituye el ``localStorage`` (`detalle_watchlist`) del
frontend de detalle de licitación (RFC ux-mi-watchlist F5; ADR-014 §2: el
estado de usuario es server-side, ``localStorage`` solo caché/migración
one-shot).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from api.tenancy import require_organization, resolve_organization_ctx
from db.repositories.watchlist import WatchlistRepository
from observability.logging import get_logger
from services.organizations import claim_legacy_scope

log = get_logger(__name__)

router = APIRouter(prefix="/watchlist/items", tags=["watchlist"])

_repo = WatchlistRepository()


def _user_key(ctx: dict[str, Any]) -> str:
    """Clave opaca y estable por usuario.

    ``require_any_auth`` (sesión o API key) siempre adjunta ``user_key`` al
    contexto vía ``shared.identity.user_key_from_email`` — es la única
    derivación canónica. Antes esta función tenía un fallback local con una
    fórmula distinta (sin ``.strip().lower()``, usando ``key_hash`` en vez de
    ``user_id`` como semilla alternativa) que nunca se ejercitaba en la
    práctica pero podía divergir silenciosamente si algún día lo hiciera.
    """
    return str(ctx["user_key"])


def _user_id(ctx: dict[str, Any]) -> int | None:
    """Devuelve el propietario humano, también para API keys vinculadas."""
    raw = ctx.get("user_id")
    return int(raw) if raw is not None else None


class WatchlistItemBody(BaseModel):
    """Cuerpo de creación de un favorito."""

    id_externo: str = Field(max_length=120)
    organization_id: int | None = Field(default=None, ge=1)
    visibility: str = Field(default="private", pattern="^(private|organization)$")


@router.get("", summary="Listar favoritos del usuario (enriquecidos)")
async def get_items(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_organization()),
) -> dict[str, list[dict[str, Any]]]:
    if organization_id is not None:
        await run_db(claim_legacy_scope, int(ctx["user_id"]), _user_key(ctx))
    items = await run_db(
        _repo.list_items,
        _user_key(ctx),
        ctx["organization_id"],
        _user_id(ctx),
    )
    return {"items": items}


@router.post("", status_code=status.HTTP_201_CREATED, summary="Añadir un favorito")
async def post_item(
    body: WatchlistItemBody,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, Any]:
    ctx = await resolve_organization_ctx(ctx, body.organization_id, write=True)
    item = await run_db(
        _repo.add_item,
        _user_key(ctx),
        _user_id(ctx),
        body.id_externo,
        ctx["organization_id"],
        body.visibility,
    )
    log.info("watchlist_item_created", id_externo=body.id_externo)
    return item


@router.delete(
    "/{id_externo}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar un favorito propio",
)
async def delete_item(
    id_externo: str,
    ctx: dict[str, Any] = Depends(require_organization(write=True)),
) -> None:
    ok = await run_db(_repo.remove_item, _user_key(ctx), id_externo, ctx["organization_id"])
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Favorito no encontrado.")
