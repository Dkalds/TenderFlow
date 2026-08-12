"""Ruta /api/v1/feedback — recoge feedback de relevancia de licitaciones."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from api.concurrency import run_db, run_ml
from api.routes.dual_auth import require_any_auth
from config.keywords import TECH_LABELS
from db.audit import log_event
from db.repositories.feedback import FeedbackRepository
from db.repositories.licitaciones import LicitacionRepository
from observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])

_repo = FeedbackRepository()
_lic_repo = LicitacionRepository()


def _safe_float(val: Any) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


class FeedbackStats(BaseModel):
    """Conteos agregados de ml_feedback (SUM sobre tabla vacía → None)."""

    total: int
    positivos: int | None
    negativos: int | None
    last_feedback_at: str | None


class ModelHistoryEntry(BaseModel):
    version: str
    trained_at: str | None
    metrics: dict[str, Any] | None


class ModelInfoResult(BaseModel):
    """Resumen del modelo activo (registry) para el panel de active learning."""

    name: str
    # Fila cruda del registry (id/version/path/sha256/metrics/...): forma libre
    # del almacén, None si aún no hay versión activa.
    active: dict[str, Any] | None
    feedbacks_since_train: int
    history: list[ModelHistoryEntry]


class QueueModelBlock(BaseModel):
    """Scores del TechnologyClassifier para un candidato de la cola."""

    tech_scores: dict[str, float]
    tech_predicted: list[str]
    tech_principal: str | None
    tech_max_proba: float
    tech_thresholds: dict[str, float]


class FeedbackQueueItem(BaseModel):
    """Candidato de etiquetado con contexto y confianza del modelo."""

    id_externo: str
    titulo: str
    descripcion: str
    cpv: str | None
    importe: float | None
    organo: str | None
    ccaa: str | None
    fecha_publicacion: str | None
    url_origen: str | None
    confidence: float
    uncertainty: float
    tecnologia: str | None
    model: QueueModelBlock | None


class FeedbackQueueResult(BaseModel):
    items: list[FeedbackQueueItem]
    strategy: str
    model_version: str | None


def _build_queue_items(
    candidates: list[dict[str, Any]],
    *,
    include_model: bool = True,
    tech_classifier: Any = None,
) -> list[dict[str, Any]]:
    """Construye el payload de la cola con campos contextuales y, opcionalmente,
    el bloque ``model`` con los scores del TechnologyClassifier.

    ``candidates`` viene de ``get_unlabelled_candidates`` o
    ``get_unlabelled_random`` y ya tiene los campos extra (descripcion, cpv,
    importe, organo_contratacion, ccaa, fecha_publicacion, url, tecnologia,
    ml_tecnologias, ml_proba_max, ml_tech_principal).
    """

    if not candidates:
        return []

    tech_batch_results: list[dict[str, Any]] | None = None
    if include_model and tech_classifier is not None:
        try:
            items_for_batch = [
                {
                    "text": f"{c.get('titulo', '')} {c.get('descripcion') or ''}",
                    "cpv": c.get("cpv"),
                    "importe": _safe_float(c.get("importe")),
                }
                for c in candidates
            ]
            tech_batch_results = tech_classifier.predict_batch(items_for_batch)
        except Exception:
            log.warning("tech_classifier_batch_failed", exc_info=True)
            tech_batch_results = None

    results: list[dict[str, Any]] = []
    for i, c in enumerate(candidates):
        model_block: dict[str, Any] | None = None
        if include_model and tech_batch_results and i < len(tech_batch_results):
            t = tech_batch_results[i]
            model_block = {
                "tech_scores": {k: round(v, 3) for k, v in t.get("scores", {}).items()},
                "tech_predicted": t.get("predicted", []),
                "tech_principal": t.get("principal"),
                "tech_max_proba": round(t.get("max_proba", 0.0), 3),
                "tech_thresholds": {k: round(v, 3) for k, v in t.get("thresholds", {}).items()},
            }

        results.append(
            {
                "id_externo": c["id_externo"],
                "titulo": c.get("titulo", ""),
                "descripcion": (c.get("descripcion") or "")[:500],
                "cpv": c.get("cpv"),
                "importe": _safe_float(c.get("importe")) if c.get("importe") is not None else None,
                "organo": c.get("organo_contratacion"),
                "ccaa": c.get("ccaa"),
                "fecha_publicacion": c.get("fecha_publicacion"),
                "url_origen": c.get("url"),
                "confidence": round(
                    _safe_float(
                        c.get("confidence")
                        if c.get("confidence") is not None
                        else c.get("ml_proba_max")
                    ),
                    3,
                ),
                "uncertainty": round(
                    _safe_float(
                        c.get("uncertainty")
                        if c.get("uncertainty") is not None
                        else abs(_safe_float(c.get("ml_proba_max")) - 0.5)
                    ),
                    3,
                ),
                "tecnologia": c.get("tecnologia"),
                "model": model_block,
            }
        )
    return results


class FeedbackRequest(BaseModel):
    expediente: str = Field(
        ...,
        min_length=1,
        max_length=100,
        examples=["PRO/2024/12345"],
        description="Identificador externo de la licitación.",
    )
    relevante: bool = Field(
        ...,
        examples=[True],
        description="True si la licitación es relevante.",
    )
    nota: str = Field(
        default="",
        max_length=500,
        examples=["Encaja con perfil SAP S/4HANA Cloud"],
        description="Nota libre opcional (máx. 500 chars).",
    )
    tecnologia: str | None = Field(
        default=None,
        examples=["SAP"],
        description="Tecnología principal seleccionada por el etiquetador.",
    )
    tecnologias_secundarias: list[str] = Field(
        default_factory=list,
        examples=[["MICROSOFT", "INFOR"]],
        description="Tecnologías secundarias (multi-label).",
    )

    @field_validator("expediente")
    @classmethod
    def sanitize_expediente(cls, v: str) -> str:
        return "".join(ch for ch in v if ch.isprintable()).strip()

    @field_validator("tecnologia")
    @classmethod
    def validate_tecnologia(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v_upper = v.upper().strip()
        if v_upper not in TECH_LABELS:
            raise ValueError(f"tecnologia debe ser una de {TECH_LABELS}, got '{v}'")
        return v_upper

    @field_validator("tecnologias_secundarias")
    @classmethod
    def validate_secundarias(cls, v: list[str]) -> list[str]:
        invalid = [t for t in v if t.upper().strip() not in TECH_LABELS]
        if invalid:
            raise ValueError(
                f"tecnologias_secundarias contiene labels inválidas: {invalid}. "
                f"Permitidas: {TECH_LABELS}"
            )
        return [t.upper().strip() for t in v]


class FeedbackResponse(BaseModel):
    status: str
    expediente: str
    stored_at: str


@router.post(
    "",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Feedback almacenado"},
        401: {"description": "API key inválida"},
        422: {"description": "Body inválido"},
    },
)
async def submit_feedback(
    body: FeedbackRequest,
    ctx: dict[str, Any] = Depends(require_any_auth),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> FeedbackResponse:
    """Registra el feedback de relevancia de una licitación.

    Si se incluye el header ``Idempotency-Key``, requests repetidas con la
    misma clave devuelven la respuesta original sin insertar duplicados.
    El cache tiene TTL de 24h.
    """
    # -- Idempotency check --
    if idempotency_key:
        cached = await run_db(_repo.exists_idempotency, idempotency_key)
        if cached is not None:
            log.info("feedback_idempotent_hit", key=idempotency_key[:16])
            return FeedbackResponse(**cached)

    try:
        stored_at = await run_db(
            _repo.insert,
            expediente=body.expediente,
            relevante=body.relevante,
            nota=body.nota,
            tecnologia=body.tecnologia,
            tecnologias_secundarias=body.tecnologias_secundarias or None,
            user_id=int(ctx["user_id"]),
        )
    except Exception as exc:
        log.error("feedback_store_error", expediente=body.expediente, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al almacenar el feedback.",
        ) from exc

    response_data = FeedbackResponse(
        status="ok",
        expediente=body.expediente,
        stored_at=stored_at,
    )

    # -- Persist idempotency key --
    if idempotency_key:
        await run_db(_repo.store_idempotency, idempotency_key, response_data.model_dump())

    await run_db(
        log_event,
        event_type="feedback.submitted",
        user_key=str(ctx.get("user_key", "system"))[:8],
        resource=f"licitacion:{body.expediente}",
        detail={
            "relevante": body.relevante,
            "tecnologia": body.tecnologia,
            "tecnologias_secundarias": body.tecnologias_secundarias,
        },
    )
    log.info(
        "feedback_stored",
        expediente=body.expediente,
        relevante=body.relevante,
        tecnologia=body.tecnologia,
    )
    return response_data


@router.get(
    "/stats",
    summary="Estadísticas de feedback",
    responses={401: {"description": "API key inválida"}},
)
async def feedback_stats(
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> FeedbackStats:
    """Devuelve estadísticas agregadas del feedback recogido."""
    return FeedbackStats(**await run_db(_repo.stats))


@router.get(
    "/model-info",
    summary="Estado del modelo activo (cierre del bucle de active learning)",
    responses={401: {"description": "API key inválida"}},
)
async def feedback_model_info(
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> ModelInfoResult:
    """Versión del modelo activo, etiquetas desde el último reentreno y tendencia
    de métricas — para que el etiquetado muestre su impacto, no se sienta gratis.

    Todo proviene del model registry (BD); no carga el modelo ML.
    """
    from db.model_registry import active_model_summary

    return ModelInfoResult(**await run_db(active_model_summary))


@router.get(
    "/queue",
    summary="Cola de active learning (uncertainty sampling)",
    responses={401: {"description": "API key inválida"}},
)
async def feedback_queue(
    strategy: str = Query("uncertainty", description="uncertainty | random"),
    limit: int = Query(20, ge=1, le=200),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> FeedbackQueueResult:
    """Devuelve licitaciones priorizadas para etiquetado.

    - ``uncertainty``: prioriza las que el modelo clasifica con menor confianza.
    - ``random``: muestra aleatoria (baseline).

    La inferencia ML se ejecuta en threadpool para no bloquear el event loop.
    Incluye el bloque ``model`` con scores del TechnologyClassifier si está
    disponible; si no, ``model`` es ``null`` (degradación elegante).
    """
    limit = max(1, min(limit, 200))

    # Intentar cargar TechnologyClassifier (lazy, en threadpool)
    tech_clf: Any = None
    try:

        def _load_tech() -> Any:
            from scraper.tech_classifier import TechnologyClassifier

            if TechnologyClassifier.is_available():
                return TechnologyClassifier.load()
            return None

        tech_clf = await run_ml(_load_tech)
    except Exception as exc:
        log.warning("tech_classifier_unavailable", error=str(exc))
        tech_clf = None

    if strategy == "uncertainty":
        try:
            candidates = await run_db(_lic_repo.get_unlabelled_candidates, 500)
            if not candidates:
                return FeedbackQueueResult(items=[], strategy=strategy, model_version=None)

            texts = [f"{c['titulo']} {c.get('descripcion') or ''}" for c in candidates]

            def _predict() -> list[dict[str, Any]]:
                from scraper.ml_classifier import SAPClassifier

                clf = SAPClassifier.load()
                probs = clf.predict_proba(texts)
                scores = []
                for i, row in enumerate(candidates):
                    p = float(probs[i][1]) if hasattr(probs[i], "__len__") else 0.5
                    uncertainty = abs(p - 0.5)
                    scores.append({"uncertainty": uncertainty, "confidence": p, **row})
                scores.sort(key=lambda x: x["uncertainty"])
                return scores[:limit]

            sorted_candidates = await run_ml(_predict)
            items = _build_queue_items(
                sorted_candidates, include_model=True, tech_classifier=tech_clf
            )
            return FeedbackQueueResult(
                items=[FeedbackQueueItem(**item) for item in items],
                strategy=strategy,
                model_version=None,
            )

        except Exception as exc:
            log.warning("uncertainty_sampling_failed", error=str(exc))

    # Random / fallback
    candidates = await run_db(_lic_repo.get_unlabelled_random, limit)
    items = _build_queue_items(candidates, include_model=True, tech_classifier=tech_clf)
    return FeedbackQueueResult(
        items=[FeedbackQueueItem(**item) for item in items],
        strategy="random",
        model_version=None,
    )
