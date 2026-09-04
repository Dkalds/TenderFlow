"""Rutas /api/v1/empresas — maestro de empresas (entity resolution).

Expone la dimensión canónica de empresas adjudicatarias: búsqueda, detalle
con aliases/UTEs, cobertura de resolución y la cola de revisión humana de
matches fuzzy (listar + resolver).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from db.audit import log_event
from db.empresas import apply_review, list_pending_reviews, resolution_stats
from db.repositories.empresas import EmpresasReadRepository
from observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/empresas", tags=["empresas"])


# ── DTOs del contrato (campos sin default: la query siempre trae la clave) ──


class EmpresaListItem(BaseModel):
    """Fila del buscador del maestro (agregados de adjudicaciones incluidos)."""

    empresa_id: int
    nombre_canonico: str
    nif_canonico: str | None
    es_ute: int
    es_pyme: int | None
    grupo: str | None
    n_adjudicaciones: int
    importe_total: float


class EmpresasListResult(BaseModel):
    items: list[EmpresaListItem]
    limit: int
    offset: int


class EmpresasStats(BaseModel):
    """Cobertura de la resolución de entidades sobre adjudicaciones."""

    adjudicaciones_total: int
    adjudicaciones_enlazadas: int
    pct_filas: float
    importe_total: float
    importe_enlazado: float
    pct_importe: float
    empresas: int
    revisiones_pendientes: int


class EmpresaReviewItem(BaseModel):
    """Entrada pendiente de la cola de revisión humana de matches fuzzy."""

    id: int
    nombre_original: str | None
    alias_normalizado: str | None
    nif: str | None
    score: float | None
    candidato_empresa_id: int | None
    candidato_nombre: str | None
    candidato_nif: str | None
    created_at: str | None


class EmpresaReviewsResult(BaseModel):
    items: list[EmpresaReviewItem]


class ReviewResolved(BaseModel):
    """Resultado de resolver una revisión (empresa vinculada o creada)."""

    status: str
    review_id: int
    empresa_id: int


class EmpresaAlias(BaseModel):
    alias_normalizado: str
    nif_variante: str | None
    fuente: str | None
    confianza: float | None


class EmpresaRef(BaseModel):
    """Referencia mínima a otra empresa canónica (miembro/UTE contenedora)."""

    empresa_id: int
    nombre_canonico: str
    nif_canonico: str | None = None


class EmpresaDetail(BaseModel):
    """Empresa canónica con aliases y relaciones UTE."""

    empresa_id: int
    nombre_canonico: str
    nif_canonico: str | None
    es_ute: int
    es_pyme: int | None
    grupo: str | None
    created_at: str | None
    updated_at: str | None
    aliases: list[EmpresaAlias]
    ute_miembros: list[EmpresaRef]
    participa_en_utes: list[EmpresaRef]


def _require_review_admin(ctx: dict[str, Any] = Depends(require_any_auth)) -> dict[str, Any]:
    """Human entity-resolution reviews mutate global canonical data."""
    if not ctx.get("is_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required.")
    return ctx


_repo = EmpresasReadRepository()


@router.get("", summary="Buscar empresas del maestro")
async def list_empresas(
    q: str | None = Query(None, max_length=200, description="Nombre, alias o NIF (parcial)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> EmpresasListResult:
    """Lista empresas canónicas ordenadas por importe adjudicado total."""
    items = await run_db(_repo.list_empresas, q, limit, offset)
    return EmpresasListResult(
        items=[EmpresaListItem(**item) for item in items], limit=limit, offset=offset
    )


@router.get("/stats", summary="Cobertura del maestro de empresas")
async def empresas_stats(_ctx: dict[str, Any] = Depends(require_any_auth)) -> EmpresasStats:
    """% de adjudicaciones (filas e importe) resueltas a empresa canónica."""
    return EmpresasStats(**await run_db(resolution_stats))


@router.get("/reviews", summary="Cola de revisión de matches fuzzy")
async def pending_reviews(
    limit: int = Query(100, ge=1, le=500),
    _ctx: dict[str, Any] = Depends(_require_review_admin),
) -> EmpresaReviewsResult:
    items = await run_db(list_pending_reviews, limit)
    return EmpresaReviewsResult(items=[EmpresaReviewItem(**item) for item in items])


class ReviewDecision(BaseModel):
    accept: bool = Field(
        ...,
        description="True: el alias pertenece al candidato. False: es una empresa distinta (se crea nueva).",
    )


@router.post(
    "/reviews/{review_id}",
    summary="Resolver una entrada de la cola de revisión",
    responses={404: {"description": "Revisión inexistente o ya resuelta"}},
)
async def resolve_review(
    review_id: int,
    body: ReviewDecision,
    ctx: dict[str, Any] = Depends(_require_review_admin),
) -> ReviewResolved:
    """Acepta o rechaza un match dudoso y vincula sus adjudicaciones pendientes."""
    resolved_by = str(ctx.get("email") or ctx.get("key_hash") or "api")[:64]
    empresa_id = await run_db(apply_review, review_id, accept=body.accept, resolved_by=resolved_by)
    if empresa_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Revisión inexistente o ya resuelta.",
        )
    await run_db(
        log_event,
        event_type="empresa.review_resolved",
        user_key=resolved_by[:8],
        resource=f"empresa_review:{review_id}",
        detail={"accept": body.accept, "empresa_id": empresa_id},
    )
    return ReviewResolved(status="ok", review_id=review_id, empresa_id=empresa_id)


@router.get(
    "/{empresa_id}",
    summary="Detalle de una empresa canónica",
    responses={404: {"description": "Empresa no encontrada"}},
)
async def get_empresa(
    empresa_id: int,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> EmpresaDetail:
    """Empresa con sus aliases, miembros de UTE y UTEs en las que participa."""
    empresa = await run_db(_repo.get_empresa, empresa_id)
    if empresa is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa no encontrada.")
    return EmpresaDetail(**empresa)
