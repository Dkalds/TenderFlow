"""Rutas /api/v1/saved-filters — vistas/filtros guardados por el usuario.

Persiste snapshots con nombre de la combinación de filtros (estado ``nuqs`` del
frontend) para que el usuario pueda restaurar vistas frecuentes. Cada vista se
asocia a una clave opaca y estable derivada de la sesión o API key.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from db.saved_filters import (
    delete_saved_filter,
    list_saved_filters,
    save_filter,
)
from observability.logging import get_logger
from services.organizations import (
    OrganizationAccessError,
    OrganizationPermissionError,
    claim_legacy_scope,
    resolve_organization,
)

log = get_logger(__name__)

router = APIRouter(prefix="/saved-filters", tags=["saved-filters"])

_MAX_FILTERS_JSON = 8_000


def _user_key(ctx: dict[str, Any]) -> str:
    """Clave opaca y estable por usuario (email de sesión o hash de API key)."""
    if ctx.get("user_key"):
        return str(ctx["user_key"])
    seed = str(ctx.get("email") or ctx.get("key_hash") or "anon")
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


class SavedFilter(BaseModel):
    """Vista guardada tal como se devuelve al cliente."""

    id: int
    name: str
    filters_json: str
    created_at: str
    organization_id: int | None = None
    visibility: str = "private"


class SaveFilterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    filters_json: str = Field(..., max_length=_MAX_FILTERS_JSON)
    organization_id: int | None = Field(default=None, ge=1)
    visibility: str = Field(default="private", pattern="^(private|organization)$")


@router.get("", summary="Listar vistas guardadas del usuario")
async def get_saved_filters(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, list[SavedFilter]]:
    resolved_id: int | None = None
    if organization_id is not None:
        try:
            resolved_id, _ = await run_db(
                resolve_organization, int(ctx["user_id"]), organization_id
            )
            await run_db(claim_legacy_scope, int(ctx["user_id"]), _user_key(ctx))
        except OrganizationAccessError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    rows = await run_db(list_saved_filters, _user_key(ctx), resolved_id)
    items = [SavedFilter(**row) for row in rows]
    return {"items": items}


@router.post("", status_code=status.HTTP_201_CREATED, summary="Guardar (o actualizar) una vista")
async def post_saved_filter(
    body: SaveFilterRequest,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, str]:
    # Validar que el payload sea JSON serializable (defensa frente a basura).
    try:
        json.loads(body.filters_json)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="filters_json no es JSON válido.",
        ) from exc

    resolved_id: int | None = None
    if body.organization_id is not None:
        try:
            resolved_id, _ = await run_db(
                resolve_organization,
                int(ctx["user_id"]),
                body.organization_id,
                write=True,
            )
        except (OrganizationAccessError, OrganizationPermissionError) as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    await run_db(
        save_filter,
        _user_key(ctx),
        body.name.strip(),
        body.filters_json,
        resolved_id,
        body.visibility,
    )
    log.info("saved_filter_upsert", name=body.name)
    return {"status": "ok", "name": body.name.strip()}


@router.delete("/{filter_id}", summary="Eliminar una vista guardada")
async def delete_saved_filter_route(
    filter_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, str]:
    user_key = _user_key(ctx)
    resolved_id: int | None = None
    if organization_id is not None:
        try:
            resolved_id, _ = await run_db(
                resolve_organization,
                int(ctx["user_id"]),
                organization_id,
                write=True,
            )
        except (OrganizationAccessError, OrganizationPermissionError) as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    # Comprobar propiedad antes de borrar (previene IDOR — OWASP A01).
    rows = await run_db(list_saved_filters, user_key, resolved_id)
    if not any(row["id"] == filter_id for row in rows):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vista no encontrada.",
        )
    await run_db(
        delete_saved_filter,
        filter_id,
        user_key=user_key,
        organization_id=resolved_id,
    )
    return {"status": "ok"}
