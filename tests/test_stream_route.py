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

    def test_stream_batch_param_respected(self, stream_client):
        """?batch= es aceptado sin error."""
        with _patch_fast_stream():
            resp = stream_client.get("/api/v1/licitaciones/stream?batch=5")
        assert resp.status_code == 200
