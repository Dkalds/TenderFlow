"""Búsqueda de texto — POST /api/v1/search/semantic.

Expone el motor de :mod:`services.investigador.search_engine` como endpoint
REST (requiere API-key o sesión).

Diseño
------
* Tres caminos, de más a menos informado: fusión RRF (FTS + pgvector sobre
  ``documento_chunks``), full-text de Postgres (``tsvector``/``ts_rank_cd``;
  los nombres ``fts5_*`` sobreviven por compatibilidad de contrato) y
  fallback LIKE. ``source`` dice cuál se ejecutó de verdad.
* ``alpha`` pondera las dos listas de la fusión (0 = solo léxico, 1 = solo
  semántico). Entre 2026-07 (retirada de FAISS) y 2026-09 fue un campo
  legacy sin efecto, y el deslizador del Investigador que lo enviaba era el
  único control de la UI que el backend ignoraba (D15 del plan de
  arquitectura 2026-09: servir la fusión que ya existía).
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
from api.tenancy import resolve_organization_ctx
from db.repositories.licitaciones import LicitacionRepository
from observability.logging import get_logger
from services.busqueda_global import BusquedaGlobal, buscar_global

log = get_logger(__name__)

router = APIRouter(tags=["search"])

_repo = LicitacionRepository()

_MAX_Q_LEN = 500
_DEFAULT_TOP_K = 10
_MAX_TOP_K = 50

# Valores posibles de ``SemanticSearchResponse.source``, en el orden en que se
# intentan los caminos. Son constantes y no un literal suelto porque el
# Investigador tiene que poder etiquetar los tres sin inventarse un cuarto:
# ``tests/test_search_semantic_source.py`` comprueba que la tabla de etiquetas
# de la UI y esta tupla no se separen.
SOURCE_RRF = "rrf"
SOURCE_FTS = "fts"
SOURCE_LIKE = "like"
SEARCH_SOURCES: tuple[str, ...] = (SOURCE_RRF, SOURCE_FTS, SOURCE_LIKE)


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
        description=(
            "Peso del lado semántico en la fusión RRF: 0 = solo texto completo, "
            "1 = solo similitud vectorial. Solo tiene efecto cuando la respuesta "
            "es source=rrf; con source=fts o like no hay nada que ponderar."
        ),
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
    score: float = Field(
        description=(
            "Relevancia en [0, 1]. La escala DEPENDE de source y no es "
            "comparable entre búsquedas ni entre fuentes: con rrf se escala "
            "contra el mejor resultado de esta misma respuesta, que vale 1; "
            "con fts, contra el mejor candidato del texto completo ANTES de "
            "aplicar los filtros, así que el máximo de la lista puede quedar "
            "por debajo de 1; con like es la constante 0.2 en todos los "
            "resultados, porque la coincidencia literal no ordena por "
            "relevancia."
        )
    )


class SemanticSearchResponse(BaseModel):
    """Respuesta de búsqueda semántica."""

    q: str
    top_k: int
    # Tipado ``str`` y no ``Literal``: el conjunto de valores es cerrado y lo
    # fija ``SEARCH_SOURCES``, pero un Literal en la respuesta convierte
    # cualquier camino futuro en un 500 de validación en producción.
    source: str = Field(
        description=(
            "Camino REALMENTE ejecutado: rrf (fusión de texto completo y "
            "similitud vectorial), fts (solo texto completo) o like "
            "(coincidencia literal). No se declara por configuración."
        )
    )
    hits: list[SemanticHit]
    elapsed_ms: int


# ── Normalización de los hits de la fusión ───────────────────────────────────

# Campos de ``hybrid_search_docs`` que sí viajan al cliente. El resto de lo que
# devuelve (``tecnologia``, ``chunks``) es para el RAG, no para esta ruta.
_HIT_FIELDS = (
    "id_externo",
    "titulo",
    "organo_contratacion",
    "importe",
    "descripcion",
    "url",
    "fecha_publicacion",
    "ccaa",
    "estado",
)


def _hits_from_fused(
    docs: list[dict[str, Any]],
    allowed_ids: set[str] | None,
    top_k: int,
) -> list[dict[str, Any]]:
    """Adapta los documentos de la fusión RRF a la forma de ``SemanticHit``.

    El ``rrf_score`` bruto vive en torno a 1/60 y no tiene techo conocido, así
    que se escala contra el mejor de esta misma respuesta para que el contrato
    ``score ∈ [0, 1]`` se cumpla sin fingir una escala absoluta que no existe:
    la descripción del campo dice que es relativo a la respuesta.
    """
    if allowed_ids is not None:
        docs = [d for d in docs if d.get("id_externo") in allowed_ids]
    docs = docs[:top_k]
    if not docs:
        return []

    max_score = max(float(d.get("rrf_score") or 0.0) for d in docs)
    hits: list[dict[str, Any]] = []
    for doc in docs:
        hit: dict[str, Any] = {k: doc.get(k) for k in _HIT_FIELDS}
        raw = float(doc.get("rrf_score") or 0.0)
        hit["score"] = round(raw / max_score, 6) if max_score > 0 else 0.0
        hits.append(hit)
    return hits


# ── Endpoint ─────────────────────────────────────────────────────────────────


@router.post(
    "/search/semantic",
    response_model=SemanticSearchResponse,
    summary="Búsqueda de texto completo con fusión semántica",
    description=(
        "Fusiona (RRF) el texto completo de Postgres (tsvector/ts_rank_cd) con "
        "la similitud vectorial sobre los chunks de pliego, ponderadas por "
        "alpha. Sin embeddings disponibles degrada a texto completo y, si este "
        "no encuentra nada, a coincidencia literal; el campo source de la "
        "respuesta dice cuál de los tres caminos se ejecutó."
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
            hybrid_search,
            like_search,
        )

        # Con filtros activos ampliamos el pool de candidatos y filtramos ANTES de
        # recortar a top_k, para no quedarnos cortos de resultados tras el filtro.
        pool = min(body.top_k * (10 if allowed_ids is not None else 2), 200)

        # La fusión primero: solo devuelve algo cuando hay modelo de embeddings
        # y chunks embebidos con los que fusionar. Que esté vacía significa que
        # el camino no existe hoy en esta instalación, no que la consulta no
        # tenga resultados — por eso se sigue al FTS en vez de responder vacío.
        fused = hybrid_search(body.q, pool, alpha=body.alpha)
        if fused:
            return _hits_from_fused(fused, allowed_ids, body.top_k), SOURCE_RRF

        fts_hits = fts5_search(body.q, pool)

        if fts_hits:
            ranked = sorted(fts_hits, key=lambda x: x[1], reverse=True)[:pool]
            source = SOURCE_FTS
        else:
            ranked = like_search(body.q, pool)
            source = SOURCE_LIKE

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
        # ``alpha`` solo se interpreta cuando ``source`` es rrf; loguear ambos
        # juntos es lo que permite saber, sin abrir la BD, si el deslizador del
        # Investigador está gobernando algo o si esa instalación no tiene
        # embeddings que fusionar.
        alpha=body.alpha,
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
    responses={
        401: {"description": "Autenticación inválida"},
        403: {"description": "Sin membresía en la organización pedida"},
    },
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
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> BusquedaGlobal:
    """F1.2 — un término, cuatro clases de resultado.

    Un término demasiado corto devuelve 200 con `sin_busqueda`, no un 422: la
    paleta consulta en cada tecla y un error por escribir dos letras sería un
    error en la mitad de las pulsaciones.
    """
    # La organización se **resuelve**, no se cree: el filtro de oportunidades
    # es `WHERE p.organization_id = %s`, así que pasar el valor crudo de la
    # query convertía la paleta en un enumerador del pipeline ajeno. Sin
    # `organization_id` no se resuelve nada, porque `None` aquí significa «no
    # busques oportunidades», no «la organización por defecto».
    resuelta: int | None = None
    if organization_id is not None:
        ambito = await resolve_organization_ctx(ctx, organization_id)
        resuelta = int(ambito["organization_id"])
    return await run_db(buscar_global, q, organization_id=resuelta, limite_por_tipo=limit)
