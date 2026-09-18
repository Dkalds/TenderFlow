"""Familia **analítica**: lo que el sistema *deduce* sobre un expediente.

``/explain`` (por qué el clasificador lo incluyó), ``/tech-scores`` y
``/tecnologias`` (qué tecnologías se le ven y con qué confianza) y
``/simulador`` (qué precios salen de adjudicaciones comparables). Ninguna
devuelve datos del expediente: devuelven inferencias sobre él, y por eso
todas declaran de dónde sale el número.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from pydantic import BaseModel

from api.concurrency import run_db, run_ml
from api.dependencias_pipeline import paquete_del_pipeline_ausente
from api.routes.dual_auth import require_any_auth
from api.routes.licitaciones._base import (
    _get_classifier,
    _lic_repo,
)
from observability.logging import get_logger
from services.simulador_precio import SimulacionPrecio, simular_precio_de
from shared.tender_facts import EvidenceRef

log = get_logger(__name__)

router = APIRouter(tags=["licitaciones"])


# ── /licitaciones/{id_externo}/explain ───────────────────────────────────


class ExplainFeature(BaseModel):
    """Término y su contribución a la clasificación (modelo lineal)."""

    term: str
    weight: float
    contribution: float


class ExplainPayload(BaseModel):
    """Salida de ``TenderClassifier.explain`` (SHAP-equivalente lineal)."""

    prediction: bool
    confidence: float
    top_features: list[ExplainFeature]
    warning: str | None = None


class ExplainResult(BaseModel):
    """Explicabilidad de la clasificación de una licitación."""

    id_externo: str
    tecnologia: str | None
    explanation: ExplainPayload | None
    warning: str | None = None


@router.get(
    "/licitaciones/{id_externo:path}/explain",
    summary="Explicabilidad de la clasificación SAP/no-SAP",
    responses={
        401: {"description": "API key inválida"},
        404: {"description": "No encontrado"},
        503: {"description": "Modelo no disponible"},
    },
)
async def explain_licitacion(
    id_externo: str,
    top_k: int = Query(5, ge=1, le=20),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> ExplainResult:
    """Devuelve los top-K términos que más influyen en la clasificación."""
    result = await run_db(_lic_repo.get_text_for_ml, id_externo)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado.")

    titulo, descripcion, tecnologia = result
    text = f"{titulo} {descripcion}".strip()
    if not text:
        return ExplainResult(
            id_externo=id_externo,
            tecnologia=tecnologia,
            explanation=None,
            warning="Texto vacío.",
        )

    def _explain() -> Any:
        clf = _get_classifier()
        return clf.explain(text, top_k=top_k)

    try:
        explanation = await run_ml(_explain)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Modelo no disponible. Entrena el clasificador primero.",
        ) from None
    except Exception as exc:
        # C3.1: la imagen de la API no instala scikit-learn, y el clasificador
        # es un pipeline de sklearn serializado. Es un estado conocido del
        # despliegue, no un fallo: 503 y no 500. El destino de esta ruta está
        # en docs/rfc/2026-09-18-rfc-explain-fuera-del-proceso-api.md.
        if paquete := paquete_del_pipeline_ausente(exc):
            log.info("explain_sin_ml_en_imagen", id_externo=id_externo, paquete=paquete)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="La explicación del clasificador no está disponible en este despliegue.",
            ) from None
        log.warning("explain_failed", id_externo=id_externo, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error generando explicación.",
        ) from exc

    return ExplainResult(
        id_externo=id_externo,
        tecnologia=tecnologia,
        explanation=ExplainPayload(**explanation),
    )


@router.get(
    "/licitaciones/{id_externo:path}/simulador",
    summary="Puntos de precio que da cada baja, según la fórmula del pliego",
    responses={401: {"description": "Autenticación inválida"}},
)
async def get_simulador_precio(
    id_externo: str,
    baja: list[float] = Query(
        default=[],
        description=(
            "Bajas a simular, en tanto por uno (0.12 = 12 %). Repetible. Sin "
            "ninguna se usan los escenarios de referencia 5/10/15/20/25 %."
        ),
    ),
    baja_referencia: float | None = Query(
        default=None,
        ge=0,
        le=1,
        description="Baja del rival contra el que medirse (p. ej. el p90 de la predicción)",
    ),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> SimulacionPrecio:
    """F2.2 — el simulador de puntuación de la oferta.

    Devuelve 200 también cuando **no** puede calcular: `sin_calculo` dice por
    qué (sin fórmula extraída, fórmula no calculable, sin puntos de precio) y
    `escenarios` va vacío. Un 404 aquí obligaría al cliente a distinguir «no
    existe el expediente» de «el pliego no publica la fórmula», que son dos
    cosas muy distintas para quien está fijando un precio.
    """
    return await run_db(
        simular_precio_de,
        id_externo,
        bajas=list(baja),
        baja_referencia=baja_referencia,
    )


class TechScore(BaseModel):
    """Score de una tecnología para la licitación (clasificador multi-label)."""

    tecnologia: str
    probabilidad: float
    threshold_aplicado: float | None
    computed_at: str | None


class TechScoresResult(BaseModel):
    id_externo: str
    scores: list[TechScore]


@router.get(
    "/licitaciones/{id_externo:path}/tech-scores",
    summary="Scores multi-tecnología del clasificador (ML_TECH)",
    responses={
        401: {"description": "API key inválida"},
        404: {"description": "No encontrado o sin scores"},
    },
)
async def get_tech_scores(
    id_externo: str,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> TechScoresResult:
    """Devuelve los scores por tecnología desde ``licitacion_tecnologia_score``.

    Cada item incluye ``tecnologia``, ``probabilidad``, ``threshold_aplicado`` y
    ``computed_at``. Lista vacía si la licitación aún no ha sido puntuada por
    el clasificador multi-label (p. ej., ``ML_TECH_ENABLED=False`` o el job
    ``precompute_ml_tecnologias`` no se ha ejecutado todavía).
    """
    scores = await run_db(_lic_repo.tech_scores_for, id_externo)
    return TechScoresResult(id_externo=id_externo, scores=[TechScore(**score) for score in scores])


# ── /licitaciones/{id_externo}/tecnologias ────────────────────────────────


class TecnologiaDetalle(BaseModel):
    """Consolida, por tecnología, las señales que la detectaron.

    ``en_titulo`` es el keyword-match histórico sobre título/descripción
    (``licitaciones.tecnologia`` -- semántica intacta, sin cambios). Las
    demás son aditivas: el clasificador ML sobre título/descripción, y la
    señal detectada en el texto de los pliegos (keywords y/o LLM, plan
    "categorización alimentada por los pliegos"). Cualquier combinación de
    campos puede estar poblada -- una tecnología puede venir solo del pliego
    sin que el título la mencione, que es justamente el caso que este plan
    resuelve (ej. "mantenimiento del sistema de RRHH" sin decir si es SAP
    HCM o Meta4).
    """

    tecnologia: str
    en_titulo: bool
    ml_probabilidad: float | None = None
    ml_threshold_aplicado: float | None = None
    pliego_keywords_score: float | None = None
    pliego_keywords_terms: list[str] | None = None
    pliego_llm_score: float | None = None
    pliego_llm_evidence: list[EvidenceRef] | None = None


class TecnologiasSenalResult(BaseModel):
    id_externo: str
    items: list[TecnologiaDetalle]


@router.get(
    "/licitaciones/{id_externo:path}/tecnologias",
    response_model=TecnologiasSenalResult,
    summary="Tecnologías detectadas: título, ML y señal de pliego (keywords/LLM), con evidencia",
    responses={
        401: {"description": "Autenticación inválida"},
        404: {"description": "No encontrado"},
    },
)
async def get_tecnologias(
    id_externo: str,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> TecnologiasSenalResult:
    """Une por nombre de tecnología las tres fuentes de la categorización:
    título/descripción (keywords), el clasificador ML, y la señal detectada
    en el texto de los pliegos con su evidencia (términos o citas).
    """
    from db.repositories.tecnologia_pliego import TecnologiaPliegoRepository

    data = await run_db(_lic_repo.get_by_id, id_externo)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado.")

    en_titulo = {t.strip() for t in str(data.get("tecnologia") or "").split(",") if t.strip()}
    ml_scores = await run_db(_lic_repo.tech_scores_for, id_externo)
    pliego_repo = TecnologiaPliegoRepository()
    pliego_rows = await run_db(pliego_repo.list_for_licitacion, id_externo)

    items: dict[str, TecnologiaDetalle] = {}

    def _entry(tech: str) -> TecnologiaDetalle:
        if tech not in items:
            items[tech] = TecnologiaDetalle(tecnologia=tech, en_titulo=tech in en_titulo)
        return items[tech]

    for tech in en_titulo:
        _entry(tech)

    for score in ml_scores:
        entry = _entry(str(score["tecnologia"]))
        entry.ml_probabilidad = score.get("probabilidad")
        entry.ml_threshold_aplicado = score.get("threshold_aplicado")

    for row in pliego_rows:
        entry = _entry(str(row["tecnologia"]))
        if row["method"] == "keywords":
            entry.pliego_keywords_score = row["score"]
            terms = row.get("matched_terms")
            entry.pliego_keywords_terms = json.loads(terms) if terms else None
        elif row["method"] == "llm":
            entry.pliego_llm_score = row["score"]
            evidence = row.get("evidence_json")
            entry.pliego_llm_evidence = (
                [EvidenceRef.model_validate(e) for e in json.loads(evidence)] if evidence else None
            )

    def _sort_key(item: TecnologiaDetalle) -> tuple[float, str]:
        best = max(
            item.ml_probabilidad or 0.0,
            item.pliego_keywords_score or 0.0,
            item.pliego_llm_score or 0.0,
        )
        return (-best, item.tecnologia)

    return TecnologiasSenalResult(
        id_externo=id_externo, items=sorted(items.values(), key=_sort_key)
    )
