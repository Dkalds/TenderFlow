"""Rutas /api/v1/licitaciones y /api/v1/adjudicaciones."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Generator
from typing import Any

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
from db.repositories.documentos import DocumentosRepository
from db.repositories.licitaciones import LicitacionRepository
from observability.logging import get_logger
from shared.dto import (
    MAX_PAGE_LIMIT,
    CursorPaginatedResponse,
    PaginatedResponse,
    SafeStr,
)
from shared.export_safety import sanitize_spreadsheet_record
from shared.tender_facts import EvidenceRef, TenderFactSheetRecord

log = get_logger(__name__)

router = APIRouter(tags=["licitaciones"])

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_QUERY_LENGTH = 200

# Singletons — instanciados una vez
_lic_repo = LicitacionRepository()
_adj_repo = AdjudicacionRepository()
_doc_repo = DocumentosRepository()


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
    # La fecha límite decide la urgencia de una licitación: sin ella un listado
    # no puede ordenar por cierre ni avisar de un plazo que se agota.
    fecha_limite: str | None = None
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
    fecha_inicio: str | None = None
    fecha_fin: str | None = None
    raw_keywords: str | None = None
    fecha_extraccion: str | None = None
    # Fuente de ingesta (ADR-009): 'placsp', 'ted', 'pscp', 'euskadi_rss'… La
    # ficha etiquetaba su enlace externo como «Ver en PLACSP» pasara lo que
    # pasara, y con TED/PSCP/Euskadi el `url` no lleva a PLACSP: el texto
    # mentía. Sin este campo el frontend no tiene de dónde sacar la etiqueta —
    # `id_externo` no sirve, porque PLACSP es el legacy sin namespace.
    fuente: str | None = None


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


class DocumentoSummary(BaseModel):
    id: int
    tipo: str
    uri: str
    filename: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    status: str
    created_at: str | None = None


# `PaginatedResponse` y `CursorPaginatedResponse` viven en `shared/dto.py`
# (contrato de paginación común del API). Se importan arriba: la forma que
# estas rutas ya usaban es la que ahora comparten las demás.


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
    """Genera un ETag débil basado en SHA-256 del contenido."""
    content = str(sorted(data.items()))
    return f'W/"{hashlib.sha256(content.encode()).hexdigest()}"'


def _check_etag(request: Request, etag: str) -> bool:
    """True si el cliente envió If-None-Match que coincide."""
    client_etag = request.headers.get("If-None-Match", "")
    return client_etag == etag


# ── SAPClassifier singleton ───────────────────────────────────────────────


def _get_classifier() -> Any:
    """Devuelve el SAPClassifier activo (caché de proceso con lock y TTL).

    La caché vive en ``api.model_cache`` para que ``/models/{name}/activate``
    pueda invalidarla sin importar esta ruta.
    """
    from api.model_cache import get_classifier

    return get_classifier()


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

    # Cabecera de deprecación
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = '</api/v1/licitaciones/cursor>; rel="successor-version"'

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
    _ctx: AuthContext = Depends(require_api_key),
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


# ── /licitaciones/{id_externo}/documentos ─────────────────────────────────


class DocumentosResult(BaseModel):
    """Adjuntos (pliegos) de una licitación, sin el texto extraído."""

    id_externo: str
    items: list[DocumentoSummary]


@router.get(
    "/licitaciones/{id_externo:path}/documentos",
    summary="Documentos (pliegos) referenciados por una licitación",
    responses={401: {"description": "API key inválida"}},
)
async def get_documentos(
    id_externo: str,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> DocumentosResult:
    """Metadatos de los adjuntos (pliegos) parseados del CODICE/UBL para esta
    licitación — sin el texto extraído, que solo usa internamente el pipeline
    RAG ("Preguntar al copilot"). Lista vacía si aún no se procesó ningún
    documento (no todas las fuentes/licitaciones tienen adjuntos parseados).
    """
    items = await run_db(_doc_repo.list_by_licitacion, id_externo)
    return DocumentosResult(
        id_externo=id_externo,
        items=[DocumentoSummary.model_validate(d) for d in items],
    )


@router.get(
    "/licitaciones/{id_externo:path}/ficha-pliego",
    response_model=TenderFactSheetRecord,
    summary="Ficha estructurada y citable de los pliegos",
    responses={
        401: {"description": "Autenticación inválida"},
        404: {"description": "Ficha todavía no disponible"},
    },
)
async def get_tender_fact_sheet(
    id_externo: str,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> TenderFactSheetRecord:
    """Lee la extracción vigente sin invocar al proveedor LLM."""
    from services.rag.fact_sheet import get_fact_sheet

    record = await run_db(get_fact_sheet, id_externo)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La ficha del pliego todavía no está disponible.",
        )
    return record


@router.post(
    "/licitaciones/{id_externo:path}/ficha-pliego/extract",
    response_model=TenderFactSheetRecord,
    summary="Extraer o reprocesar la ficha estructurada",
    responses={
        401: {"description": "Autenticación inválida"},
        422: {"description": "Sin texto de pliegos disponible (ni descargable ahora)"},
        502: {"description": "El proveedor no devolvió una ficha válida"},
    },
)
async def extract_tender_fact_sheet(
    id_externo: str,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> TenderFactSheetRecord:
    """Reextracción explícita; descarga bajo demanda los pliegos que aún
    estén pendientes (el cron nocturno drena el backlog global por lotes y
    esta licitación puede no haber tocado turno) y valida toda cita antes de
    persistirla."""
    from config import settings
    from services.rag.fact_sheet import extract_fact_sheet_on_demand
    from services.tech_signal import ingest_llm_technologies

    try:
        record = await run_db(
            extract_fact_sheet_on_demand,
            id_externo,
            model=settings.PLIEGO_FACTS_MODEL,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        log.warning("tender_fact_sheet_extract_failed", id_externo=id_externo, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo extraer una ficha verificable del pliego.",
        ) from exc

    try:
        await run_db(ingest_llm_technologies, record)
    except Exception as exc:
        # La ficha ya se persistió y es lo que la ruta promete devolver; un
        # fallo al ingerir la señal de tecnología no debe convertir una
        # extracción exitosa en un 502.
        log.warning("tender_fact_sheet_tech_ingest_failed", id_externo=id_externo, error=str(exc))

    return record


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
    _ctx: AuthContext = Depends(require_api_key),
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
    limit: int = Query(50, ge=1, le=MAX_PAGE_LIMIT),
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
    _ctx: AuthContext = Depends(require_api_key),
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
