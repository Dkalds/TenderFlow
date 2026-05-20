"""Endpoints `/api/v1/models` para consultar el model registry (F3)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import require_api_key
from db.model_registry import activate_version, get_active, list_versions

router = APIRouter(prefix="/models", tags=["models"])


@router.get("/{name}", summary="Versión activa de un modelo")
def get_active_model(
    name: str,
    _ctx: Any = Depends(require_api_key),
) -> dict[str, Any]:
    """Devuelve los metadatos de la versión activa del modelo ``name``."""
    active = get_active(name)
    if active is None:
        raise HTTPException(status_code=404, detail=f"Modelo '{name}' sin versión activa")
    return active


@router.get("/{name}/versions", summary="Histórico de versiones de un modelo")
def list_model_versions(
    name: str,
    limit: int = Query(50, ge=1, le=500),
    _ctx: Any = Depends(require_api_key),
) -> list[dict[str, Any]]:
    """Histórico de versiones para auditoría y A/B testing."""
    return list_versions(name, limit=limit)


@router.post(
    "/{name}/activate/{version}",
    summary="Activar una versión concreta (rollback o promote)",
)
def activate_model_version(
    name: str,
    version: int,
    _ctx: Any = Depends(require_api_key),
) -> dict[str, Any]:
    """Activa la ``version`` indicada. Requiere API key con scope admin."""
    ok = activate_version(name, version)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Versión {version} no existe para '{name}'")
    return {"name": name, "version": version, "activated": True}
