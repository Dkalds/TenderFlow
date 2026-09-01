"""Endpoints IA — POST /api/v1/ask y POST /api/v1/licitaciones/{id}/resumen

``/ask`` responde preguntas en lenguaje natural con soporte de conversación
multi-turno (``messages``). Sin ``id_externo`` recupera licitaciones relevantes
por FTS5 como contexto (modo general: si el corpus no cubre la pregunta, el
modelo responde con conocimiento general indicándolo). Con ``id_externo`` el
contexto es esa licitación concreta: metadatos del anuncio + fragmentos de sus
pliegos (``services/rag/context.py``).

``/licitaciones/{id_externo}/resumen`` genera un resumen ejecutivo
estructurado de la oportunidad y su pliego (streaming; cacheado por firma de
estado — documentos + ficha verificada + metadatos — con ``force`` para
regenerar).

Ambos requieren API-key con scope ``ask:read`` o sesión activa.

Ejemplo::

    curl -X POST /api/v1/ask \\
         -H "X-API-Key: sk-..." \\
         -H "Content-Type: application/json" \\
         -d '{"question": "¿Y qué solvencia técnica exige?",
              "messages": [{"role": "user", "content": "Resume los criterios"},
                            {"role": "assistant", "content": "Los criterios son..."}],
              "id_externo": "EXP-2024-001"}'

Respuesta: ``text/event-stream`` con fragmentos del modelo + evento ``[DONE]``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Callable, Iterator
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from config import settings
from llm.prompts import ChatMessage, PromptMode
from observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["ask"])

_MAX_Q_LEN = 500
_DEFAULT_TOP_K = 5
_MAX_TOP_K = 20
_MAX_HISTORY_MESSAGES = 20
_MAX_HISTORY_CONTENT_LEN = 4000

_RESUMEN_QUESTION = "Genera el resumen estructurado de esta licitación."
_RESUMEN_MAX_TOKENS = 1500

# Caché del resumen: mismo expediente + mismos documentos + misma ficha →
# mismo texto, sin pagar otra llamada LLM ni la espera del streaming. La clave
# incorpora una firma del estado (metadatos del anuncio, status de cada
# documento, extracted_at de la ficha), así que un pliego recién procesado o
# una ficha nueva invalidan solos; el TTL solo acota el caso residual.
# ``_RESUMEN_CACHE_VERSION`` se bumpea al cambiar el prompt o el contexto.
_RESUMEN_CACHE_TTL_SECONDS = 7 * 24 * 3600
_RESUMEN_CACHE_VERSION = "resumen-v2"

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


class ChatMessageDTO(BaseModel):
    """Mensaje del historial de conversación (multi-turno)."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=_MAX_HISTORY_CONTENT_LEN)


class AskRequest(BaseModel):
    """Cuerpo de la petición de preguntas en lenguaje natural."""

    question: str = Field(
        ..., min_length=3, max_length=_MAX_Q_LEN, description="Pregunta en lenguaje natural"
    )
    messages: list[ChatMessageDTO] | None = Field(
        default=None,
        max_length=_MAX_HISTORY_MESSAGES,
        description=(
            "Historial previo de la conversación (no incluye la pregunta actual). "
            "No se persiste en el servidor."
        ),
    )
    model: str = Field(
        # Mantener sincronizado con llm.client.DEFAULT_MODEL.
        default="deepseek-ai/deepseek-v4-flash-0731",
        description="Modelo LLM a usar. Ver /api/v1/ask/models para modelos disponibles.",
    )
    top_k: int = Field(
        default=_DEFAULT_TOP_K,
        ge=1,
        le=_MAX_TOP_K,
        description=(
            "Número de licitaciones a recuperar como contexto. Se ignora si se envía id_externo."
        ),
    )
    ccaa: str | None = Field(default=None, description="Filtrar licitaciones por CCAA")
    tecnologia: str | None = Field(default=None, description="Filtrar licitaciones por tecnología")
    id_externo: str | None = Field(
        default=None,
        description=(
            "ID de una licitación específica: el contexto pasa a ser esa licitación "
            "(metadatos del anuncio + fragmentos de sus pliegos) en lugar del retrieval "
            "de corpus."
        ),
    )


class AskModelInfo(BaseModel):
    """Información sobre los modelos LLM disponibles."""

    models: list[str]
    default: str


