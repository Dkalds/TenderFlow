"""Búsqueda de texto — POST /api/v1/search/semantic.

Expone el motor FTS+BM25 de :mod:`services.investigador.search_engine` como
endpoint REST público (requiere API-key).

Diseño
------
* Full-text search de Postgres (``tsvector``/``ts_rank_cd``; los nombres
  ``fts5_*`` sobreviven por compatibilidad de contrato) con fallback LIKE.
* FAISS se retiró en la Fase 3 de reducción de superficie (2026-07-04); la
  ruta conserva su path público y los campos ``alpha``/``embedding_model``
  por compatibilidad de contrato, pero ya no hay reranking semántico.
* ``run_ml`` aísla la latencia en el pool de ML (bulkhead 2 slots).

Ejemplo::

    curl -X POST /api/v1/search/semantic \\
         -H "X-API-Key: sk-..." \\
         -H "Content-Type: application/json" \\
         -d '{"q": "SAP S/4HANA consultoría", "top_k": 5}'
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from api.concurrency import run_db, run_ml
from api.routes.dual_auth import require_any_auth
from db.repositories.licitaciones import LicitacionRepository
from observability.logging import get_logger
from services.busqueda_global import BusquedaGlobal, buscar_global

log = get_logger(__name__)

router = APIRouter(tags=["search"])

_repo = LicitacionRepository()

_MAX_Q_LEN = 500
_DEFAULT_TOP_K = 10
_MAX_TOP_K = 50


# ── Schemas ──────────────────────────────────────────────────────────────────


class SemanticSearchRequest(BaseModel):
    """Cuerpo de la petición de búsqueda semántica."""

    q: str = Field(
        ..., min_length=1, max_length=_MAX_Q_LEN, description="Consulta en lenguaje natural"
    )
    top_k: int = Field(
        default=_DEFAULT_TOP_K, ge=1, le=_MAX_TOP_K, description="Número máximo de resultados"
    )
    alpha: float = Field(
        default=0.70,
        ge=0.0,
        le=1.0,
        description="LEGACY — sin efecto desde la retirada de FAISS (2026-07); se acepta por compatibilidad",
    )
    embedding_model: str = Field(
        default="",
        max_length=200,
        description="LEGACY — sin efecto desde la retirada de FAISS (2026-07); se acepta por compatibilidad",
    )
    ccaa: list[str] = Field(
        default_factory=list, description="Filtra resultados por CCAA (multi-valor)"
    )
    tecnologia: list[str] = Field(
        default_factory=list, description="Filtra resultados por tecnología (multi-valor)"
    )
    fecha_desde: str | None = Field(
        default=None, description="Fecha de publicación desde (YYYY-MM-DD)"
    )
    fecha_hasta: str | None = Field(
        default=None, description="Fecha de publicación hasta (YYYY-MM-DD)"
    )

    @field_validator("q", "ccaa", "tecnologia", "fecha_desde", "fecha_hasta")
    @classmethod
    def _sin_bytes_nul(cls, value: str | list[str] | None) -> str | list[str] | None:
        """Postgres rechaza NUL (0x00) en campos de texto con un ``DataError``
        que llegaba al cliente como 5xx (lo encontró el fuzzing de contrato).
        Se rechaza como 422 en vez de sanearse en silencio: un NUL en una
        consulta nunca es intención de usuario, es un input malformado."""
        if value is None:
            return value
        values = value if isinstance(value, list) else [value]
        if any("\x00" in item for item in values):
            raise ValueError("El texto no puede contener bytes NUL (0x00).")
        return value


class SemanticHit(BaseModel):
    """Un resultado de búsqueda semántica."""

    id_externo: str
    titulo: str | None
    organo_contratacion: str | None
    importe: float | None
    descripcion: str | None
    url: str | None
    fecha_publicacion: str | None
    ccaa: str | None
    estado: str | None
    score: float = Field(description="Puntuación de relevancia combinada [0, 1]")


class SemanticSearchResponse(BaseModel):
    """Respuesta de búsqueda semántica."""

    q: str
    top_k: int
    source: str = Field(description="Motor usado: FTS5 | LIKE")
    hits: list[SemanticHit]
    elapsed_ms: int


# ── Endpoint ─────────────────────────────────────────────────────────────────


@router.post(
    "/search/semantic",
    response_model=SemanticSearchResponse,
    summary="Búsqueda de texto completo (FTS/BM25)",
    description=(
        "Ejecuta una búsqueda de texto completo (Postgres tsvector/ts_rank_cd) "
        "con fallback LIKE. Los campos alpha/embedding_model son legacy sin "
        "efecto desde la retirada de FAISS (2026-07)."
    ),
)
async def semantic_search(
    body: SemanticSearchRequest,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> SemanticSearchResponse:
    """Búsqueda semántica híbrida."""
    import time

    t0 = time.perf_counter()

    # Filtros activos → restringir los hits a esos ids (allowed_ids). El backend
    # es la fuente del filtrado; el frontend no finge ni manda solo el primer valor.
    allowed_ids: set[str] | None = None
    if body.ccaa or body.tecnologia or body.fecha_desde or body.fecha_hasta:
        allowed_ids = await run_db(
            lambda: _repo.ids_for_filters(
                ccaa=body.ccaa or None,
                tecnologia=body.tecnologia or None,
                fecha_desde=body.fecha_desde,
                fecha_hasta=body.fecha_hasta,
            )
        )

    def _run() -> tuple[list[dict[str, Any]], str]:
        from services.investigador.search_engine import (
            fetch_docs,
            fts5_search,
            like_search,
        )

        # Con filtros activos ampliamos el pool de candidatos y filtramos ANTES de
        # recortar a top_k, para no quedarnos cortos de resultados tras el filtro.
        pool = min(body.top_k * (10 if allowed_ids is not None else 2), 200)
        fts_hits = fts5_search(body.q, pool)

        if fts_hits:
            ranked = sorted(fts_hits, key=lambda x: x[1], reverse=True)[:pool]
            source = "FTS5"
        else:
            ranked = like_search(body.q, pool)
            source = "LIKE"

        if allowed_ids is not None:
            ranked = [(id_, sc) for id_, sc in ranked if id_ in allowed_ids]
        ranked = ranked[: body.top_k]

        ids = [id_ for id_, _ in ranked]
        docs_map = fetch_docs(ids)

        hits: list[dict[str, Any]] = []
        for id_, score in ranked:
            if id_ in docs_map:
                doc = dict(docs_map[id_])
                doc["score"] = round(score, 6)
                hits.append(doc)

        return hits, source

    try:
        hits, source = await run_ml(_run)
    except Exception as exc:
        log.error("semantic_search.failed", error=str(exc), q=body.q[:80])
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servicio de búsqueda semántica no está disponible temporalmente.",
        ) from exc

    elapsed_ms = round((time.perf_counter() - t0) * 1000)

    log.info(
        "semantic_search.ok",
        q=body.q[:80],
        n=len(hits),
        source=source,
        elapsed_ms=elapsed_ms,
        user=ctx.get("user_id"),
    )

    return SemanticSearchResponse(
        q=body.q,
        top_k=body.top_k,
        source=source,
        hits=[SemanticHit(**h) for h in hits],
        elapsed_ms=elapsed_ms,
    )


@router.get(
    "/search/global",
    summary="Búsqueda unificada para la paleta: expedientes, empresas, órganos y oportunidades",
    responses={401: {"description": "Autenticación inválida"}},
)
async def get_search_global(
    q: str = Query(..., max_length=_MAX_Q_LEN, description="Término de búsqueda"),
    organization_id: int | None = Query(
        default=None,
        ge=1,
        description=(
            "Sin él **no se buscan oportunidades**, que no es lo mismo que no "
            "encontrar ninguna: la respuesta lo declara en `tipos_buscados`."
        ),
    ),
    limit: int = Query(5, ge=1, le=20, description="Máximo por tipo"),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> BusquedaGlobal:
    """F1.2 — un término, cuatro clases de resultado.

    Un término demasiado corto devuelve 200 con `sin_busqueda`, no un 422: la
    paleta consulta en cada tecla y un error por escribir dos letras sería un
    error en la mitad de las pulsaciones.
    """
    return await run_db(buscar_global, q, organization_id=organization_id, limite_por_tipo=limit)
