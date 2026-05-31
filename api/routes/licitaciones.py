"""Rutas /api/v1/licitaciones y /api/v1/adjudicaciones."""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Generator
from typing import Any, Generic, TypeVar

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.auth import AuthContext, require_api_key
from api.concurrency import run_db, run_ml
from api.routes.dual_auth import require_any_auth
from db.repositories.adjudicaciones import AdjudicacionRepository
from db.repositories.licitaciones import LicitacionRepository
from observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["licitaciones"])

_T = TypeVar("_T")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_LIMIT = 500
_MAX_QUERY_LENGTH = 200

# Singletons — instanciados una vez
_lic_repo = LicitacionRepository()
_adj_repo = AdjudicacionRepository()


def _validate_date(value: str | None, field: str) -> None:
    """Raise 422 si el valor no es YYYY-MM-DD."""
    if value is not None and not _DATE_RE.match(value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Parámetro '{field}' debe tener formato YYYY-MM-DD, recibido: {value!r}",
        )


def _validate_query(value: str | None) -> None:
    """Raise 422 si la query de búsqueda excede el límite de caracteres."""
    if value is not None and len(value) > _MAX_QUERY_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Parámetro 'q' excede el máximo de {_MAX_QUERY_LENGTH} caracteres.",
        )


# ── Modelos de respuesta ──────────────────────────────────────────────────


class LicitacionSummary(BaseModel):
    id_externo: str
    titulo: str
    organo_contratacion: str | None = None
    importe: float | None = None
    estado: str | None = None
    fecha_publicacion: str | None = None
    ccaa: str | None = None
    cpv: str | None = None
    url: str | None = None
    tecnologia: str | None = None
    ml_tecnologias: str | None = None
    ml_proba_max: float | None = None
    ml_tech_principal: str | None = None


class LicitacionDetail(LicitacionSummary):
    descripcion: str | None = None
    tipo_contrato: str | None = None
    moneda: str | None = None
    provincia: str | None = None
    nuts_code: str | None = None
    duracion_valor: float | None = None
    duracion_unidad: str | None = None
    fecha_limite: str | None = None
    fecha_inicio: str | None = None
    fecha_fin: str | None = None
    raw_keywords: str | None = None
    fecha_extraccion: str | None = None


class AdjudicacionSummary(BaseModel):
    id: int
    licitacion_id: str
    nombre: str
    nif: str | None = None
    importe_adjudicado: float | None = None
    fecha_adjudicacion: str | None = None
    ccaa: str | None = None
    es_pyme: int | None = None
    n_ofertas_recibidas: int | None = None


class PaginatedResponse(BaseModel, Generic[_T]):
    total: int
    limit: int
    offset: int
    items: list[_T]
    deprecation_notice: str | None = None


class CursorPaginatedResponse(BaseModel, Generic[_T]):
    """Respuesta con paginación por cursor (recomendada para datasets grandes)."""

    items: list[_T]
    next_cursor: str | None = None
    has_more: bool = False
    limit: int


# ── Cursor helpers ────────────────────────────────────────────────────────


def _encode_cursor(fecha: str | None, id_externo: str) -> str:
    raw = f"{fecha or ''}|{id_externo}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    if len(cursor) > 512:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cursor demasiado largo.",
        )
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + padding).decode()
        fecha, id_externo = raw.split("|", 1)
        return fecha, id_externo
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cursor inválido.",
        ) from exc


# ── ETag helpers ──────────────────────────────────────────────────────────


def _make_etag(data: dict[str, Any]) -> str:
    """Genera un ETag débil basado en hash MD5 del contenido."""
    content = str(sorted(data.items()))
    return f'W/"{hashlib.md5(content.encode()).hexdigest()}"'  # noqa: S324


def _check_etag(request: Request, etag: str) -> bool:
    """True si el cliente envió If-None-Match que coincide."""
    client_etag = request.headers.get("If-None-Match", "")
    return client_etag == etag


# ── SAPClassifier singleton ───────────────────────────────────────────────

_classifier_cache: Any = None
_classifier_lock_val = False


def _get_classifier() -> Any:
    """Carga SAPClassifier una sola vez (singleton lazy thread-safe)."""
    global _classifier_cache
    if _classifier_cache is None:
        from scraper.ml_classifier import SAPClassifier

        _classifier_cache = SAPClassifier.load()
    return _classifier_cache


# ── /licitaciones (offset pagination — marcado deprecated) ───────────────