class ResumenRequest(BaseModel):
    """Cuerpo de la petición de resumen IA de una licitación."""

    model: str = Field(
        default="deepseek-ai/deepseek-v4-flash-0731",
        description="Modelo LLM a usar. Ver /api/v1/ask/models para modelos disponibles.",
    )
    force: bool = Field(
        default=False,
        description="Ignora el resumen cacheado y regenera con el proveedor LLM.",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _check_ask_scope(user: dict[str, Any]) -> None:
    """Scope check para auth por API key (usuarios de sesión siempre permitidos)."""
    if user.get("auth_method") == "api_key":
        raw_scopes = user.get("scopes", "")
        if isinstance(raw_scopes, str):
            scopes = frozenset(scope.strip() for scope in raw_scopes.split(",") if scope.strip())
        elif isinstance(raw_scopes, (set, frozenset, list, tuple)):
            scopes = frozenset(str(scope).strip() for scope in raw_scopes if str(scope).strip())
        else:
            scopes = frozenset()
        if "*" not in scopes and "ask:read" not in scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acceso denegado. Scope insuficiente.",
            )


def _budget_subject(user: dict[str, Any]) -> str | None:
    """Sujeto del presupuesto: la ``user_key`` opaca que adjunta el auth.

    Nunca el email ni el ``user_id`` crudo: ``user_key`` es el identificador
    canónico del repo para colgar estado de un usuario fuera de la BD.
    """
    raw = user.get("user_key")
    return raw if isinstance(raw, str) and raw else None


def _check_budget(user: dict[str, Any]) -> None:
    """Check eager del presupuesto ANTES de abrir el SSE: con enforce y ventana
    agotada respondemos 429 sin llamar al proveedor ni hacer retrieval
    (RFC llm-dependencia-gestionada). En monitor solo instrumenta.

    Se verifica el tope global y el del propio usuario, para que una cuenta que
    agota su cuota no arrastre a las demás."""
    from llm.budget import LLMBudgetExceeded, get_budget_guard

    try:
        get_budget_guard().check(_budget_subject(user))
    except LLMBudgetExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc


def _validate_model(model: str) -> None:
    from llm.client import AVAILABLE_MODELS

    if model not in AVAILABLE_MODELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Modelo '{model}' no disponible. Usa GET /api/v1/ask/models.",
        )


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


