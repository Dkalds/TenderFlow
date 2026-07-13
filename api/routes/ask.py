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
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.routes.dual_auth import require_any_auth
from config import settings
from observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["ask"])

_MAX_Q_LEN = 500
_DEFAULT_TOP_K = 5
_MAX_TOP_K = 20

# Campos que viajan en el evento SSE ``degraded`` (fallback sin síntesis LLM).
# Aditivo al stream, NO al DTO (RFC llm-dependencia-gestionada §3.5).
_DEGRADED_DOC_FIELDS = (
    "id_externo",
    "titulo",
    "organo_contratacion",
    "importe",
    "estado",
    "fecha_publicacion",
    "url",
)


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
    # Feature C: contexto especifico de una licitacion (backwards-compatible: opcional)
    id_externo: str | None = Field(
        default=None,
        description="ID de una licitación específica para añadirla como primer documento de contexto",
    )


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
    id_externo: str | None = None,
) -> list[dict[str, Any]]:
    """Recupera documentos relevantes usando FTS5 con LIKE fallback.

    Si ``id_externo`` se proporciona (Feature C), antepone el registro completo
    de esa licitación como primer documento de contexto.

    Delega en ``services.licitaciones.search_for_ask`` que orquesta
    FTS5 + LIKE fallback a través del repository.
    """
    try:
        from services.licitaciones import get_licitacion_detail, search_for_ask

        docs = search_for_ask(question, top_k, ccaa=ccaa, tecnologia=tecnologia)

        # Feature C: anteponer el detalle de la licitacion especifica si se proporciona
        if id_externo:
            try:
                detail = get_licitacion_detail(id_externo)
                if detail is not None:
                    # Construir un doc de contexto con los campos mas relevantes
                    primary_doc: dict[str, Any] = {
                        "id_externo": id_externo,
                        "titulo": detail.get("titulo"),
                        "descripcion": str(detail.get("descripcion") or "")[:1000],
                        "organo_contratacion": detail.get("organo_contratacion"),
                        "importe": detail.get("importe"),
                        "fecha_publicacion": detail.get("fecha_publicacion"),
                        "fecha_limite": detail.get("fecha_limite"),
                        "cpv": detail.get("cpv"),
                        "ccaa": detail.get("ccaa"),
                        "estado": detail.get("estado"),
                        "url": detail.get("url"),
                        "_score": 2.0,  # prioridad maxima
                    }
                    # Insertar al principio, evitar duplicado si ya aparece en FTS
                    docs = [primary_doc] + [d for d in docs if d.get("id_externo") != id_externo]
            except Exception as exc:
                log.debug("ask.primary_doc_failed", id_externo=id_externo, error=str(exc))

        return docs
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
        id_externo=request.id_externo,
    )

    if not docs:
        # Respuesta sin contexto
        async def _no_context() -> AsyncGenerator[str, None]:
            yield "data: No se encontraron licitaciones relevantes para tu pregunta.\n\n"
            yield "data: [DONE]\n\n"

        return _no_context()

    keywords = [w for w in request.question.split() if len(w) > 3][:10]

    # Payload del fallback degradado: los mismos docs del retrieval, sin campos
    # internos (_score). El usuario recibe las licitaciones aunque no la prosa.
    degraded_docs = [{k: d.get(k) for k in _DEGRADED_DOC_FIELDS} for d in docs]

    def _degraded_event(reason: str) -> str:
        payload = {"degraded": True, "reason": reason, "docs": degraded_docs}
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    # Campo aditivo opcional (plan Pliegos+RAG, F9): con retrieval híbrido
    # activo (RAG_HYBRID_ENABLED), cada doc puede traer `chunks` -- los
    # fragmentos de pliego que motivaron su inclusión (fuentes citables). Sin
    # retrieval híbrido (o sin match vectorial) esto es simplemente [] y no
    # se emite ningún evento — comportamiento idéntico al anterior al cambio.
    fuentes_documentos = [
        {
            "id_externo": d.get("id_externo"),
            "titulo": d.get("titulo"),
            "chunks": d["chunks"],
        }
        for d in docs
        if d.get("chunks")
    ]

    async def _generate() -> AsyncGenerator[str, None]:
        """Async generator que envuelve el stream LLM síncrono con timeout.

        Usa ``asyncio.wait_for`` + ``run_in_executor`` para evitar que un LLM
        colgado bloquee el worker indefinidamente. Ante fallo del proveedor,
        breaker abierto o timeout, degrada a los documentos del retrieval sin
        síntesis (evento SSE ``degraded``, RFC llm-dependencia-gestionada).
        """
        timeout_seconds = float(settings.ASK_LLM_TIMEOUT_SECONDS)
        loop = asyncio.get_running_loop()
        # Cola thread-safe para pasar (kind, payload) del executor al event loop
        queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()

        def _run_sync() -> None:
            """Ejecuta el stream LLM en un thread y encola los chunks."""
            try:
                for chunk in stream_llm_response(
                    question=request.question,
                    docs=docs,
                    model=request.model,
                    keywords=keywords,
                ):
                    loop.call_soon_threadsafe(queue.put_nowait, ("chunk", chunk))
                loop.call_soon_threadsafe(queue.put_nowait, ("done", ""))
            except Exception as exc:
                log.warning("ask.llm_stream_error_degrading", error=str(exc))
                loop.call_soon_threadsafe(queue.put_nowait, ("degraded", "provider_error"))

        if fuentes_documentos:
            yield (
                f"data: {json.dumps({'fuentes_documentos': fuentes_documentos}, ensure_ascii=False)}\n\n"
            )

        executor_task = asyncio.ensure_future(asyncio.to_thread(_run_sync))

        try:
            while True:
                # Esperar el siguiente chunk con timeout global
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=timeout_seconds)
                except TimeoutError:
                    log.error(
                        "ask.llm_timeout_degrading",
                        model=request.model,
                        timeout=timeout_seconds,
                    )
                    yield _degraded_event("timeout")
                    yield "data: [DONE]\n\n"
                    executor_task.cancel()
                    return

                if kind == "done":
                    yield "data: [DONE]\n\n"
                    return
                if kind == "degraded":
                    yield _degraded_event(payload)
                    yield "data: [DONE]\n\n"
                    return
                yield f"data: {json.dumps({'text': payload})}\n\n"
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
        429: {"description": "Presupuesto LLM agotado (LLM_BUDGET_MODE=enforce)"},
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

    # Check eager del presupuesto ANTES de abrir el SSE: con enforce y ventana
    # agotada respondemos 429 sin llamar al proveedor ni hacer retrieval
    # (RFC llm-dependencia-gestionada). En monitor solo instrumenta.
    from llm.budget import LLMBudgetExceeded, get_budget_guard

    try:
        get_budget_guard().check()
    except LLMBudgetExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc

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
