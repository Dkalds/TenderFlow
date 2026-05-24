"""Endpoint RAG con LLM — POST /api/v1/ask

Permite hacer preguntas en lenguaje natural sobre las licitaciones almacenadas.
Recupera documentos relevantes mediante FTS5 y los envía al LLM configurado
para generar una respuesta contextual (Retrieval-Augmented Generation).

Requiere API-key con scope ``ask:read``.

Ejemplo::

    curl -X POST /api/v1/ask \\
         -H "X-API-Key: sk-..." \\
         -H "Content-Type: application/json" \\
         -d '{"question": "¿Cuántas licitaciones de SAP S/4HANA hay en Madrid?",
              "model": "gpt-4o-mini", "top_k": 5}'

Respuesta: ``text/event-stream`` con fragmentos del modelo + evento ``[DONE]``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.auth import (  # require_api_key: used by list_ask_models
    AuthContext,
    require_api_key,
    require_scope,
)
from observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["ask"])

_MAX_Q_LEN = 500
_DEFAULT_TOP_K = 5
_MAX_TOP_K = 20


# ── Schemas ───────────────────────────────────────────────────────────────────


class AskRequest(BaseModel):
    """Cuerpo de la petición de preguntas en lenguaje natural."""

    question: str = Field(
        ..., min_length=3, max_length=_MAX_Q_LEN, description="Pregunta en lenguaje natural"
    )
    model: str = Field(
        default="gpt-4o-mini",
        description="Modelo LLM a usar. Ver /api/v1/ask/models para modelos disponibles.",
    )
    top_k: int = Field(
        default=_DEFAULT_TOP_K,
        ge=1,
        le=_MAX_TOP_K,
        description="Número de licitaciones a recuperar como contexto",
    )
    ccaa: str | None = Field(default=None, description="Filtrar licitaciones por CCAA")
    tecnologia: str | None = Field(default=None, description="Filtrar licitaciones por tecnología")


class AskModelInfo(BaseModel):
    """Información sobre los modelos LLM disponibles."""

    models: list[str]
    default: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def _retrieve_docs(
    question: str,
    top_k: int,
    ccaa: str | None,
    tecnologia: str | None,
) -> list[dict[str, Any]]:
    """Recupera documentos relevantes usando FTS5.

    Construye una consulta FTS5 con la pregunta del usuario y filtros opcionales,
    devuelve una lista de dicts con los campos necesarios para el contexto LLM.
    """
    from db.database import connect

    params: list[Any] = []

    # FTS5 sobre título+descripción
    fts_query = " OR ".join(f'"{w}"' for w in question.split()[:10] if len(w) > 2)
    if not fts_query:
        fts_query = "*"

    base_query = """
        SELECT l.id_externo, l.titulo, l.organo_contratacion, l.importe,
               l.estado, l.descripcion, l.ccaa, l.tecnologia, l.fecha_publicacion
        FROM licitaciones l
        INNER JOIN licitaciones_fts fts ON l.id_externo = fts.id_externo
        WHERE licitaciones_fts MATCH ?
    """
    params.append(fts_query)

    if ccaa:
        base_query += " AND l.ccaa = ?"
        params.append(ccaa)
    if tecnologia:
        base_query += " AND l.tecnologia = ?"
        params.append(tecnologia)

    base_query += f" ORDER BY rank LIMIT {int(top_k)}"

    try:
        with connect() as c:
            rows = c.execute(base_query, params).fetchall()
            if not rows:
                # Fallback: LIKE search si FTS no devuelve resultados
                words = [w for w in question.split() if len(w) > 3][:5]
                if words:
                    like_clauses = " OR ".join("titulo LIKE ?" for _ in words)
                    like_params = [f"%{w}%" for w in words]
                    if ccaa:
                        like_clauses += " AND ccaa = ?"
                        like_params.append(ccaa)
                    rows = c.execute(
                        f"""
                        SELECT id_externo, titulo, organo_contratacion, importe,
                               estado, descripcion, ccaa, tecnologia, fecha_publicacion
                        FROM licitaciones WHERE {like_clauses} LIMIT {int(top_k)}
                        """,
                        like_params,
                    ).fetchall()
    except Exception as exc:
        log.warning("ask.retrieve_docs_failed", error=str(exc))
        return []

    cols = [
        "id_externo",
        "titulo",
        "organo_contratacion",
        "importe",
        "estado",
        "descripcion",
        "ccaa",
        "tecnologia",
        "fecha_publicacion",
    ]
    return [dict(zip(cols, row, strict=False)) for row in rows]


def _stream_ask(request: AskRequest) -> Any:
    """Genera el stream SSE con los fragmentos del LLM."""
    from llm.client import AVAILABLE_MODELS, stream_llm_response

    if request.model not in AVAILABLE_MODELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Modelo '{request.model}' no disponible. Usa GET /api/v1/ask/models.",
        )

    docs = _retrieve_docs(
        question=request.question,
        top_k=request.top_k,
        ccaa=request.ccaa,
        tecnologia=request.tecnologia,
    )

    if not docs:
        # Respuesta sin contexto
        def _no_context() -> Iterator[str]:
            yield "data: No se encontraron licitaciones relevantes para tu pregunta.\n\n"
            yield "data: [DONE]\n\n"

        return _no_context()

    keywords = [w for w in request.question.split() if len(w) > 3][:10]

    def _generate() -> Iterator[str]:
        try:
            for chunk in stream_llm_response(
                question=request.question,
                docs=docs,
                model=request.model,
                keywords=keywords,
            ):
                yield f"data: {json.dumps({'text': chunk})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:
            log.warning("ask.llm_stream_error", error=str(exc))
            yield f"data: {json.dumps({'error': 'Error generando respuesta LLM'})}\n\n"
            yield "data: [DONE]\n\n"

    return _generate()


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post(
    "/ask",
    summary="Pregunta en lenguaje natural sobre licitaciones (RAG + LLM)",
    response_class=StreamingResponse,
    responses={
        200: {"description": "Stream SSE con la respuesta del LLM"},
        400: {"description": "Modelo no disponible o parámetros inválidos"},
        401: {"description": "API key inválida o sin scope ask:read"},
    },
)
async def ask_question(
    body: AskRequest,
    auth: AuthContext = Depends(require_scope("ask:read")),
) -> StreamingResponse:
    """Responde a preguntas sobre licitaciones usando RAG + LLM.

    Recupera las licitaciones más relevantes mediante FTS5 y las usa como
    contexto para generar una respuesta con el modelo LLM configurado.

    Requiere scope ``ask:read``.
    """

    log.info(
        "ask.request",
        model=body.model,
        top_k=body.top_k,
        question_len=len(body.question),
        user_key_id=auth.key_id,
    )

    generator = _stream_ask(body)

    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/ask/models",
    summary="Modelos LLM disponibles para el endpoint /ask",
)
async def list_ask_models(
    auth: AuthContext = Depends(require_api_key),
) -> AskModelInfo:
    """Lista los modelos LLM disponibles para usar en POST /api/v1/ask."""
    from llm.client import AVAILABLE_MODELS

    return AskModelInfo(models=AVAILABLE_MODELS, default="gpt-4o-mini")
