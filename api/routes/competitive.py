"""Rutas /api/v1/competitive — inteligencia competitiva (Fase 2).

Renovaciones (contratos que vencen), análisis de bajas, cuota de mercado,
concentración HHI, perfil de competidor y watchlist por empresa.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from api.tenancy import require_organization, resolve_organization_ctx
from db.watchlist_empresas import (
    WatchlistEmpresaEntry,
    add_entry,
    list_entries,
    remove_entry,
)
from observability.logging import get_logger
from services.competitive.bajas import baja_de_referencia, bajas_agregadas
from services.competitive.mercado import (
    concentracion_hhi,
    cuota_mercado,
    listar_adjudicaciones_empresa,
    metric_scope,
    perfil_empresa,
)
from services.competitive.renovaciones import (
    RenovacionesResult,
    RenovacionesResumenResult,
    proximas_renovaciones,
    resumen_renovaciones,
    totales_renovaciones,
)
from shared.dto import CompetitiveCompanyAwardsDTO, CompetitiveCompanyProfileDTO
from shared.metric_scope import MetricScope

log = get_logger(__name__)

router = APIRouter(prefix="/competitive", tags=["competitive"])


def _user_key(ctx: dict[str, Any]) -> str:
    """Clave opaca estable de la identidad humana autenticada."""
    if ctx.get("user_key"):
        return str(ctx["user_key"])
    seed = str(ctx.get("email") or ctx.get("key_hash") or "anon")
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _split_filter(value: str | None) -> list[str] | None:
    items = [item.strip() for item in (value or "").split(",") if item.strip()]
    return items or None


def _split_int_filter(value: str | None) -> list[int] | None:
    items = _split_filter(value)
    if not items:
        return None
    try:
        return [int(item) for item in items]
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="empresa_ids debe ser una lista de IDs numéricos separados por comas.",
        ) from exc


# ── Renovaciones ──────────────────────────────────────────────────────────


@router.get("/renovaciones", summary="Contratos que vencen próximamente")
async def get_renovaciones(
    months: int = Query(6, ge=1, le=60, description="Horizonte en meses"),
    empresa_id: int | None = Query(None),
    ccaa: str | None = Query(None, max_length=50),
    tecnologia: str | None = Query(
        None,
        max_length=200,
        description="Tecnología(s) separadas por comas (filtro global)",
    ),
    min_importe: float | None = Query(None, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> RenovacionesResult:
    """Pipeline de renovaciones: cada fila es un contrato-adjudicatario con
    fecha de fin efectiva (explícita o calculada con la duración CODICE)."""
    tecnologias = [t.strip() for t in (tecnologia or "").split(",") if t.strip()]
    items = await run_db(
        proximas_renovaciones,
        months_ahead=months,
        empresa_id=empresa_id,
        ccaa=ccaa,
        tecnologias=tecnologias or None,
        min_importe=min_importe,
        limit=limit,
        offset=offset,
    )
    return RenovacionesResult.model_validate({"items": items, "months_ahead": months})


@router.get("/renovaciones/resumen", summary="Cartera en juego por empresa")
async def get_renovaciones_resumen(
    months: int = Query(12, ge=1, le=60),
    tecnologia: str | None = Query(
        None,
        max_length=200,
        description="Tecnología(s) separadas por comas (filtro global)",
    ),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> RenovacionesResumenResult:
    tecnologias = [t.strip() for t in (tecnologia or "").split(",") if t.strip()]
    items = await run_db(
        resumen_renovaciones,
        months_ahead=months,
        tecnologias=tecnologias or None,
    )
    totales = await run_db(
        totales_renovaciones,
        months_ahead=months,
        tecnologias=tecnologias or None,
    )
    return RenovacionesResumenResult.model_validate(
        {"items": items, "months_ahead": months, "totales": totales}
    )


# ── Bajas ─────────────────────────────────────────────────────────────────


# ── DTOs del contrato (campos sin default: la query siempre trae la clave) ──


class BajaAgregada(BaseModel):
    """Baja media por grupo (empresa/órgano/CPV/CCAA)."""

    # Solo el group_by=empresa lleva id del maestro — clave condicional.
    grupo_id: int | None = None
    grupo: str | None
    contratos: int
    baja_media_pct: float | None
    baja_min_pct: float | None
    baja_max_pct: float | None
    importe_total: float
    ofertas_medias: float | None


class BajasResult(BaseModel):
    items: list[BajaAgregada]
    group_by: str


class BajaReferencia(BaseModel):
    """Baja media y rango del segmento pedido (órgano y/o prefijo CPV)."""

    contratos: int | None = None
    baja_media_pct: float | None = None
    baja_min_pct: float | None = None
    baja_max_pct: float | None = None
    ofertas_medias: float | None = None
    organo: str | None
    cpv_prefix: str | None


class CuotaEmpresa(BaseModel):
    empresa_id: int | None
    empresa: str | None
    es_ute: int
    contratos: int
    importe: float
    ofertas_medias: float | None
    cuota_pct: float | None


class CuotaResult(BaseModel):
    items: list[CuotaEmpresa]
    scope: MetricScope


class HhiSegmento(BaseModel):
    segmento: str | None
    empresas: int
    importe_total: float
    contratos: int
    hhi: float | None


class HhiResult(BaseModel):
    items: list[HhiSegmento]
    segment_by: str
    scope: MetricScope


class WatchlistEmpresaItem(BaseModel):
    """Empresa vigilada, con nombre canónico del maestro."""

    id: int
    empresa_id: int
    nombre_canonico: str
    nif_canonico: str | None
    email: str | None
    frequency: str | None
    created_at: str | None
    last_notified_at: str | None
    organization_id: int | None
    visibility: str | None


class WatchlistEmpresasResult(BaseModel):
    items: list[WatchlistEmpresaItem]


class WatchlistEmpresaStatus(BaseModel):
    """Alta/baja de vigilancia; ``id`` solo cuando se creó una entrada nueva."""

    status: str
    empresa_id: int
    id: int | None = None


@router.get("/bajas", summary="Baja media por empresa, órgano, CPV o CCAA")
async def get_bajas(
    group_by: str = Query("empresa", pattern="^(empresa|organo|cpv|ccaa)$"),
    min_contratos: int = Query(3, ge=1, le=100),
    cpv: str | None = Query(None, max_length=8, description="Prefijo CPV"),
    ccaa: str | None = Query(None, max_length=50),
    limit: int = Query(100, ge=1, le=500),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> BajasResult:
    items = await run_db(
        bajas_agregadas,
        group_by=group_by,
        min_contratos=min_contratos,
        cpv_prefix=cpv,
        ccaa=ccaa,
        limit=limit,
    )
    return BajasResult(items=[BajaAgregada(**item) for item in items], group_by=group_by)


@router.get("/bajas/referencia", summary="Baja de referencia para un segmento")
async def get_baja_referencia(
    organo: str | None = Query(None, max_length=300),
    cpv: str | None = Query(None, max_length=8),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> BajaReferencia:
    """'¿Cuánto hay que bajar para ganar en este órgano/CPV?'"""
    return BajaReferencia(**await run_db(baja_de_referencia, organo=organo, cpv_prefix=cpv))


# ── Mercado ───────────────────────────────────────────────────────────────


@router.get("/cuota", summary="Cuota de mercado por empresa")
async def get_cuota(
    cpv: str | None = Query(None, max_length=8),
    ccaa: str | None = Query(None, max_length=50),
    desde: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(50, ge=1, le=500),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> CuotaResult:
    items = await run_db(cuota_mercado, cpv_prefix=cpv, ccaa=ccaa, desde=desde, limit=limit)
    scope = await run_db(metric_scope, cpv_prefix=cpv, ccaa=ccaa, desde=desde)
    return CuotaResult(items=[CuotaEmpresa(**item) for item in items], scope=scope)


@router.get("/hhi", summary="Concentración HHI por segmento")
async def get_hhi(
    segment_by: str = Query("cpv", pattern="^(cpv|ccaa|organo|tecnologia)$"),
    min_contratos: int = Query(5, ge=1, le=100),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> HhiResult:
    items = await run_db(concentracion_hhi, segment_by=segment_by, min_contratos=min_contratos)
    scope = await run_db(metric_scope)
    return HhiResult(
        items=[HhiSegmento(**item) for item in items], segment_by=segment_by, scope=scope
    )


@router.get(
    "/empresas/{empresa_id}/perfil",
    response_model=CompetitiveCompanyProfileDTO,
    summary="Dossier competitivo de una empresa",
)
async def get_perfil(
    empresa_id: int,
    empresa_ids: str | None = Query(
        None,
        max_length=500,
        description="IDs adicionales del grupo (separados por comas) para agregar el dossier",
    ),
    fecha_desde: date | None = Query(None),
    fecha_hasta: date | None = Query(None),
    cpv: str | None = Query(None, max_length=8),
    ccaa: str | None = Query(None, max_length=500),
    tecnologia: str | None = Query(None, max_length=500),
    importe_min: float | None = Query(None, ge=0),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, Any]:
    perfil = await run_db(
        perfil_empresa,
        empresa_id,
        empresa_ids=_split_int_filter(empresa_ids),
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        cpv_prefix=cpv,
        ccaas=_split_filter(ccaa),
        tecnologias=_split_filter(tecnologia),
        importe_min=importe_min,
    )
    if not perfil.pop("_exists", False):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Empresa no encontrada.",
        )
    return perfil


@router.get(
    "/empresas/{empresa_id}/adjudicaciones",
    response_model=CompetitiveCompanyAwardsDTO,
    summary="Adjudicaciones paginadas de una empresa",
)
async def get_adjudicaciones_empresa(
    empresa_id: int,
    empresa_ids: str | None = Query(
        None,
        max_length=500,
        description="IDs adicionales del grupo (separados por comas) para agregar el listado",
    ),
    fecha_desde: date | None = Query(None),
    fecha_hasta: date | None = Query(None),
    cpv: str | None = Query(None, max_length=8),
    ccaa: str | None = Query(None, max_length=500),
    tecnologia: str | None = Query(None, max_length=500),
    importe_min: float | None = Query(None, ge=0),
    q: str | None = Query(None, max_length=200),
    organo: str | None = Query(None, max_length=300),
    sort: str = Query(
        "fecha_desc",
        pattern="^(fecha_desc|fecha_asc|importe_desc|importe_asc)$",
    ),
    limit: int = Query(25, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, Any]:
    return await run_db(
        listar_adjudicaciones_empresa,
        empresa_id,
        empresa_ids=_split_int_filter(empresa_ids),
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        cpv_prefix=cpv,
        ccaas=_split_filter(ccaa),
        tecnologias=_split_filter(tecnologia),
        importe_min=importe_min,
        q=q,
        organo=organo,
        sort=sort,
        limit=limit,
        offset=offset,
    )


# ── Watchlist por empresa ─────────────────────────────────────────────────


class WatchlistEmpresaRequest(BaseModel):
    empresa_id: int = Field(..., ge=1)
    email: str | None = Field(None, max_length=200, description="Destino de alertas")
    frequency: str = Field("daily", pattern="^(immediate|daily|weekly)$")
    organization_id: int | None = Field(default=None, ge=1)
    visibility: str = Field(default="private", pattern="^(private|organization)$")


@router.get("/watchlist", summary="Empresas vigiladas por el usuario")
async def get_watchlist(
    ctx: dict[str, Any] = Depends(require_organization()),
) -> WatchlistEmpresasResult:
    items = await run_db(list_entries, _user_key(ctx), ctx["organization_id"])
    return WatchlistEmpresasResult(items=[WatchlistEmpresaItem(**item) for item in items])


@router.post("/watchlist", status_code=status.HTTP_201_CREATED, summary="Vigilar una empresa")
async def post_watchlist(
    body: WatchlistEmpresaRequest,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> WatchlistEmpresaStatus:
    ctx = await resolve_organization_ctx(ctx, body.organization_id, write=True)
    entry = WatchlistEmpresaEntry(
        user_key=_user_key(ctx),
        empresa_id=body.empresa_id,
        email=body.email or ctx.get("email"),
        frequency=body.frequency,
        organization_id=ctx["organization_id"],
        visibility=body.visibility,
    )
    try:
        entry_id = await run_db(add_entry, entry)
    except Exception as exc:
        # FK violada → empresa inexistente
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Empresa no encontrada en el maestro.",
        ) from exc
    if entry_id is None:
        return WatchlistEmpresaStatus(status="ya_existia", empresa_id=body.empresa_id)
    log.info("watchlist_empresa_added", empresa_id=body.empresa_id)
    return WatchlistEmpresaStatus(status="ok", id=entry_id, empresa_id=body.empresa_id)


@router.delete("/watchlist/{empresa_id}", summary="Dejar de vigilar una empresa")
async def delete_watchlist(
    empresa_id: int,
    ctx: dict[str, Any] = Depends(require_organization(write=True)),
) -> WatchlistEmpresaStatus:
    removed = await run_db(remove_entry, _user_key(ctx), empresa_id, ctx["organization_id"])
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La empresa no estaba en tu watchlist.",
        )
    return WatchlistEmpresaStatus(status="ok", empresa_id=empresa_id)
