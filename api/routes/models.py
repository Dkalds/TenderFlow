"""Endpoints `/api/v1/models` para consultar el model registry (F3)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.routes.dual_auth import require_admin, require_any_auth
from db.model_registry import activate_version, get_active, list_versions

router = APIRouter(prefix="/models", tags=["models"])


class ModelVersionOut(BaseModel):
    """Fila del model registry con ``metrics`` ya parseado del JSON."""

    id: int
    name: str
    version: int
    path: str | None
    sha256: str | None
    metrics: dict[str, Any]
    trained_at: str | None
    trained_on_n_samples: int | None
    trained_on_n_feedbacks: int | None
    is_active: int
    notes: str | None


class ModelActivated(BaseModel):
    name: str
    version: int
    activated: bool


@router.get("/{name}", summary="Versión activa de un modelo")
def get_active_model(
    name: str,
    _ctx: Any = Depends(require_any_auth),
) -> ModelVersionOut:
    """Devuelve los metadatos de la versión activa del modelo ``name``."""
    active = get_active(name)
    if active is None:
        raise HTTPException(status_code=404, detail=f"Modelo '{name}' sin versión activa")
    return ModelVersionOut(**active)


@router.get("/{name}/versions", summary="Histórico de versiones de un modelo")
def list_model_versions(
    name: str,
    limit: int = Query(50, ge=1, le=500),
    _ctx: Any = Depends(require_any_auth),
) -> list[ModelVersionOut]:
    """Histórico de versiones para auditoría y A/B testing."""
    # Devolvía `list[dict[str, Any]]` -> `unknown[]` en el cliente TS. Las filas
    # de `list_versions` son exactamente las de `get_active` (misma proyección de
    # `model_versions`), así que el DTO ya existía y solo faltaba declararlo.
    return [ModelVersionOut(**row) for row in list_versions(name, limit=limit)]


@router.post(
    "/{name}/activate/{version}",
    summary="Activar una versión concreta (rollback o promote)",
)
def activate_model_version(
    name: str,
    version: int,
    _ctx: Any = Depends(require_admin),
) -> ModelActivated:
    """Activa la ``version`` indicada. Requiere ser administrador.

    Antes exigía ``require_scope("admin")``, que solo entiende de API keys: un
    administrador con sesión de navegador no podía activar ni revertir un
    modelo desde ``/ops``, que es donde el producto pone ese botón. Para una
    API key no cambia nada — ``require_any_auth`` solo la marca ``is_admin``
    si su dueño lo es *y* la key lleva scope ``admin`` o ``*``.

    Invalida la caché de proceso del clasificador: sin esto, el cambio de
    ``is_active`` quedaba solo en la BD y el proceso seguía sirviendo el modelo
    anterior hasta reiniciar, así que el rollback no surtía efecto.
    """
    ok = activate_version(name, version)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Versión {version} no existe para '{name}'")

    from api.model_cache import invalidate_classifier_cache

    invalidate_classifier_cache()
    return ModelActivated(name=name, version=version, activated=True)
