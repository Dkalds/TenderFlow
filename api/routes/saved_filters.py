"""Rutas /api/v1/saved-filters — vistas/filtros guardados por el usuario.

Persiste snapshots con nombre de la combinación de filtros (estado ``nuqs`` del
frontend) para que el usuario pueda restaurar vistas frecuentes. Cada vista es
del ``user_id`` del principal (sesión o API key con dueño); ``db/saved_filters.py``
resuelve en la base las vistas antiguas que solo llevan la clave del correo.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from api.tenancy import require_organization, resolve_organization_ctx
from db.saved_filters import (
    delete_saved_filter,
    list_saved_filters,
    save_filter,
)
from observability.logging import get_logger
from services.organizations import claim_legacy_scope
from shared.dto import StatusOk
from shared.identity import Principal

log = get_logger(__name__)

router = APIRouter(prefix="/saved-filters", tags=["saved-filters"])

_MAX_FILTERS_JSON = 8_000


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


class SavedFiltersResult(BaseModel):
    items: list[SavedFilter]


class SavedFilterSaved(BaseModel):
    status: str
    name: str


@router.get("", summary="Listar vistas guardadas del usuario")
async def get_saved_filters(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: Principal = Depends(require_organization()),
) -> SavedFiltersResult:
    if organization_id is not None:
        await run_db(claim_legacy_scope, int(ctx["user_id"]))
    rows = await run_db(list_saved_filters, ctx["organization_id"], user_id=int(ctx["user_id"]))
    return SavedFiltersResult(items=[SavedFilter(**row) for row in rows])


@router.post("", status_code=status.HTTP_201_CREATED, summary="Guardar (o actualizar) una vista")
async def post_saved_filter(
    body: SaveFilterRequest,
    ctx: Principal = Depends(require_any_auth),
) -> SavedFilterSaved:
    # Validar que el payload sea JSON serializable (defensa frente a basura).
    try:
        json.loads(body.filters_json)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="filters_json no es JSON válido.",
        ) from exc

    ctx = await resolve_organization_ctx(ctx, body.organization_id, write=True)
    await run_db(
        save_filter,
        body.name.strip(),
        body.filters_json,
        ctx["organization_id"],
        body.visibility,
        user_id=int(ctx["user_id"]),
    )
    log.info("saved_filter_upsert", name=body.name)
    return SavedFilterSaved(status="ok", name=body.name.strip())


@router.delete("/{filter_id}", summary="Eliminar una vista guardada")
async def delete_saved_filter_route(
    filter_id: int,
    ctx: Principal = Depends(require_organization(write=True)),
) -> StatusOk:
    user_id = int(ctx["user_id"])
    # Comprobar visibilidad antes de borrar (previene IDOR — OWASP A01). No
    # basta con esto: la lista incluye las vistas *compartidas* de los demás
    # miembros, y ésas se ven pero no se borran.
    rows = await run_db(list_saved_filters, ctx["organization_id"], user_id=user_id)
    if not any(row["id"] == filter_id for row in rows):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vista no encontrada.",
        )
    # El borrado es sólo del dueño, así que su resultado manda: si no tocó
    # ninguna fila la vista era de un compañero. Devolver `ok` ahí sería
    # mentirle al cliente —la vista sigue en su sitio y la UI la haría
    # desaparecer hasta el siguiente refresco—, y confirmar un borrado que no
    # ocurrió es peor que negarlo.
    deleted = await run_db(
        delete_saved_filter,
        filter_id,
        organization_id=ctx["organization_id"],
        user_id=user_id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vista no encontrada.",
        )
    return StatusOk(status="ok")