@router.get(
    "/licitaciones",
    response_model=PaginatedResponse[LicitacionSummary],
    summary="Listado paginado de licitaciones (offset)",
    responses={
        200: {"description": "Lista de licitaciones"},
        401: {"description": "API key inválida"},
        422: {"description": "Parámetros inválidos"},
    },
)
async def list_licitaciones(
    request: Request,
    response: Response,
    q: str | None = Query(
        None, max_length=_MAX_QUERY_LENGTH, description="Búsqueda en título y descripción"
    ),
    estado: str | None = Query(None, description="Código de estado (PUB, EV, ADJ…)"),
    ccaa: str | None = Query(None, description="Comunidad Autónoma"),
    tecnologia: str | None = Query(None, description="Tecnología (SAP, ORACLE…)"),
    tecnologia_predicha: str | None = Query(
        None,
        description=(
            "Filtra por tecnología predicha por el clasificador multi-label "
            "(ml_tech_principal o cualquiera en ml_tecnologias). Combinable "
            "con min_proba_tech para usar la tabla licitacion_tecnologia_score."
        ),
    ),
    min_proba_tech: float | None = Query(
        None,
        ge=0.0,
        le=1.0,
        description=(
            "Si se especifica junto con tecnologia_predicha, sólo devuelve "
            "licitaciones cuyo score para esa tecnología es >= este umbral."
        ),
    ),
    fecha_desde: str | None = Query(None, description="Fecha publicación desde (YYYY-MM-DD)"),
    fecha_hasta: str | None = Query(None, description="Fecha publicación hasta (YYYY-MM-DD)"),
    sort: str | None = Query(
        None, description="Orden: fecha_publicacion (default), -importe, importe, titulo"
    ),
    with_total: bool = Query(
        True, description="Incluir total (false = más rápido para paginación)"
    ),
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> PaginatedResponse[LicitacionSummary]:
    """Devuelve lista paginada con filtros opcionales.

    > **Deprecation notice**: Se recomienda usar `/licitaciones/cursor` para
    > datasets grandes. La paginación offset se mantendrá pero quedará marcada
    > como legacy en futuras versiones.
    """
    _validate_query(q)
    _validate_date(fecha_desde, "fecha_desde")
    _validate_date(fecha_hasta, "fecha_hasta")

    # Cabecera de deprecación
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = '</api/v1/licitaciones/cursor>; rel="successor-version"'

    items, total = await run_db(
        _lic_repo.list_paginated,
        q=q,
        estado=estado,
        ccaa=ccaa,
        tecnologia=tecnologia,
        tecnologia_predicha=tecnologia_predicha,
        min_proba_tech=min_proba_tech,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        limit=limit,
        offset=offset,
        sort=sort,
        with_total=with_total,
    )

    if not with_total:
        total = -1

    # Last-Modified
    last_mod = await run_db(_lic_repo.get_last_extraction_date)
    if last_mod:
        response.headers["Last-Modified"] = last_mod

    return PaginatedResponse[LicitacionSummary](
        total=total,
        limit=limit,
        offset=offset,
        items=[LicitacionSummary.model_validate(d) for d in items],
        deprecation_notice="Usa /licitaciones/cursor para datasets grandes.",
    )


# ── /licitaciones/cursor ──────────────────────────────────────────────────


@router.get(
    "/licitaciones/cursor",
    response_model=CursorPaginatedResponse[LicitacionSummary],
    summary="Listado con paginación por cursor (recomendado)",
    responses={
        400: {"description": "Cursor inválido"},
        401: {"description": "API key inválida"},
    },
)
async def list_licitaciones_cursor(
    cursor: str | None = Query(None, description="Cursor opaco devuelto en la página anterior"),
    limit: int = Query(100, ge=1, le=_MAX_LIMIT),
    tecnologia: str | None = Query(None, description="Tecnología (SAP, ORACLE…)"),
    _ctx: AuthContext = Depends(require_api_key),
) -> CursorPaginatedResponse[LicitacionSummary]:
    """Paginación estable por cursor (fecha_publicacion, id_externo).

    Más eficiente que offset: no requiere COUNT(*) y no se ve afectado
    por inserciones concurrentes.
    """
    cursor_fecha: str | None = None
    cursor_id: str | None = None
    if cursor:
        cursor_fecha, cursor_id = _decode_cursor(cursor)

    items = await run_db(
        _lic_repo.list_cursor,
        cursor_fecha=cursor_fecha,
        cursor_id=cursor_id,
        tecnologia=tecnologia,
        limit=limit,
    )

    has_more = len(items) > limit
    if has_more:
        items = items[:limit]

    next_cursor: str | None = None
    if has_more and items:
        last = items[-1]
        next_cursor = _encode_cursor(last.get("fecha_publicacion"), last["id_externo"])

    return CursorPaginatedResponse[LicitacionSummary](
        items=[LicitacionSummary.model_validate(d) for d in items],
        next_cursor=next_cursor,
        has_more=has_more,
        limit=limit,
    )


# ── /licitaciones/search (POST — búsqueda avanzada) ──────────────────────


class SearchRequest(BaseModel):
    q: str | None = Field(None, max_length=_MAX_QUERY_LENGTH)
    estado: list[str] | None = None
    ccaa: list[str] | None = Field(None, max_length=50)
    tecnologia: list[str] | None = Field(None, max_length=20)
    importe_min: float | None = Field(None, ge=0)
    importe_max: float | None = Field(None, ge=0)
    fecha_desde: str | None = None
    fecha_hasta: str | None = None
    sort: str | None = None
    limit: int = Field(50, ge=1, le=_MAX_LIMIT)
    offset: int = Field(0, ge=0)
    with_total: bool = True


@router.post(
    "/licitaciones/search",
    response_model=PaginatedResponse[LicitacionSummary],
    summary="Búsqueda avanzada de licitaciones (POST)",
    responses={401: {"description": "API key inválida"}, 422: {"description": "Body inválido"}},
)
async def search_licitaciones(
    body: SearchRequest,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> PaginatedResponse[LicitacionSummary]:
    """Búsqueda con criterios complejos que no caben en query string.

    Soporta múltiples CCAA, múltiples tecnologías y rangos de importe.
    """
    from services.licitaciones import search_advanced

    limit = max(1, min(body.limit, _MAX_LIMIT))
    offset = max(0, body.offset)

    def _run() -> tuple[list[dict[str, Any]], int]:
        return search_advanced(
            q=body.q,
            estado=body.estado,
            ccaa=body.ccaa,
            tecnologia=body.tecnologia,
            importe_min=body.importe_min,
            importe_max=body.importe_max,
            fecha_desde=body.fecha_desde,
            fecha_hasta=body.fecha_hasta,
            sort=body.sort,
            limit=limit,
            offset=offset,
            with_total=body.with_total,
        )

    items, total = await run_db(_run)

    return PaginatedResponse[LicitacionSummary](
        total=total,
        limit=limit,
        offset=offset,
        items=[LicitacionSummary.model_validate(d) for d in items],
    )


# ── /licitaciones/{id_externo} ────────────────────────────────────────────


@router.get(
    "/licitaciones/{id_externo}",
    response_model=LicitacionDetail,
    summary="Detalle de una licitación",
    responses={
        200: {"description": "Detalle completo"},
        304: {"description": "Not Modified (ETag coincide)"},
        401: {"description": "API key inválida"},
        404: {"description": "No encontrado"},
    },
)
async def get_licitacion(
    id_externo: str,
    request: Request,
    response: Response,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> Any:
    """Devuelve todos los campos de una licitación por su ID externo.

    Soporta caching via ETag / If-None-Match.
    """
    data = await run_db(_lic_repo.get_by_id, id_externo)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado.")

    etag = _make_etag(data)
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=60"

    if _check_etag(request, etag):
        return Response(status_code=304)

    return LicitacionDetail(**{k: data.get(k) for k in LicitacionDetail.model_fields})  # type: ignore[arg-type]


# ── /licitaciones/{id_externo}/explain ───────────────────────────────────


@router.get(
    "/licitaciones/{id_externo}/explain",
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
    _ctx: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    """Devuelve los top-K términos que más influyen en la clasificación."""
    result = await run_db(_lic_repo.get_text_for_ml, id_externo)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontrado.")

    titulo, descripcion, tecnologia = result
    text = f"{titulo} {descripcion}".strip()
    if not text:
        return {
            "id_externo": id_externo,
            "tecnologia": tecnologia,
            "explanation": None,
            "warning": "Texto vacío.",
        }

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
        log.warning("explain_failed", id_externo=id_externo, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error generando explicación.",
        ) from exc

    return {
        "id_externo": id_externo,
        "tecnologia": tecnologia,
        "explanation": explanation,
    }


@router.get(
    "/licitaciones/{id_externo}/tech-scores",
    summary="Scores multi-tecnología del clasificador (ML_TECH)",
    responses={
        401: {"description": "API key inválida"},
        404: {"description": "No encontrado o sin scores"},
    },
)
async def get_tech_scores(
    id_externo: str,
    _ctx: AuthContext = Depends(require_api_key),
) -> dict[str, Any]:
    """Devuelve los scores por tecnología desde ``licitacion_tecnologia_score``.

    Cada item incluye ``tecnologia``, ``probabilidad``, ``threshold_aplicado`` y
    ``computed_at``. Lista vacía si la licitación aún no ha sido puntuada por
    el clasificador multi-label (p. ej., ``ML_TECH_ENABLED=False`` o el job
    ``precompute_ml_tecnologias`` no se ha ejecutado todavía).
    """
    scores = await run_db(_lic_repo.tech_scores_for, id_externo)
    return {"id_externo": id_externo, "scores": scores}


# ── /adjudicaciones ───────────────────────────────────────────────────────


@router.get(
    "/adjudicaciones",
    response_model=PaginatedResponse[AdjudicacionSummary],
    summary="Listado paginado de adjudicaciones",
    responses={
        401: {"description": "API key inválida"},
        422: {"description": "Parámetros inválidos"},
    },
)
async def list_adjudicaciones(
    licitacion_id: str | None = Query(None, description="Filtrar por ID de licitación"),
    ccaa: str | None = Query(None, description="Comunidad Autónoma de la empresa"),
    fecha_desde: str | None = Query(None, description="Fecha adjudicación desde"),
    fecha_hasta: str | None = Query(None, description="Fecha adjudicación hasta"),
    with_total: bool = Query(True, description="Incluir total"),
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> PaginatedResponse[AdjudicacionSummary]:
    """Devuelve lista paginada de adjudicaciones."""
    _validate_date(fecha_desde, "fecha_desde")
    _validate_date(fecha_hasta, "fecha_hasta")

    items, total = await run_db(
        _adj_repo.list_paginated,
        licitacion_id=licitacion_id,
        ccaa=ccaa,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        limit=limit,
        offset=offset,
        with_total=with_total,
    )

    return PaginatedResponse[AdjudicacionSummary](
        total=total,
        limit=limit,
        offset=offset,
        items=[AdjudicacionSummary.model_validate(d) for d in items],
    )


# ── POST /licitaciones/bulk-get ───────────────────────────────────────────


class BulkGetRequest(BaseModel):
    ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Lista de id_externo a recuperar (máx. 100).",
        examples=[["EXP-2024-001", "EXP-2024-002"]],
    )


@router.post(
    "/licitaciones/bulk-get",
    summary="Recuperar múltiples licitaciones por ID en una sola request",
    response_model=None,
    responses={
        200: {
            "description": "Lista de licitaciones encontradas (los IDs no encontrados se omiten)"
        },
        401: {"description": "API key inválida"},
        422: {"description": "Parámetros inválidos"},
    },
)
async def bulk_get_licitaciones(
    body: BulkGetRequest,
    response: Response,
    format: str = Query("json", description="Formato de respuesta: json | csv"),
    _ctx: AuthContext = Depends(require_api_key),
) -> dict[str, Any] | StreamingResponse:
    """Recupera hasta 100 licitaciones por ``id_externo`` en una sola request.

    Útil para clientes que necesitan hidratar listas de IDs sin hacer N requests
    individuales. Los IDs no encontrados se omiten silenciosamente.

    Con ``?format=csv`` devuelve un CSV descargable.
    """
    # Deduplicar preservando orden
    seen: set[str] = set()
    ids = [id_ for id_ in body.ids if id_ not in seen and not seen.add(id_)]  # type: ignore[func-returns-value]

    items = await run_db(_lic_repo.get_by_ids, ids)

    if format == "csv":
        import csv
        import io

        def _generate_csv() -> Generator[str, None, None]:
            if not items:
                yield "id_externo,titulo,organo_contratacion,importe,estado,fecha_publicacion,ccaa,cpv,url,tecnologia\n"
                return
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=list(items[0].keys()))
            writer.writeheader()
            for row in items:
                writer.writerow(row)
            yield output.getvalue()

        response.headers["Content-Disposition"] = "attachment; filename=licitaciones_bulk.csv"
        return StreamingResponse(
            _generate_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=licitaciones_bulk.csv"},
        )

    return {"items": items, "count": len(items), "requested": len(ids)}
