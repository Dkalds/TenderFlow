"""Rutas de predicciones ML (Fase 6, RFC 20260611-2).

- ``GET /licitaciones/{id}/prediccion-baja`` — intervalo p10/p50/p90 de la
  baja esperada, materializado por el batch nocturno. Toda predicción expone
  ``model_version`` y ``computed_at`` (trazabilidad anti-"número mágico");
  ``model_version`` NULL = baseline histórico, no modelo. Si la licitación
  ya está adjudicada, además incluye ``baja_real``/``importe_adjudicado``
  para comparar la estimación (si la hubo) contra el resultado real.

Las dos operaciones sobre una licitación —``prediccion-baja`` y
``escenarios-precio``— aceptan ``lote_id`` (S3.1), porque un expediente
dividido en lotes no se puja entero: se puja un lote, con su presupuesto.
``lote_id`` ausente = expediente completo, con exactamente el mismo cálculo y
los mismos valores de siempre (``prediccion-baja`` ni siquiera cambia el
payload, porque serializa con ``exclude_unset``; ``escenarios-precio`` le suma
los dos campos nuevos a ``null``, que es el precio de mantener el esquema
OpenAPI intacto — ver el comentario de ``PriceScenariosResult.lote_id``).
``lote_id`` de otro expediente = 404. No confundir con el ``incluir_lote`` de
``/predicciones/calibracion``, que es otra cosa: un bloque de diagnóstico
agregado, no un cambio de unidad.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from services.ml.calibration import CalibracionBajaDTO, calibracion_baja_dto
from services.ml.pricing_scenarios import PriceScenariosResult, get_price_scenarios
from services.ml.scoring import LoteDesconocidoError, prediccion_baja
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
    #: Campos ADITIVOS (S3.1), presentes solo cuando se pidió un lote. Como la
    #: ruta serializa con ``exclude_unset``, en el camino sin lote no aparecen:
    #: la respuesta del expediente completo es exactamente la de siempre.
    lote_id: int | None = None
    #: ``lotes.numero``, la identidad estable del lote (``lotes.id`` se
    #: renumera en cada re-ingesta; ver la cabecera de la revisión ``v110``).
    lote_numero: str | None = None
    #: Granularidad **de la estimación**, que no siempre es la que se pidió:
    #: ``lote`` si el batch materializó una fila de ese lote, ``expediente`` si
    #: se sirve la del expediente entero a falta de modelo por lote (v86 dejó
    #: la columna, el switch sigue pendiente de medir su ``mae_p50``).
    #: ``baja_real``/``importe_adjudicado`` sí son siempre del lote pedido.
    prediccion_ambito: str | None = None


@router.get(
    "/licitaciones/{licitacion_id:path}/prediccion-baja",
    summary="Intervalo de baja esperada (p10/p50/p90)",
    responses={404: {"description": "Sin predicción para esa licitación"}},
    # Los bloques son condicionales (ver el docstring del DTO): la ausencia de
    # `p50` significa "el batch nunca scoreó esta licitación", distinto de un
    # p50 nulo. Al tipar la respuesta, la serialización pasó a emitir todos los
    # campos con `null` y esa distinción se perdía.
    #
    # `exclude_unset`, NO `exclude_none`: `prediccion_baja` arma el dict por
    # bloques, así que lo que no vino de la BD ni se pasa al constructor y
    # queda sin marcar. Con `exclude_none` se caía además `model_version` nulo,
    # que sí significa algo — "baseline histórico, no modelo" — y que el
    # contrato de trazabilidad exige emitir siempre que haya predicción.
    response_model_exclude_unset=True,
)
async def get_prediccion_baja(
    licitacion_id: str,
    lote_id: int | None = None,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> PrediccionBajaResult:
    try:
        data = await run_db(prediccion_baja, licitacion_id, lote_id)
    except LoteDesconocidoError as exc:
        # 404 y no 422: el lote es un recurso que se pide por id, y "ese lote
        # no está en este expediente" es exactamente un no-encontrado. El
        # mensaje se separa del de abajo porque son dos cosas distintas —id
        # equivocado vs. sin datos todavía— y confundirlas manda a quien
        # depura a buscar el fallo donde no está.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Sin predicción ni adjudicación registrada para esa licitación."
                if lote_id is None
                else "Sin predicción ni adjudicación registrada para ese lote."
            ),
        )
    return PrediccionBajaResult(**data)


@router.get(
    "/predicciones/calibracion",
    summary="Calibración del modelo de baja — cobertura empírica del intervalo p10-p90",
    response_model=CalibracionBajaDTO,
)
@cache_response(ttl=_CALIBRACION_CACHE_TTL_S, namespace="ml")
async def get_calibracion_baja(
    incluir_lote: bool = False,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> CalibracionBajaDTO:
    """Cobertura real del intervalo p10-p90 vs bajas observadas (closed-loop).

    On-demand: no hay tabla materializada, se computa contra
    ``predicciones_baja``/``adjudicaciones`` al vuelo (cacheado ~15 min).
    ``estado='insuficiente'`` cuando aún no hay suficientes pares
    predicción↔realidad resueltos (menos de 30 licitaciones adjudicadas
    con predicción previa) — no es un error, es el estado esperado en un
    despliegue nuevo o con poco volumen de adjudicaciones recientes.

    ``incluir_lote=true`` añade el bloque ``por_lote`` con la misma medida a
    granularidad de lote (la unidad sobre la que se puja). Es **diagnóstico**:
    los campos de primer nivel siguen describiendo lo que se sirve, y mientras
    ``por_lote.n_prediccion_por_lote`` sea 0 ese bloque es el modelo agregado
    evaluado por lote, no un modelo por lote. Opt-in porque duplica el coste de
    la agregación; la clave de caché incluye el parámetro, así que las dos
    variantes no se pisan.
    """
    return await run_db(calibracion_baja_dto, incluir_lote)


@router.get(
    "/licitaciones/{licitacion_id:path}/escenarios-precio",
    summary="Escenarios descriptivos de precio sobre adjudicaciones comparables",
    response_model=PriceScenariosResult,
    responses={404: {"description": "Licitación (o lote) inexistente"}},
)
async def get_escenarios_precio(
    licitacion_id: str,
    lote_id: int | None = None,
    competencia_esperada: int | None = None,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> PriceScenariosResult:
    """Devuelve cuantiles históricos; deliberadamente no devuelve P(ganar).

    Con ``lote_id`` los tres precios se calculan sobre el presupuesto de ese
    lote (S3.1). Sin él, sobre el del expediente, como siempre.
    """
    if competencia_esperada is not None and competencia_esperada < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="competencia_esperada debe ser al menos 1.",
        )
    data = await run_db(
        get_price_scenarios,
        licitacion_id,
        lote_id=lote_id,
        expected_competition=competencia_esperada,
    )
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Licitación no encontrada."
                if lote_id is None
                # Cubre las dos formas de no encontrarlo —lote de otro
                # expediente, o expediente inexistente— porque desde fuera son
                # la misma: ese lote no está aquí.
                else "Lote no encontrado en esa licitación."
            ),
        )
    return data
