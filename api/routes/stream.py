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
  ``POLL_INTERVAL`` segundos (por defecto 5 s), respaldado por Postgres.
* Heartbeat cada ``HEARTBEAT_INTERVAL`` segundos (por defecto 30 s) para
  mantener la conexión TCP viva a través de proxies y load-balancers.
* Máximo ``MAX_DURATION_SECONDS`` por conexión (por defecto 300 s = 5 min)
  para evitar conexiones zombi.
* Requiere API key con cualquier scope (autenticación estándar).
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
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


def _parse_last_event_id(value: str) -> float:
    """Parsea el cursor SSE y descarta números no finitos."""
    try:
        timestamp = float(value) if value else 0.0
    except (ValueError, OverflowError):
        return 0.0
    return timestamp if math.isfinite(timestamp) else 0.0


def _fetch_recent(since_ts: float, limit: int) -> list[dict[str, Any]]:
    """Recupera licitaciones publicadas/actualizadas desde ``since_ts``."""
    from services.licitaciones import fetch_recent

    since_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(since_ts))
    try:
        return fetch_recent(since_iso, limit)
    except Exception as exc:
        log.warning("stream.fetch_recent_failed", error=str(exc))
        return []


class _SignalWatcher:
    """Poller único de proceso para el centinela de ingesta, con fan-out en memoria.

    Cada conexión SSE consultaba el centinela por su cuenta cada 5 s. Con N
    clientes con el dashboard abierto eso son 12 consultas por minuto y cliente,
    una ocupando un hilo del threadpool y una conexión del pool, solo para
    preguntar si hay novedades: veinte usuarios agotaban el presupuesto de
    concurrencia de la API sin que nadie hubiera pedido nada.

    Aquí el centinela se consulta **una vez por proceso** mientras haya al menos
    un suscriptor, y el resultado se reparte por una ``asyncio.Condition``. El
    coste pasa de O(clientes) a O(1), y además el aviso es inmediato en vez de
    esperar al siguiente tick de cada generador.
    """

    def __init__(self) -> None:
        self._subscribers = 0
        self._task: asyncio.Task[None] | None = None
        self._cond = asyncio.Condition()
        self._signal_ts: float = 0.0
        self._loop: asyncio.AbstractEventLoop | None = None

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[_SignalWatcher]:
        """Registra un suscriptor; arranca el poller con el primero y lo para con el último."""
        async with self._cond:
            self._subscribers += 1
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run())
        try:
            yield self
        finally:
            async with self._cond:
                self._subscribers -= 1
                if self._subscribers <= 0 and self._task is not None:
                    self._task.cancel()
                    self._task = None
                    self._signal_ts = 0.0

    async def _run(self) -> None:
        from shared.cache_signal import get_signal_timestamp

        while True:
            try:
                ts = await run_db(get_signal_timestamp)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("stream.signal_poll_failed", error=str(exc))
                ts = 0.0
            if ts > self._signal_ts:
                async with self._cond:
                    self._signal_ts = ts
                    self._cond.notify_all()
            await asyncio.sleep(_POLL_INTERVAL)

    async def wait_for_signal(self, since: float, timeout: float) -> float | None:
        """Marca del centinela si supera ``since``; ``None`` si expiró el plazo."""
        async with self._cond:
            if self._signal_ts > since:
                return self._signal_ts
            try:
                await asyncio.wait_for(self._cond.wait(), timeout=timeout)
            except TimeoutError:
                return None
            return self._signal_ts if self._signal_ts > since else None


_watcher: _SignalWatcher | None = None


def _get_watcher() -> _SignalWatcher:
    """Singleton del watcher, recreado si cambia el event loop.

    La suite instancia la app en loops distintos (``TestClient`` abre uno por
    petición), y una ``Condition`` atada a un loop muerto no sirve.
    """
    global _watcher
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _watcher is None or _watcher._loop is not loop:
        _watcher = _SignalWatcher()
        _watcher._loop = loop
    return _watcher


async def _event_generator(
    request: Request,
    last_event_id: float,
    batch: int,
) -> AsyncGenerator[str, None]:
    """Generador asíncrono de eventos SSE."""
    deadline = time.monotonic() + _MAX_DURATION_SECONDS
    last_signal_check = last_event_id  # timestamp del último evento conocido por el cliente
    last_heartbeat = time.monotonic()

    # Enviar heartbeat inicial para confirmar conexión
    yield _sse_event("heartbeat", {"ts": time.time()})

    async with _get_watcher().subscribe() as watcher:
        while time.monotonic() < deadline:
            # Comprobar si el cliente desconectó — debe ir antes de cualquier yield
            # para no emitir heartbeat/data a un cliente que ya se fue.
            if await request.is_disconnected():
                log.debug("stream.client_disconnected")
                break

            now = time.monotonic()

            # Heartbeat — verificar desconexión justo antes de emitir para no
            # desperdiciar I/O en un cliente que ya se fue.
            if now - last_heartbeat >= _HEARTBEAT_INTERVAL:
                if await request.is_disconnected():
                    log.debug("stream.client_disconnected_before_heartbeat")
                    break
                yield _sse_event("heartbeat", {"ts": time.time()})
                last_heartbeat = now

            # Esperar aviso del poller compartido (sin tocar la BD desde aquí).
            signal_ts = await watcher.wait_for_signal(last_signal_check, _POLL_INTERVAL)
            if signal_ts is None:
                continue

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
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> StreamingResponse:
    """Endpoint SSE para notificaciones push de nuevas licitaciones."""
    # Soporte para reconexión: Last-Event-ID contiene el timestamp del último evento
    last_event_id_header = request.headers.get("Last-Event-ID", "")
    last_event_ts = _parse_last_event_id(last_event_id_header)

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
        user=ctx.get("user_id"),
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
