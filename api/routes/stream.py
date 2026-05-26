"""SSE — GET /api/v1/licitaciones/stream.

Implementa Server-Sent Events (SSE) para notificaciones push de nuevas
licitaciones sin polling del cliente.

Protocolo
---------
El cliente abre una conexión HTTP persistent con ``Accept: text/event-stream``.
El servidor emite eventos en formato SSE estándar::

    event: licitaciones_nuevas
    data: {"items": [...], "total_nuevas": 3, "as_of": "2026-05-22T..."}

    event: heartbeat
    data: {"ts": 1748000000.0}

    event: error
    data: {"detail": "mensaje de error"}

La conexión se cierra si el cliente envía ``Last-Event-ID`` con el timestamp
del último evento procesado (reconexión idempotente).

Diseño
------
* Poll interno sobre ``shared.cache_signal.check_cache_signal()`` cada
  ``POLL_INTERVAL`` segundos (por defecto 5 s). Sin pubsub, sin Redis.
* Heartbeat cada ``HEARTBEAT_INTERVAL`` segundos (por defecto 30 s) para
  mantener la conexión TCP viva a través de proxies y load-balancers.
* Máximo ``MAX_DURATION_SECONDS`` por conexión (por defecto 300 s = 5 min)
  para evitar conexiones zombi.
* Requiere API key con cualquier scope (autenticación estándar).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from api.auth import AuthContext, require_api_key
from api.concurrency import run_db
from observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["stream"])

# Configuración
_POLL_INTERVAL = 5.0  # segundos entre polls al centinela
_HEARTBEAT_INTERVAL = 30.0  # segundos entre heartbeats
_MAX_DURATION_SECONDS = 300  # máximo tiempo de conexión (5 min)
_DEFAULT_BATCH = 20  # licitaciones por evento


def _sse_event(event: str, data: Any) -> str:
    """Formatea un evento SSE como string."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def _fetch_recent(since_ts: float, limit: int) -> list[dict[str, Any]]:
    """Recupera licitaciones publicadas/actualizadas desde ``since_ts``."""
    from services.licitaciones import fetch_recent

    since_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(since_ts))
    try:
        return fetch_recent(since_iso, limit)
    except Exception as exc:
        log.warning("stream.fetch_recent_failed", error=str(exc))
        return []


async def _event_generator(
    request: Request,
    last_event_id: float,
    batch: int,
) -> AsyncGenerator[str, None]:
    """Generador asíncrono de eventos SSE."""
    from shared.cache_signal import check_cache_signal

    deadline = time.monotonic() + _MAX_DURATION_SECONDS
    last_signal_check = last_event_id  # timestamp del último evento conocido por el cliente
    last_heartbeat = time.monotonic()

    # Enviar heartbeat inicial para confirmar conexión
    yield _sse_event("heartbeat", {"ts": time.time()})

    while time.monotonic() < deadline:
        # Comprobar si el cliente desconectó
        if await request.is_disconnected():
            log.debug("stream.client_disconnected")
            break

        now = time.monotonic()

        # Heartbeat
        if now - last_heartbeat >= _HEARTBEAT_INTERVAL:
            yield _sse_event("heartbeat", {"ts": time.time()})
            last_heartbeat = now

        # Comprobar señal de nueva ingesta
        if check_cache_signal(last_signal_check):
            new_signal_ts = time.time()
            try:
                items = await run_db(_fetch_recent, last_signal_check, batch)
            except Exception as exc:
                log.warning("stream.fetch_failed", error=str(exc))
                items = []

            if items:
                yield _sse_event(
                    "licitaciones_nuevas",
                    {
                        "items": items,
                        "total_nuevas": len(items),
                        "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(new_signal_ts)),
                    },
                )
                log.info("stream.sent_batch", n=len(items))

            last_signal_check = new_signal_ts

        await asyncio.sleep(_POLL_INTERVAL)

    # Evento de cierre limpio
    yield _sse_event("close", {"reason": "max_duration_reached"})


@router.get(
    "/licitaciones/stream",
    summary="SSE — Notificaciones en tiempo real de nuevas licitaciones",
    description=(
        "Abre una conexión Server-Sent Events. Emite eventos ``licitaciones_nuevas`` "
        "cuando el scraper ingesta datos nuevos, y ``heartbeat`` cada 30 s para "
        "mantener la conexión viva. La conexión se cierra automáticamente tras "
        f"{_MAX_DURATION_SECONDS // 60} minutos."
    ),
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "Stream SSE de eventos de licitaciones",
        }
    },
    include_in_schema=True,
)
async def licitaciones_stream(
    request: Request,
    ctx: AuthContext = Depends(require_api_key),
) -> StreamingResponse:
    """Endpoint SSE para notificaciones push de nuevas licitaciones."""
    # Soporte para reconexión: Last-Event-ID contiene el timestamp del último evento
    last_event_id_header = request.headers.get("Last-Event-ID", "")
    try:
        _ts = float(last_event_id_header) if last_event_id_header else 0.0
        # Guard contra NaN/Inf inyectados vía header (Semgrep: nan-injection)
        import math

        last_event_ts = _ts if math.isfinite(_ts) else 0.0
    except (ValueError, OverflowError):
        last_event_ts = 0.0

    # batch desde query param con límite
    try:
        batch_size = min(
            int(request.query_params.get("batch", str(_DEFAULT_BATCH))),
            _DEFAULT_BATCH * 2,
        )
    except (ValueError, OverflowError):
        batch_size = _DEFAULT_BATCH

    log.info(
        "stream.connected",
        user=getattr(ctx, "user_id", None),
        last_event_ts=last_event_ts,
    )

    return StreamingResponse(
        _event_generator(request, last_event_ts, batch_size),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Nginx: deshabilitar buffering
            "Connection": "keep-alive",
        },
    )
