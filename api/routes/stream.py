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
* **Un solo poller por proceso** (``_SignalWatcher``) lee el centinela de
  ``shared.cache_signal`` cada ``POLL_INTERVAL`` segundos y publica el
  timestamp en memoria. Antes cada cliente conectado hacía su propia consulta
  cada 5 s: con N clientes eran N consultas por intervalo, casi todas sin
  novedades, compitiendo por el threadpool con el resto de la API. Ahora la
  carga a BD es O(1) en el número de clientes.
* Los clientes comparan ese timestamp contra su propio checkpoint. Es
  exactamente lo que hacía ``check_cache_signal(last_check)``
  (``get_signal_timestamp() > last_check``), pero sin viaje a BD por cliente.
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
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["stream"])

# Configuración
_POLL_INTERVAL = 5.0  # segundos entre polls al centinela (poller compartido)
_CLIENT_TICK = 1.0  # segundos entre iteraciones del bucle por cliente
_HEARTBEAT_INTERVAL = 30.0  # segundos entre heartbeats
_MAX_DURATION_SECONDS = 300  # máximo tiempo de conexión (5 min)
_DEFAULT_BATCH = 20  # licitaciones por evento


class _SignalWatcher:
    """Poller único por proceso del centinela de ingesta.

    Arranca con el primer cliente SSE y se para con el último, así que un
    proceso sin suscriptores no consulta nada. El bucle por cliente
    (``_CLIENT_TICK``, 1 s) solo lee ``latest`` en memoria: puede ser más
    frecuente que el poll a BD sin coste, lo que además detecta antes las
    desconexiones.
    """

    def __init__(self) -> None:
        self._subscribers = 0
        self._task: asyncio.Task[None] | None = None
        self._latest = 0.0

    @property
    def latest(self) -> float:
        """Último timestamp visto del centinela. Lectura en memoria."""
        return self._latest

    def _read_signal(self) -> float:
        from shared.cache_signal import get_signal_timestamp

        return get_signal_timestamp()

    async def _refresh(self) -> None:
        try:
            value = await run_db(self._read_signal)
        except Exception as exc:
            # Un fallo del centinela no puede tumbar el poller: el siguiente
            # ciclo reintenta y los clientes siguen recibiendo heartbeats.
            log.warning("stream.signal_poll_failed", error=str(exc))
            return
        if value > self._latest:
            self._latest = value

    async def _run(self) -> None:
        # Duerme antes de leer: ``subscribe`` ya hizo la lectura inicial, así
        # que refrescar aquí de entrada sería un viaje a BD duplicado.
        while self._subscribers > 0:
            await asyncio.sleep(_POLL_INTERVAL)
            if self._subscribers > 0:
                await self._refresh()

    async def subscribe(self) -> None:
        """Registra un cliente y arranca el poller si es el primero."""
        self._subscribers += 1
        if self._task is None or self._task.done():
            await self._refresh()  # valor inicial sin esperar un ciclo entero
            self._task = asyncio.create_task(self._run())
            log.debug("stream.watcher_started")

    async def unsubscribe(self) -> None:
        """Da de baja un cliente y para el poller si era el último."""
        self._subscribers = max(0, self._subscribers - 1)
        if self._subscribers == 0 and self._task is not None:
            self._task.cancel()
            self._task = None
            log.debug("stream.watcher_stopped")


_watcher = _SignalWatcher()


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


async def _event_generator(
    request: Request,
    last_event_id: float,
    batch: int,
) -> AsyncGenerator[str, None]:
    """Generador asíncrono de eventos SSE."""
    deadline = time.monotonic() + _MAX_DURATION_SECONDS
    last_signal_check = last_event_id  # timestamp del último evento conocido por el cliente
    last_heartbeat = time.monotonic()

    await _watcher.subscribe()
    try:
        # Enviar heartbeat inicial para confirmar conexión
        yield _sse_event("heartbeat", {"ts": time.time()})

        while time.monotonic() < deadline:
            # Comprobar si el cliente desconectó — debe ir antes de cualquier
            # yield para no emitir heartbeat/data a un cliente que ya se fue.
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

            # Señal de nueva ingesta: comparación en memoria contra el
            # timestamp que publica el poller compartido. Equivale a
            # ``check_cache_signal(last_signal_check)`` sin viaje a BD.
            if _watcher.latest > last_signal_check:
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
                            "as_of": time.strftime(
                                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(new_signal_ts)
                            ),
                        },
                    )
                    log.info("stream.sent_batch", n=len(items))

                last_signal_check = new_signal_ts

            await asyncio.sleep(_CLIENT_TICK)

        # Evento de cierre limpio
        yield _sse_event("close", {"reason": "max_duration_reached"})
    finally:
        await _watcher.unsubscribe()


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
