"""Rutas /api/v1/licitaciones y /api/v1/adjudicaciones."""

from __future__ import annotations

import base64
import hashlib
import re
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
from db.repositories.adjudicaciones import AdjudicacionRepository
from db.repositories.licitaciones import LicitacionRepository
from observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["licitaciones"])

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_LIMIT = 500

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


T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    total: int
    limit: int
    offset: int
    items: list[T]
    deprecation_notice: str | None = None


class CursorPaginatedResponse(BaseModel, Generic[T]):
    """Respuesta con paginación por cursor (recomendada para datasets grandes)."""

    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False
    limit: int


# ── Cursor helpers ────────────────────────────────────────────────────────


def _encode_cursor(fecha: str | None, id_externo: str) -> str:
    raw = f"{fecha or ''}|{id_externo}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
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
    q: str | None = Query(None, description="Búsqueda en título y descripción"),
    estado: str | None = Query(None, description="Código de estado (PUB, EV, ADJ…)"),
    ccaa: str | None = Query(None, description="Comunidad Autónoma"),
    tecnologia: str | None = Query(None, description="Tecnología (SAP, ORACLE…)"),
    fecha_desde: str | None = Query(None, description="Fecha publicación desde (YYYY-MM-DD)"),
    fecha_hasta: str | None = Query(None, description="Fecha publicación hasta (YYYY-MM-DD)"),
    sort: str | None = Query(None, description="Orden: fecha_publicacion (default), -importe, importe, titulo"),
    with_total: bool = Query(True, description="Incluir total (false = más rápido para paginación)"),
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    _ctx: AuthContext = Depends(require_api_key),
) -> PaginatedResponse[LicitacionSummary]:
    """Devuelve lista paginada con filtros opcionales.

    > **Deprecation notice**: Se recomienda usar `/licitaciones/cursor` para
    > datasets grandes. La paginación offset se mantendrá pero quedará marcada
    > como legacy en futuras versiones.
    """
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
        items=items,
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
        items=items,
        next_cursor=next_cursor,
        has_more=has_more,
        limit=limit,
    )


# ── /licitaciones/search (POST — búsqueda avanzada) ──────────────────────


class SearchRequest(BaseModel):
    q: str | None = None
    estado: list[str] | None = None
    ccaa: list[str] | None = None
    tecnologia: list[str] | None = None
    importe_min: float | None = None
    importe_max: float | None = None
    fecha_desde: str | None = None
    fecha_hasta: str | None = None
    sort: str | None = None
    limit: int = 50
    offset: int = 0
    with_total: bool = True


@router.post(
    "/licitaciones/search",
    response_model=PaginatedResponse[LicitacionSummary],
    summary="Búsqueda avanzada de licitaciones (POST)",
    responses={401: {"description": "API key inválida"}, 422: {"description": "Body inválido"}},
)
async def search_licitaciones(
    body: SearchRequest,
    _ctx: AuthContext = Depends(require_api_key),
) -> PaginatedResponse[LicitacionSummary]:
    """Búsqueda con criterios complejos que no caben en query string.

    Soporta múltiples CCAA, múltiples tecnologías y rangos de importe.
    """
    from db.database import connect_read
    from db.repositories.base import count_where, rows_to_dicts

    conditions: list[str] = ["tecnologia IS NOT NULL AND tecnologia != ''"]
    params: list[Any] = []

    if body.q:
        conditions.append("(titulo LIKE ? OR descripcion LIKE ?)")
        like = f"%{body.q}%"
        params.extend([like, like])
    if body.estado:
        placeholders = ",".join("?" for _ in body.estado)
        conditions.append(f"estado IN ({placeholders})")
        params.extend(body.estado)
    if body.ccaa:
        placeholders = ",".join("?" for _ in body.ccaa)
        conditions.append(f"ccaa IN ({placeholders})")
        params.extend(body.ccaa)
    if body.tecnologia:
        placeholders = ",".join("?" for _ in body.tecnologia)
        conditions.append(f"tecnologia IN ({placeholders})")
        params.extend(body.tecnologia)
    if body.importe_min is not None:
        conditions.append("importe >= ?")
        params.append(body.importe_min)
    if body.importe_max is not None:
        conditions.append("importe <= ?")
        params.append(body.importe_max)
    if body.fecha_desde and _DATE_RE.match(body.fecha_desde):
        conditions.append("fecha_publicacion >= ?")
        params.append(body.fecha_desde)
    if body.fecha_hasta and _DATE_RE.match(body.fecha_hasta):
        conditions.append("fecha_publicacion <= ?")
        params.append(body.fecha_hasta)

    from db.repositories.licitaciones import _DEFAULT_SORT, _SORT_WHITELIST, _SUMMARY_COLS
    order = _SORT_WHITELIST.get(body.sort or "", _DEFAULT_SORT)
    where = " AND ".join(conditions)

    limit = max(1, min(body.limit, _MAX_LIMIT))
    offset = max(0, body.offset)

    def _run() -> tuple[list[dict[str, Any]], int]:
        with connect_read() as c:
            total = count_where(c, "licitaciones", where, tuple(params)) if body.with_total else -1
            sql = f"SELECT {_SUMMARY_COLS} FROM licitaciones"  # noqa: S608
            if where:
                sql += f" WHERE {where}"
            sql += f" ORDER BY {order} LIMIT ? OFFSET ?"
            q_params = [*list(params), limit, offset]
            items = rows_to_dicts(c.execute(sql, tuple(q_params)))
        return items, total

    items, total = await run_db(_run)

    return PaginatedResponse[LicitacionSummary](
        total=total,
        limit=limit,
        offset=offset,
        items=items,
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
    _ctx: AuthContext = Depends(require_api_key),
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

    return LicitacionDetail(**{k: data.get(k) for k in LicitacionDetail.model_fields})


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
    _ctx: AuthContext = Depends(require_api_key),
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
        items=items,
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
    responses={
        200: {"description": "Lista de licitaciones encontradas (los IDs no encontrados se omiten)"},
        401: {"description": "API key inválida"},
        422: {"description": "Parámetros inválidos"},
    },
)
async def bulk_get_licitaciones(
    body: BulkGetRequest,
    response: Response,
    format: str = Query("json", description="Formato de respuesta: json | csv"),
    _ctx: AuthContext = Depends(require_api_key),
):
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

        def _generate_csv():
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
