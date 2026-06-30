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

import asyncio
import json
import os
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.routes.dual_auth import require_any_auth
from observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["ask"])

_MAX_Q_LEN = 500
_DEFAULT_TOP_K = 5
_MAX_TOP_K = 20

# Timeout para la llamada al LLM (segundos). Configurable vía variable de entorno.
_LLM_TIMEOUT_SECONDS = float(os.environ.get("ASK_LLM_TIMEOUT_SECONDS", "120"))


# ── Schemas ───────────────────────────────────────────────────────────────────


class AskRequest(BaseModel):
    """Cuerpo de la petición de preguntas en lenguaje natural."""

    question: str = Field(
        ..., min_length=3, max_length=_MAX_Q_LEN, description="Pregunta en lenguaje natural"
    )
    model: str = Field(
        # Mantener sincronizado con llm.client.DEFAULT_MODEL.
        default="deepseek-ai/deepseek-v4-pro",
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
    """Recupera documentos relevantes usando FTS5 con LIKE fallback.

    Delega en ``services.licitaciones.search_for_ask`` que orquesta
    FTS5 + LIKE fallback a través del repository.
    """
    try:
        from services.licitaciones import search_for_ask

        return search_for_ask(question, top_k, ccaa=ccaa, tecnologia=tecnologia)
    except Exception as exc:
        log.warning("ask.retrieve_docs_failed", error=str(exc))
        return []


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
        async def _no_context() -> AsyncGenerator[str, None]:
            yield "data: No se encontraron licitaciones relevantes para tu pregunta.\n\n"
            yield "data: [DONE]\n\n"

        return _no_context()

    keywords = [w for w in request.question.split() if len(w) > 3][:10]

    async def _generate() -> AsyncGenerator[str, None]:
        """Async generator que envuelve el stream LLM síncrono con timeout.

        Usa ``asyncio.wait_for`` + ``run_in_executor`` para evitar que un LLM
        colgado bloquee el worker indefinidamente.
        """
        loop = asyncio.get_running_loop()
        # Cola thread-safe para pasar chunks del executor al event loop
        queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()

        def _run_sync() -> None:
            """Ejecuta el stream LLM en un thread y encola los chunks."""
            try:
                for chunk in stream_llm_response(
                    question=request.question,
                    docs=docs,
                    model=request.model,
                    keywords=keywords,
                ):
                    loop.call_soon_threadsafe(queue.put_nowait, (chunk, False))
                loop.call_soon_threadsafe(queue.put_nowait, ("", True))
            except Exception as exc:
                log.warning("ask.llm_stream_error", error=str(exc))
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    (json.dumps({"error": "Error generando respuesta LLM"}), True),
                )

        executor_task = asyncio.ensure_future(asyncio.to_thread(_run_sync))

        try:
            done = False
            while not done:
                # Esperar el siguiente chunk con timeout global
                try:
                    chunk, done = await asyncio.wait_for(queue.get(), timeout=_LLM_TIMEOUT_SECONDS)
                except TimeoutError:
                    log.error(
                        "ask.llm_timeout",
                        model=request.model,
                        timeout=_LLM_TIMEOUT_SECONDS,
                    )
                    yield f"data: {json.dumps({'error': 'Timeout esperando respuesta del LLM'})}\n\n"
                    yield "data: [DONE]\n\n"
                    executor_task.cancel()
                    return

                if done:
                    yield "data: [DONE]\n\n"
                else:
                    yield f"data: {json.dumps({'text': chunk})}\n\n"
        finally:
            if not executor_task.done():
                executor_task.cancel()

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
    user: dict[str, Any] = Depends(require_any_auth),
) -> StreamingResponse:
    """Responde a preguntas sobre licitaciones usando RAG + LLM.

    Recupera las licitaciones más relevantes mediante FTS5 y las usa como
    contexto para generar una respuesta con el modelo LLM configurado.

    Requiere scope ``ask:read`` (API key) o sesión activa (cookie).
    """
    # Scope check for API key auth only (session users always allowed)
    if user.get("auth_method") == "api_key":
        scopes_str = user.get("scopes", "")
        scopes = frozenset(s.strip() for s in scopes_str.split(",") if s.strip())
        if "*" not in scopes and "ask:read" not in scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acceso denegado. Scope insuficiente.",
            )

    log.info(
        "ask.request",
        model=body.model,
        top_k=body.top_k,
        question_len=len(body.question),
        user_key_id=user.get("user_id"),
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
    _user: dict[str, Any] = Depends(require_any_auth),
) -> AskModelInfo:
    """Lista los modelos LLM disponibles para usar en POST /api/v1/ask."""
    from llm.client import AVAILABLE_MODELS, DEFAULT_MODEL

    return AskModelInfo(models=AVAILABLE_MODELS, default=DEFAULT_MODEL)