def _fuentes_documentos(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Evento aditivo ``fuentes_documentos``: fragmentos de pliego citables.

    Con retrieval híbrido (RAG_HYBRID_ENABLED) o contexto de licitación
    (``id_externo``), cada doc puede traer ``chunks``; sin ellos el evento no
    se emite — comportamiento idéntico al contrato SSE previo. Los chunks
    viajan tal cual (contrato aditivo: el camino ``id_externo`` añade
    ``tipo``/``filename`` a cada chunk).
    """
    return [
        {
            "id_externo": d.get("id_externo"),
            "titulo": d.get("titulo"),
            "chunks": d["chunks"],
        }
        for d in docs
        if d.get("chunks")
    ]


def _sse_event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _resumen_cache_key(
    id_externo: str,
    model: str,
    doc: dict[str, Any],
    documentos: list[dict[str, Any]],
    ficha_extracted_at: str | None,
) -> str:
    """Clave de caché del resumen: expediente + modelo + firma de estado.

    La firma cubre lo que puede cambiar el resumen sin que cambie el id: los
    metadatos del anuncio (importe, estado, fechas…), el ciclo de vida de cada
    documento (un pliego que pasa a ``extracted`` cambia el contexto) y la
    ficha verificada vigente.
    """
    import hashlib

    payload = {
        "v": _RESUMEN_CACHE_VERSION,
        "id": id_externo,
        "model": model,
        "doc": {k: v for k, v in doc.items() if k not in ("chunks", "_score")},
        "documentos": [
            (d.get("id"), d.get("status"), str(d.get("created_at"))) for d in documentos
        ],
        "ficha": ficha_extracted_at,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()
    return f"resumen|{digest}"


def _stream_sse(
    stream_factory: Callable[[], Iterator[str]],
    degraded_docs: list[dict[str, Any]],
    pre_events: list[dict[str, Any]] | None = None,
) -> AsyncGenerator[str, None]:
    """Generator SSE compartido por ``/ask`` y ``/resumen``.

    Envuelve el stream LLM síncrono con ``asyncio.wait_for`` + executor para
    evitar que un LLM colgado bloquee el worker. Ante fallo del proveedor,
    stream vacío (API key ausente) o timeout, degrada a los documentos del
    contexto sin síntesis (evento SSE ``degraded``, RFC llm-dependencia-
    gestionada).
    """

    async def _generate() -> AsyncGenerator[str, None]:
        timeout_seconds = float(settings.ASK_LLM_TIMEOUT_SECONDS)
        loop = asyncio.get_running_loop()
        # Cola thread-safe para pasar (kind, payload) del executor al event loop
        queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()

        def _run_sync() -> None:
            """Ejecuta el stream LLM en un thread y encola los chunks."""
            emitted = 0
            try:
                for chunk in stream_factory():
                    emitted += 1
                    loop.call_soon_threadsafe(queue.put_nowait, ("chunk", chunk))
                if emitted == 0:
                    # Providers sin API key/paquete devuelven un iterador vacío
                    # sin lanzar: degradar en vez de cerrar en silencio.
                    loop.call_soon_threadsafe(queue.put_nowait, ("degraded", "empty_response"))
                else:
                    loop.call_soon_threadsafe(queue.put_nowait, ("done", ""))
            except Exception as exc:
                log.warning("ask.llm_stream_error_degrading", error=str(exc))
                loop.call_soon_threadsafe(queue.put_nowait, ("degraded", "provider_error"))

        for event in pre_events or []:
            yield _sse_event(event)

        executor_task = asyncio.ensure_future(asyncio.to_thread(_run_sync))

        try:
            while True:
                # Esperar el siguiente chunk con timeout global
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=timeout_seconds)
                except TimeoutError:
                    log.error("ask.llm_timeout_degrading", timeout=timeout_seconds)
                    yield _sse_event({"degraded": True, "reason": "timeout", "docs": degraded_docs})
                    yield "data: [DONE]\n\n"
                    executor_task.cancel()
                    return

                if kind == "done":
                    yield "data: [DONE]\n\n"
                    return
                if kind == "degraded":
                    yield _sse_event({"degraded": True, "reason": payload, "docs": degraded_docs})
                    yield "data: [DONE]\n\n"
                    return
                yield f"data: {json.dumps({'text': payload})}\n\n"
        finally:
            if not executor_task.done():
                executor_task.cancel()

    return _generate()


def _prepare_ask_context(request: AskRequest) -> tuple[list[dict[str, Any]], PromptMode]:
    """Recupera los documentos de contexto para la pregunta (trabajo de BD).

    Se separa de ``_stream_ask`` para poder despacharla al threadpool: es la
    fase pesada de ``/ask`` (anuncio completo + fragmentos de pliego, o bien
    retrieval FTS + pgvector) y corría en el event loop, bloqueando la API
    entera durante cientos de milisegundos por pregunta. El streaming de tokens
    del LLM ya estaba correctamente aislado en un thread.
    """
    mode: PromptMode = "general"
    docs: list[dict[str, Any]] = []

    if request.id_externo:
        # Contexto de licitación: anuncio completo + fragmentos de pliego
        # relevantes a la pregunta. Si el id no existe se degrada al retrieval
        # general (no romper consumidores que envían ids stale).
        try:
            from services.rag.context import build_licitacion_context, primary_doc_from_context

            ctx = build_licitacion_context(request.id_externo, request.question)
        except Exception as exc:
            log.warning(
                "ask.licitacion_context_failed", id_externo=request.id_externo, error=str(exc)
            )
            ctx = None
        if ctx is not None:
            docs = [primary_doc_from_context(request.id_externo, ctx)]
            mode = "licitacion"

    if not docs:
        # Modo general: sin docs el LLM responde igualmente con conocimiento
        # general (el prompt indica que no se basa en el corpus).
        docs = _retrieve_docs(
            question=request.question,
            top_k=request.top_k,
            ccaa=request.ccaa,
            tecnologia=request.tecnologia,
        )
        mode = "general"

    return docs, mode


async def _stream_ask(request: AskRequest, scope_key: str | None) -> AsyncGenerator[str, None]:
    """Prepara contexto + historial y devuelve el stream SSE del LLM."""
    from llm.budget import bind_budget_subject
    from llm.client import stream_llm_response

    _validate_model(request.model)

    docs, mode = await run_db(_prepare_ask_context, request)

    keywords = [w for w in request.question.split() if len(w) > 3][:10]
    history: list[ChatMessage] = [
        {"role": m.role, "content": m.content} for m in request.messages or []
    ]

    # Payload del fallback degradado: los mismos docs del contexto, sin campos
    # internos (_score). El usuario recibe las licitaciones aunque no la prosa.
    degraded_docs = [{k: d.get(k) for k in _DEGRADED_DOC_FIELDS} for d in docs]
    fuentes = _fuentes_documentos(docs)

    # Evento aditivo ``ask_meta``: el ámbito EFECTIVO de la respuesta. Importa
    # cuando se pidió ``id_externo`` y el contexto de esa licitación no pudo
    # cargarse: sin este evento el fallback al corpus era silencioso y la UI
    # del detalle presentaba como "sobre este expediente" una respuesta que no
    # lo era.
    pre_events: list[dict[str, Any]] = [
        {"ask_meta": {"contexto": mode, "id_externo": request.id_externo}}
    ]
    if fuentes:
        pre_events.append({"fuentes_documentos": fuentes})

    def _factory() -> Iterator[str]:
        # El coste solo se conoce dentro de llm/client.py::_record_usage, que no
        # ve al usuario. Se corre en un thread con contexto propio (to_thread lo
        # copia), así que dejar ahí el sujeto lo atribuye sin filtrarlo a otras
        # requests.
        bind_budget_subject(scope_key)
        return stream_llm_response(
            question=request.question,
            docs=docs,
            model=request.model,
            keywords=keywords,
            history=history,
            mode=mode,
        )

    return _stream_sse(
        _factory,
        degraded_docs,
        pre_events=pre_events,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post(
    "/ask",
    summary="Pregunta en lenguaje natural (chat multi-turno, RAG + LLM)",
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
    """Responde preguntas con contexto del corpus o de una licitación concreta.

    Sin ``id_externo``: recupera las licitaciones más relevantes (FTS5) como
    contexto; si el corpus no cubre la pregunta, el modelo responde con
    conocimiento general indicándolo. Con ``id_externo``: el contexto es esa
    licitación (anuncio + fragmentos de pliegos). ``messages`` habilita la
    conversación multi-turno.

    Requiere scope ``ask:read`` (API key) o sesión activa (cookie).
    """
    _check_ask_scope(user)

    log.info(
        "ask.request",
        model=body.model,
        top_k=body.top_k,
        question_len=len(body.question),
        n_messages=len(body.messages or []),
        id_externo=body.id_externo,
        user_key_id=user.get("user_id"),
    )

    _check_budget(user)

    generator = await _stream_ask(body, _budget_subject(user))

    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    # ``:path`` y no el conversor por defecto: hay ``id_externo`` de PLACSP con
    # barras (p.ej. ``PA-S 2026/000058``). Con ``[^/]+`` esos expedientes
    # devolvían 404 en silencio, mientras sus rutas hermanas (/explain,
    # /documentos, /ficha-pliego, /tech-scores…) sí los aceptaban.
    "/licitaciones/{id_externo:path}/resumen",
    summary="Resumen IA de una licitación (oportunidad + pliegos)",
    response_class=StreamingResponse,
    responses={
        200: {"description": "Stream SSE con el resumen generado"},
        400: {"description": "Modelo no disponible"},
        401: {"description": "API key inválida o sin scope ask:read"},
        404: {"description": "Licitación no encontrada"},
        429: {"description": "Presupuesto LLM agotado (LLM_BUDGET_MODE=enforce)"},
    },
)
async def resumen_licitacion(
    id_externo: str,
    body: ResumenRequest,
    user: dict[str, Any] = Depends(require_any_auth),
) -> StreamingResponse:
    """Genera (o sirve cacheado) el resumen ejecutivo de la licitación.

    Secciones: qué se licita, órgano y contexto, importe y plazos, requisitos
    clave del pliego, y riesgos/avisos. El primer evento SSE es
    ``resumen_meta`` con ``has_pliego_text``, ``cached`` y el estado de los
    documentos — si no hay texto de pliegos procesado, el resumen se basa solo
    en los metadatos del anuncio y lo indica. Si existe una ficha estructurada
    verificada, sus hechos entran como contexto priorizado.

    El resumen generado se cachea con una firma del estado (documentos +
    ficha + metadatos): mismo estado → misma respuesta sin coste LLM.
    ``force=true`` regenera ignorando el caché.

    Requiere scope ``ask:read`` (API key) o sesión activa (cookie).
    """
    _check_ask_scope(user)
    _validate_model(body.model)

    log.info(
        "resumen.request",
        model=body.model,
        id_externo=id_externo,
        user_key_id=user.get("user_id"),
    )

    _check_budget(user)

    from llm.budget import bind_budget_subject
    from llm.client import stream_llm_response
    from services.rag.context import (
        LicitacionContext,
        build_licitacion_context,
        primary_doc_from_context,
    )

    scope_key = _budget_subject(user)

    # Igual que en `/ask`: el armado del contexto toca BD y no puede correr en
    # el event loop. `primary_doc_from_context` también va a BD, así que viaja
    # en el mismo salto al threadpool en vez de en uno propio.
    def _load_context() -> tuple[LicitacionContext, dict[str, Any], str | None] | None:
        """Contexto + documento principal + ficha, en el threadpool (van a BD).

        Si hay ficha verificada vigente, sus hechos entran como primer chunk
        etiquetado: son los únicos datos del sistema validados con cita, y el
        system prompt de modo ``resumen`` les da prioridad en la sección de
        requisitos. Su ``extracted_at`` forma parte de la firma de caché.
        """
        loaded = build_licitacion_context(id_externo, None)
        if loaded is None:
            return None
        doc = primary_doc_from_context(id_externo, loaded)
        ficha_at: str | None = None
        try:
            from services.rag.fact_sheet import facts_summary_text, get_fact_sheet

            ficha = get_fact_sheet(id_externo)
            if (
                ficha is not None
                and ficha.facts is not None
                and ficha.status in ("extracted", "needs_review")
            ):
                texto = facts_summary_text(ficha.facts)
                if texto:
                    doc["chunks"] = [
                        {"tipo": "ficha estructurada verificada", "texto": texto},
                        *doc["chunks"],
                    ]
                    ficha_at = ficha.extracted_at
        except Exception as exc:
            # La ficha es un refuerzo del contexto, nunca un bloqueo del resumen.
            log.warning("resumen.fact_sheet_context_failed", id_externo=id_externo, error=str(exc))
        return loaded, doc, ficha_at

    loaded_tuple = await run_db(_load_context)
    if loaded_tuple is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Licitación '{id_externo}' no encontrada.",
        )
    ctx, doc, ficha_at = loaded_tuple
    degraded_docs = [{k: doc.get(k) for k in _DEGRADED_DOC_FIELDS}]

    from shared.cache import get_cache

    cache = get_cache("llm_resumen")
    cache_key = _resumen_cache_key(id_externo, body.model, doc, ctx["documentos"], ficha_at)
    cached_raw = None if body.force else cache.get(cache_key)
    cached_text = str(cached_raw) if isinstance(cached_raw, str) and cached_raw.strip() else None

    resumen_meta = {
        "has_pliego_text": ctx["has_pliego_text"],
        "truncated": ctx["truncated"],
        "cached": cached_text is not None,
        "documentos": [
            {"tipo": d.get("tipo"), "filename": d.get("filename"), "status": d.get("status")}
            for d in ctx["documentos"]
        ],
    }

    if cached_text is not None:
        # Hit: se sirve el texto persistido como un único evento, sin proveedor.
        def _factory() -> Iterator[str]:
            return iter([cached_text])

    else:

        def _factory() -> Iterator[str]:
            # Ver _stream_ask: el sujeto viaja por contexto hasta _record_usage.
            bind_budget_subject(scope_key)

            def _generate_and_cache() -> Iterator[str]:
                parts: list[str] = []
                for token in stream_llm_response(
                    question=_RESUMEN_QUESTION,
                    docs=[doc],
                    model=body.model,
                    keywords=[],
                    mode="resumen",
                    max_tokens=_RESUMEN_MAX_TOKENS,
                ):
                    parts.append(token)
                    yield token
                # Solo se cachea un stream completo con contenido: los caminos
                # degradados (vacío, excepción, timeout) no dejan entrada.
                texto = "".join(parts).strip()
                if texto:
                    try:
                        cache.set(cache_key, texto, ttl=_RESUMEN_CACHE_TTL_SECONDS)
                    except Exception:
                        log.debug("resumen.cache_set_failed", exc_info=True)

            return _generate_and_cache()

    generator = _stream_sse(
        _factory,
        degraded_docs,
        pre_events=[{"resumen_meta": resumen_meta}],
    )

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
