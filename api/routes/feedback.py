"""Ruta /api/v1/feedback — recoge feedback de relevancia de licitaciones."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from api.concurrency import run_db, run_ml
from api.routes.dual_auth import require_any_auth
from db.audit import log_event
from db.repositories.feedback import FeedbackRepository
from db.repositories.licitaciones import LicitacionRepository
from observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])

_repo = FeedbackRepository()
_lic_repo = LicitacionRepository()


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

    @field_validator("expediente")
    @classmethod
    def sanitize_expediente(cls, v: str) -> str:
        return "".join(ch for ch in v if ch.isprintable()).strip()


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

    log_event(
        event_type="feedback.submitted",
        user_key=ctx.get("key_hash", ctx.get("email", "session"))[:8],
        resource=f"licitacion:{body.expediente}",
        detail={"relevante": body.relevante},
    )
    log.info("feedback_stored", expediente=body.expediente, relevante=body.relevante)
    return response_data


@router.get(
    "/stats",
    summary="Estadísticas de feedback",
    responses={401: {"description": "API key inválida"}},
)
async def feedback_stats(
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, Any]:
    """Devuelve estadísticas agregadas del feedback recogido."""
    return await run_db(_repo.stats)


@router.get(
    "/queue",
    summary="Cola de active learning (uncertainty sampling)",
    responses={401: {"description": "API key inválida"}},
)
async def feedback_queue(
    strategy: str = Query("uncertainty", description="uncertainty | random"),
    limit: int = Query(20, ge=1, le=200),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, Any]:
    """Devuelve licitaciones priorizadas para etiquetado.

    - ``uncertainty``: prioriza las que el modelo clasifica con menor confianza.
    - ``random``: muestra aleatoria (baseline).

    La inferencia ML se ejecuta en threadpool para no bloquear el event loop.
    """
    limit = max(1, min(limit, 200))

    if strategy == "uncertainty":
        try:
            candidates = await run_db(_lic_repo.get_unlabelled_candidates, 500)
            if not candidates:
                return {"items": [], "strategy": strategy, "model_version": None}

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
                return [
                    {
                        "id_externo": s["id_externo"],
                        "titulo": s["titulo"],
                        "confidence": round(s["confidence"], 3),
                        "uncertainty": round(s["uncertainty"], 3),
                    }
                    for s in scores[:limit]
                ]

            items = await run_ml(_predict)
            return {"items": items, "strategy": strategy, "model_version": None}

        except Exception as exc:
            log.warning("uncertainty_sampling_failed", error=str(exc))
            # Fallback to random

    items = await run_db(_lic_repo.get_unlabelled_random, limit)
    return {"items": items, "strategy": "random", "model_version": None}
