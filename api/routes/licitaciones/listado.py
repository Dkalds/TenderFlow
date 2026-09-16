"""Familia **listado**: cómo se obtienen muchos expedientes a la vez.

``GET /licitaciones`` (offset, en sunset), ``GET /licitaciones/cursor``,
``POST /licitaciones/search`` y ``POST /licitaciones/bulk-get``. Lo que las
une no es el verbo: es que ninguna direcciona un expediente concreto, así que
ninguna lleva ``{id_externo}`` y todas devuelven un envoltorio paginado.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    Query,
    Request,
    Response,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.errors import deprecate_route
from api.routes.dual_auth import require_any_auth
from api.routes.licitaciones._base import (
    _MAX_QUERY_LENGTH,
    SUNSET_LISTADO_POR_OFFSET,
    _decode_cursor,
    _encode_cursor,
    _lic_repo,
    _validate_date,
    _validate_query,
)
from api.routes.licitaciones.modelos import (
    LicitacionSummary,
)
from observability.logging import get_logger
from shared.dto import (
    MAX_PAGE_LIMIT,
    CursorPaginatedResponse,
    PaginatedResponse,
    SafeStr,
)
from shared.export_safety import sanitize_spreadsheet_record

log = get_logger(__name__)

router = APIRouter(tags=["licitaciones"])


# ── /licitaciones (offset pagination — marcado deprecated) ───────────────


@router.get(
    "/licitaciones",
    response_model=PaginatedResponse[LicitacionSummary],
    summary="[DEPRECADO 2026-12-04] Listado paginado de licitaciones (offset)",
    deprecated=True,
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
    solo_abiertas: bool = Query(
        False,
        description=(
            "Excluye los expedientes en estado terminal (RES, ADJ, ANUL). "
            "Lo usan las superficies de oportunidad —el Radar— para no "
            "proponer licitaciones que ya no se pueden licitar."
        ),
    ),
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
    cierre_desde: str | None = Query(
        None,
        description=(
            "Fecha límite de presentación desde (YYYY-MM-DD). Eje distinto de "
            "fecha_desde/fecha_hasta, que acotan publicación: éste acota el "
            "cierre. Lo pide cualquier superficie que cuente plazos —la tarjeta "
            "«Vencen 48h» de /resumen— para poder abrir el listado que enseña "
            "justo lo que cuenta. Los expedientes sin plazo publicado quedan "
            "fuera en cuanto se usa cualquiera de las dos cotas."
        ),
    ),
    cierre_hasta: str | None = Query(
        None,
        description=(
            "Fecha límite de presentación hasta (YYYY-MM-DD), inclusive el día "
            "entero: fecha_limite guarda la hora de cierre, así que la cota "
            "incluye los expedientes que cierran ese mismo día a cualquier hora."
        ),
    ),
    importe_min: float | None = Query(
        None, ge=0, description="Importe de licitación mínimo, en euros (inclusive)"
    ),
    importe_max: float | None = Query(
        None, ge=0, description="Importe de licitación máximo, en euros (inclusive)"
    ),
    cpv: str | None = Query(
        None,
        max_length=200,
        description=(
            "CPV por PREFIJO, separados por comas. `72` trae todos los "
            "servicios de TI y `7222` una familia dentro. Es prefijo y no "
            "igualdad porque nadie recuerda los ocho dígitos."
        ),
    ),
    organo: str | None = Query(
        None,
        max_length=300,
        description=(
            "Órgano de contratación por subcadena, sin distinguir acentos ni "
            "mayúsculas. Varios separados por comas."
        ),
    ),
    provincia: str | None = Query(None, max_length=200, description="Provincia (multi-valor)"),
    procedimiento: str | None = Query(
        None,
        max_length=100,
        description=(
            "Código CODICE de procedimiento (multi-valor). Las etiquetas y el "
            "catálogo completo los sirve `GET /meta/filters`."
        ),
    ),
    tramitacion: str | None = Query(
        None, max_length=100, description="Código CODICE de tramitación (multi-valor)"
    ),
    tipo_contrato: str | None = Query(
        None, max_length=100, description="Código CODICE de tipo de contrato (multi-valor)"
    ),
    dias_restantes_max: int | None = Query(
        None,
        ge=0,
        le=3650,
        description=(
            "Sólo expedientes cuyo plazo vence dentro de N días. Se calcula en "
            "SQL sobre `fecha_limite` y excluye los estados terminales: un "
            "expediente ya adjudicado con fecha límite futura no vence, no se "
            "puede licitar."
        ),
    ),
    sort: str | None = Query(
        None, description="Orden: fecha_publicacion (default), -importe, importe, titulo"
    ),
    with_total: bool = Query(
        True, description="Incluir total (false = más rápido para paginación)"
    ),
    limit: int = Query(50, ge=1, le=MAX_PAGE_LIMIT),
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
    _validate_date(cierre_desde, "cierre_desde")
    _validate_date(cierre_hasta, "cierre_hasta")

    # Cabecera de deprecación con fecha de apagado (C8.1). Antes emitía
    # `Deprecation: true` y `Link` pero no `Sunset`: le decía al cliente que se
    # preparase sin decirle para cuándo, que es la mitad inútil del aviso.
    deprecate_route(
        response,
        sunset=SUNSET_LISTADO_POR_OFFSET,
        successor="/api/v1/licitaciones/cursor",
    )

    items, total = await run_db(
        _lic_repo.list_paginated,
        q=q,
        estado=estado,
        solo_abiertas=solo_abiertas,
        ccaa=ccaa,
        tecnologia=tecnologia,
        tecnologia_predicha=tecnologia_predicha,
        min_proba_tech=min_proba_tech,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        cierre_desde=cierre_desde,
        cierre_hasta=cierre_hasta,
        importe_min=importe_min,
        importe_max=importe_max,
        cpv=cpv,
        organo=organo,
        provincia=provincia,
        procedimiento=procedimiento,
        tramitacion=tramitacion,
        tipo_contrato=tipo_contrato,
        dias_restantes_max=dias_restantes_max,
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
    limit: int = Query(100, ge=1, le=MAX_PAGE_LIMIT),
    q: str | None = Query(
        None, max_length=_MAX_QUERY_LENGTH, description="Búsqueda en título y descripción"
    ),
    estado: str | None = Query(None, description="Código de estado (PUB, EV, ADJ…)"),
    solo_abiertas: bool = Query(False, description="Excluye los expedientes en estado terminal"),
    ccaa: str | None = Query(None, description="Comunidad Autónoma"),
    tecnologia: str | None = Query(None, description="Tecnología (SAP, ORACLE…)"),
    fecha_desde: str | None = Query(None, description="Fecha publicación desde (YYYY-MM-DD)"),
    fecha_hasta: str | None = Query(None, description="Fecha publicación hasta (YYYY-MM-DD)"),
    cierre_desde: str | None = Query(None, description="Fecha límite desde (YYYY-MM-DD)"),
    cierre_hasta: str | None = Query(None, description="Fecha límite hasta (YYYY-MM-DD)"),
    importe_min: float | None = Query(None, ge=0, description="Importe mínimo, en euros"),
    importe_max: float | None = Query(None, ge=0, description="Importe máximo, en euros"),
    cpv: str | None = Query(None, max_length=200, description="CPV por prefijo (multi-valor)"),
    organo: str | None = Query(None, max_length=300, description="Órgano por subcadena"),
    provincia: str | None = Query(None, max_length=200, description="Provincia (multi-valor)"),
    procedimiento: str | None = Query(
        None, max_length=100, description="Código CODICE de procedimiento (multi-valor)"
    ),
    tramitacion: str | None = Query(
        None, max_length=100, description="Código CODICE de tramitación (multi-valor)"
    ),
    tipo_contrato: str | None = Query(
        None, max_length=100, description="Código CODICE de tipo de contrato (multi-valor)"
    ),
    dias_restantes_max: int | None = Query(
        None, ge=0, le=3650, description="Plazo que vence dentro de N días"
    ),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> CursorPaginatedResponse[LicitacionSummary]:
    """Paginación estable por cursor (fecha_publicacion, id_externo).

    Más eficiente que offset: no requiere COUNT(*) y no se ve afectado
    por inserciones concurrentes.

    Acepta **los mismos filtros** que `/licitaciones` (F1.1). Hasta ahora sólo
    aceptaba `tecnologia`, de modo que el endpoint recomendado para datasets
    grandes no podía sustituir al que dice reemplazar en cuanto había un filtro
    puesto.
    """
    _validate_query(q)
    _validate_date(fecha_desde, "fecha_desde")
    _validate_date(fecha_hasta, "fecha_hasta")
    _validate_date(cierre_desde, "cierre_desde")
    _validate_date(cierre_hasta, "cierre_hasta")

    cursor_fecha: str | None = None
    cursor_id: str | None = None
    if cursor:
        cursor_fecha, cursor_id = _decode_cursor(cursor)

    items = await run_db(
        _lic_repo.list_cursor,
        cursor_fecha=cursor_fecha,
        cursor_id=cursor_id,
        q=q,
        estado=estado,
        solo_abiertas=solo_abiertas,
        ccaa=ccaa,
        tecnologia=tecnologia,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        cierre_desde=cierre_desde,
        cierre_hasta=cierre_hasta,
        importe_min=importe_min,
        importe_max=importe_max,
        cpv=cpv,
        organo=organo,
        provincia=provincia,
        procedimiento=procedimiento,
        tramitacion=tramitacion,
        tipo_contrato=tipo_contrato,
        dias_restantes_max=dias_restantes_max,
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
    limit: int = Field(50, ge=1, le=MAX_PAGE_LIMIT)
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

    limit = max(1, min(body.limit, MAX_PAGE_LIMIT))
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


# ── POST /licitaciones/bulk-get ───────────────────────────────────────────


class BulkGetResult(BaseModel):
    """Licitaciones encontradas (los IDs no pedidos u omitidos no aparecen)."""

    items: list[LicitacionSummary]
    count: int
    requested: int


class BulkGetRequest(BaseModel):
    # `SafeStr`, no `str`: un \x00 en un id viajaba hasta Postgres y su
    # DataError salía como 500 (KNOWN_5XX del fuzzer).
    ids: list[SafeStr] = Field(
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
            "model": BulkGetResult,
            "description": "Lista de licitaciones encontradas (los IDs no encontrados se omiten)",
        },
        401: {"description": "API key inválida"},
        422: {"description": "Parámetros inválidos"},
    },
)
async def bulk_get_licitaciones(
    body: BulkGetRequest,
    response: Response,
    format: str = Query("json", description="Formato de respuesta: json | csv"),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> BulkGetResult | StreamingResponse:
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
                writer.writerow(sanitize_spreadsheet_record(row))
            yield output.getvalue()

        response.headers["Content-Disposition"] = "attachment; filename=licitaciones_bulk.csv"
        return StreamingResponse(
            _generate_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=licitaciones_bulk.csv"},
        )

    return BulkGetResult(
        items=[LicitacionSummary.model_validate(item) for item in items],
        count=len(items),
        requested=len(ids),
    )
