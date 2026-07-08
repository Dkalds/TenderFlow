"""Rutas de predicciones ML (Fase 6, RFC 20260611-2).

- ``GET /licitaciones/{id}/prediccion-baja`` — intervalo p10/p50/p90 de la
  baja esperada, materializado por el batch nocturno. Toda predicción expone
  ``model_version`` y ``computed_at`` (trazabilidad anti-"número mágico");
  ``model_version`` NULL = baseline histórico, no modelo.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from services.ml.scoring import prediccion_baja

router = APIRouter(tags=["predicciones"])


@router.get(
    "/licitaciones/{licitacion_id:path}/prediccion-baja",
    summary="Intervalo de baja esperada (p10/p50/p90)",
    responses={404: {"description": "Sin predicción para esa licitación"}},
)
async def get_prediccion_baja(
    licitacion_id: str,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, Any]:
    data = await run_db(prediccion_baja, licitacion_id)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sin predicción para esa licitación (¿batch aún no ejecutado o ya adjudicada?).",
        )
    return data
