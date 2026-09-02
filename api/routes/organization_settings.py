"""Configuración de producto por organización (``/organizations/{id}/settings``).

Vive aparte de ``api/routes/pursuits.py`` —donde están el resto de rutas de
organizaciones— porque es la única superficie que escribe en
``organizations.settings_json`` y conviene que su contrato se lea entero en un
sitio. Hoy sólo declara ``tecnologias``: las familias del diccionario que vende
la organización y con las que el Radar acota su universo por defecto.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from services.organizations import (
    OrganizationAccessError,
    OrganizationPermissionError,
    get_settings,
    update_settings,
)
from shared.dto import OrganizationSettings, OrganizationSettingsOut

router = APIRouter(tags=["pursuits"])


@router.get(
    "/organizations/{organization_id}/settings",
    response_model=OrganizationSettingsOut,
    summary="Configuración de la organización (familias tecnológicas)",
)
async def get_organization_settings(
    organization_id: int,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> OrganizationSettingsOut:
    try:
        return await run_db(get_settings, int(ctx["user_id"]), organization_id)
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.put(
    "/organizations/{organization_id}/settings",
    response_model=OrganizationSettingsOut,
    summary="Cambiar la configuración de la organización (owner/admin)",
)
async def put_organization_settings(
    organization_id: int,
    body: OrganizationSettings,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> OrganizationSettingsOut:
    try:
        return await run_db(update_settings, int(ctx["user_id"]), organization_id, body)
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
