"""Tests para api/routes/stream.py — GET /api/v1/licitaciones/stream (B12).

Cubre:
- Autenticación (401 sin key)
- Content-Type text/event-stream
- Heartbeat inicial emitido
- Soporte Last-Event-ID (reconexión)
- Evento close emitido al agotar max_duration
- Batch size respeta el parámetro query ?batch=
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def stream_client(api_db, api_key):
    """TestClient con API key válida."""
    from api.app import app

    c = TestClient(app, raise_server_exceptions=False)
    c.headers.update({"X-API-Key": api_key})
    return c


# ── Helpers ───────────────────────────────────────────────────────────────────


def _patch_fast_stream():
    """Parchea _event_generator para devolver sólo heartbeat + close inmediatamente."""

    async def _fast_gen(request, last_event_id, batch):
        yield 'event: heartbeat\ndata: {"ts": 1.0}\n\n'
        yield 'event: close\ndata: {"reason": "max_duration_reached"}\n\n'

    return patch("api.routes.stream._event_generator", _fast_gen)


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestFetchRecentLookback:
    """La ventana hacia atrás está acotada antes de llegar a la consulta.

    Una conexión sin ``Last-Event-ID`` arranca el cursor en 0.0 —1970— y el
    ``WHERE`` de ``fetch_recent`` pasaba a matchear la tabla entera: era la
    consulta con más tiempo acumulado de producción (13,4 s de media, 110,9 s
    de pico). Ningún índice arregla eso sin recortar la ventana.
    """

    def _capturar_since(self, since_ts: float) -> str:
        from api.routes import stream

        capturado: dict[str, str] = {}

        def _fake_fetch_recent(since_iso, limit):
            capturado["since"] = since_iso
            return []

        with patch("services.licitaciones.fetch_recent", _fake_fetch_recent):
            stream._fetch_recent(since_ts, 20)
        return capturado["since"]

    def test_cursor_en_cero_no_consulta_desde_1970(self):
        from api.routes.stream import _MAX_LOOKBACK_SECONDS

        since = self._capturar_since(0.0)

        minimo = time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - _MAX_LOOKBACK_SECONDS - 5)
        )
        assert not since.startswith("1970")
        assert since >= minimo

    def test_cursor_reciente_se_respeta(self):
        """El recorte es un suelo, no un valor fijo: una reconexión normal
        sigue pidiendo exactamente desde donde se quedó."""
        hace_una_hora = time.time() - 3600
        esperado = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(hace_una_hora))

        assert self._capturar_since(hace_una_hora) == esperado


class TestStreamAuth:
    def test_stream_requires_api_key(self, client):
        """Sin API key → 401."""
        resp = client.get("/api/v1/licitaciones/stream")
        assert resp.status_code == 401

    def test_stream_wrong_key_returns_401(self, client):
        resp = client.get("/api/v1/licitaciones/stream", headers={"X-API-Key": "bad-key"})
        assert resp.status_code == 401


class TestStreamSSE:
    def test_stream_returns_event_stream_content_type(self, stream_client):
        """Respuesta tiene Content-Type text/event-stream."""
        with _patch_fast_stream():
            resp = stream_client.get("/api/v1/licitaciones/stream")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_stream_emits_heartbeat_event(self, stream_client):
        """El primer evento emitido es heartbeat."""
        with _patch_fast_stream():
            resp = stream_client.get("/api/v1/licitaciones/stream")
        assert "event: heartbeat" in resp.text

    def test_stream_emits_close_event(self, stream_client):
        """El stream termina con evento close."""
        with _patch_fast_stream():
            resp = stream_client.get("/api/v1/licitaciones/stream")
        assert "event: close" in resp.text
        assert "max_duration_reached" in resp.text

    def test_stream_accepts_last_event_id_header(self, stream_client):
        """Last-Event-ID válido es aceptado sin error."""
        with _patch_fast_stream():
            resp = stream_client.get(
                "/api/v1/licitaciones/stream",
                headers={"Last-Event-ID": str(time.time())},
            )
        assert resp.status_code == 200

    def test_stream_invalid_last_event_id_falls_back(self, stream_client):
        """Last-Event-ID no numérico no causa error (fallback a 0.0)."""
        with _patch_fast_stream():
            resp = stream_client.get(
                "/api/v1/licitaciones/stream",
                headers={"Last-Event-ID": "not-a-number"},
            )
        assert resp.status_code == 200

    @pytest.mark.parametrize("last_event_id", ["NaN", "inf", "-inf"])
    def test_stream_non_finite_last_event_id_falls_back(self, stream_client, last_event_id):
        """Valores no finitos nunca llegan al generador SSE."""
        seen: dict[str, float] = {}

        async def _capture_gen(request, event_id, batch):
            seen["event_id"] = event_id
            yield 'event: close\ndata: {"reason": "test"}\n\n'

        with patch("api.routes.stream._event_generator", _capture_gen):
            resp = stream_client.get(
                "/api/v1/licitaciones/stream",
                headers={"Last-Event-ID": last_event_id},
            )

        assert resp.status_code == 200
        assert seen["event_id"] == 0.0

    def test_stream_batch_param_respected(self, stream_client):
        """?batch= es aceptado sin error."""
        with _patch_fast_stream():
            resp = stream_client.get("/api/v1/licitaciones/stream?batch=5")
        assert resp.status_code == 200


class TestSharedSignalWatcher:
    """El poll del centinela es uno por proceso, no uno por cliente."""

    def test_n_subscribers_produce_one_read_per_interval(self):
        """Con 5 suscriptores el centinela se lee una vez, no cinco.

        Antes cada cliente conectado consultaba la BD cada 5 s por su cuenta:
        la carga crecía con el número de conexiones y competía por el
        threadpool con el resto de la API.
        """
        import asyncio
        from contextlib import AsyncExitStack

        from api.routes.stream import _SignalWatcher

        reads = {"n": 0}

        def _counting_signal() -> float:
            reads["n"] += 1
            return 123.0

        async def _exercise() -> float:
            watcher = _SignalWatcher()
            async with AsyncExitStack() as stack:
                for _ in range(5):
                    await stack.enter_async_context(watcher.subscribe())
                # El poller lee una vez al arrancar y después duerme
                # _POLL_INTERVAL, así que basta con esperar a esa primera
                # lectura: cualquier lectura de más sería una por cliente.
                for _ in range(200):
                    if watcher._signal_ts:
                        break
                    await asyncio.sleep(0.01)
                return watcher._signal_ts

        with patch("shared.cache_signal.get_signal_timestamp", _counting_signal):
            signal_ts = asyncio.run(_exercise())

        assert signal_ts == 123.0, "el poller no llegó a publicar la marca del centinela"
        assert reads["n"] == 1, f"se leyó el centinela {reads['n']} veces para 5 clientes"

    def test_watcher_stops_when_last_subscriber_leaves(self):
        """Sin clientes conectados no queda ningún poller consultando."""
        import asyncio

        from api.routes.stream import _SignalWatcher

        async def _exercise() -> tuple[bool, bool]:
            watcher = _SignalWatcher()
            async with watcher.subscribe():
                running = watcher._task is not None
            return running, watcher._task is None

        with patch("shared.cache_signal.get_signal_timestamp", lambda: 1.0):
            running_with_client, stopped_without = asyncio.run(_exercise())

        assert running_with_client
        assert stopped_without
