"""Rutas de predicciones ML (Fase 6, RFC 20260611-2).

- ``GET /licitaciones/{id}/prediccion-baja`` — intervalo p10/p50/p90 de la
  baja esperada, materializado por el batch nocturno. Toda predicción expone
  ``model_version`` y ``computed_at`` (trazabilidad anti-"número mágico");
  ``model_version`` NULL = baseline histórico, no modelo. Si la licitación
  ya está adjudicada, además incluye ``baja_real``/``importe_adjudicado``
  para comparar la estimación (si la hubo) contra el resultado real.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from services.ml.calibration import CalibracionBajaDTO, calibracion_baja_dto
from services.ml.pricing_scenarios import PriceScenariosResult, get_price_scenarios
from services.ml.scoring import prediccion_baja
from shared.cache import cache_response

router = APIRouter(tags=["predicciones"])

# 15 min: la calibración depende de predicciones_baja + adjudicaciones, que
# solo cambian con el batch nocturno de scoring — no hace falta recomputar
# la agregación en cada request de la página calidad-datos.
_CALIBRACION_CACHE_TTL_S = 900


class PrediccionBajaResult(BaseModel):
    """Predicción materializada y/o baja real de una licitación.

    Los bloques son condicionales por diseño (defaults legítimos): una
    licitación abierta solo trae la estimación p10/p50/p90; una adjudicada
    sin estimación previa solo trae la baja real; scoreada y adjudicada trae
    ambos para comparar.
    """

    licitacion_id: str
    p10: float | None = None
    p50: float | None = None
    p90: float | None = None
    model_version: str | None = None
    computed_at: str | None = None
    serving: str | None = None
    baja_real: float | None = None
    importe_adjudicado: float | None = None


@router.get(
    "/licitaciones/{licitacion_id:path}/prediccion-baja",
    summary="Intervalo de baja esperada (p10/p50/p90)",
    responses={404: {"description": "Sin predicción para esa licitación"}},
)
async def get_prediccion_baja(
    licitacion_id: str,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> PrediccionBajaResult:
    data = await run_db(prediccion_baja, licitacion_id)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sin predicción ni adjudicación registrada para esa licitación.",
        )
    return PrediccionBajaResult(**data)


@router.get(
    "/predicciones/calibracion",
    summary="Calibración del modelo de baja — cobertura empírica del intervalo p10-p90",
    response_model=CalibracionBajaDTO,
)
@cache_response(ttl=_CALIBRACION_CACHE_TTL_S, namespace="ml")
async def get_calibracion_baja(
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> CalibracionBajaDTO:
    """Cobertura real del intervalo p10-p90 vs bajas observadas (closed-loop).

    On-demand: no hay tabla materializada, se computa contra
    ``predicciones_baja``/``adjudicaciones`` al vuelo (cacheado ~15 min).
    ``estado='insuficiente'`` cuando aún no hay suficientes pares
    predicción↔realidad resueltos (menos de 30 licitaciones adjudicadas
    con predicción previa) — no es un error, es el estado esperado en un
    despliegue nuevo o con poco volumen de adjudicaciones recientes.
    """
    return await run_db(calibracion_baja_dto)


@router.get(
    "/licitaciones/{licitacion_id:path}/escenarios-precio",
    summary="Escenarios descriptivos de precio sobre adjudicaciones comparables",
    response_model=PriceScenariosResult,
    responses={404: {"description": "Licitación inexistente"}},
)
async def get_escenarios_precio(
    licitacion_id: str,
    competencia_esperada: int | None = None,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> PriceScenariosResult:
    """Devuelve cuantiles históricos; deliberadamente no devuelve P(ganar)."""
    if competencia_esperada is not None and competencia_esperada < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="competencia_esperada debe ser al menos 1.",
        )
    data = await run_db(
        get_price_scenarios,
        licitacion_id,
        expected_competition=competencia_esperada,
    )
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Licitación no encontrada.",
        )
    return data
