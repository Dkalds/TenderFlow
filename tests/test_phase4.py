"""Tests para Phase 4: búsqueda semántica SSE y endpoint POST /search/semantic."""

from __future__ import annotations

import json
import time
from unittest.mock import patch

# ─── helpers ─────────────────────────────────────────────────────────────────

_FAKE_HITS = [
    {
        "id_externo": "LIC-001",
        "titulo": "Consultoría SAP S/4HANA",
        "organo_contratacion": "AEAT",
        "importe": 250000.0,
        "descripcion": "Implantación SAP",
        "url": "https://example.com/lic/001",
        "fecha_publicacion": "2026-01-15",
        "ccaa": "Madrid",
        "estado": "EV",
        "score": 0.92,
    },
    {
        "id_externo": "LIC-002",
        "titulo": "Soporte SAP ABAP",
        "organo_contratacion": "SEPE",
        "importe": 85000.0,
        "descripcion": "Mantenimiento correctivo",
        "url": "https://example.com/lic/002",
        "fecha_publicacion": "2026-01-20",
        "ccaa": "Cataluña",
        "estado": "ADJ",
        "score": 0.78,
    },
]


# ─── POST /api/v1/search/semantic ────────────────────────────────────────────


class TestSemanticSearchEndpoint:
    """Tests para el endpoint de búsqueda semántica."""

    def test_requires_api_key(self, client):
        resp = client.post("/api/v1/search/semantic", json={"q": "SAP"})
        assert resp.status_code == 401

    def test_empty_query_rejected(self, client, auth):
        resp = client.post("/api/v1/search/semantic", json={"q": ""}, headers=auth)
        assert resp.status_code == 422

    def test_query_too_long_rejected(self, client, auth):
        resp = client.post("/api/v1/search/semantic", json={"q": "x" * 501}, headers=auth)
        assert resp.status_code == 422

    def test_top_k_out_of_range_rejected(self, client, auth):
        resp = client.post("/api/v1/search/semantic", json={"q": "SAP", "top_k": 100}, headers=auth)
        assert resp.status_code == 422

    def test_alpha_out_of_range_rejected(self, client, auth):
        resp = client.post("/api/v1/search/semantic", json={"q": "SAP", "alpha": 1.5}, headers=auth)
        assert resp.status_code == 422

    def test_returns_200_with_fts(self, client, auth):
        """Cuando FTS devuelve hits, se devuelve respuesta 200 con source FTS5."""
        fts_hits = [("LIC-001", 0.92), ("LIC-002", 0.78)]

        with (
            patch("services.investigador.search_engine.fts5_search", return_value=fts_hits),
            patch(
                "services.investigador.search_engine.fetch_docs",
                return_value={h["id_externo"]: h for h in _FAKE_HITS},
            ),
        ):
            resp = client.post(
                "/api/v1/search/semantic",
                json={"q": "SAP S/4HANA", "top_k": 5},
                headers=auth,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "FTS5"
        assert len(data["hits"]) == 2
        assert data["hits"][0]["id_externo"] == "LIC-001"
        assert "score" in data["hits"][0]
        assert data["elapsed_ms"] >= 0

    def test_falls_back_to_fts_when_hits_present(self, client, auth):
        """Con FTS hits, devuelve source FTS5."""
        fts_hits = [("LIC-002", 0.65)]

        with (
            patch("services.investigador.search_engine.fts5_search", return_value=fts_hits),
            patch(
                "services.investigador.search_engine.fetch_docs",
                return_value={"LIC-002": _FAKE_HITS[1]},
            ),
        ):
            resp = client.post(
                "/api/v1/search/semantic",
                json={"q": "ABAP", "top_k": 5},
                headers=auth,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "FTS5"
        assert len(data["hits"]) == 1

    def test_falls_back_to_like_when_all_empty(self, client, auth):
        """Sin FTS hits, usa LIKE."""
        like_hits = [("LIC-001", 0.5)]

        with (
            patch("services.investigador.search_engine.fts5_search", return_value=[]),
            patch("services.investigador.search_engine.like_search", return_value=like_hits),
            patch(
                "services.investigador.search_engine.fetch_docs",
                return_value={"LIC-001": _FAKE_HITS[0]},
            ),
        ):
            resp = client.post(
                "/api/v1/search/semantic",
                json={"q": "SAP"},
                headers=auth,
            )

        assert resp.status_code == 200
        assert resp.json()["source"] == "LIKE"

    def test_returns_503_on_search_exception(self, client, auth):
        """Si el motor falla, devuelve 503."""
        with patch(
            "services.investigador.search_engine.fts5_search",
            side_effect=RuntimeError("FTS not available"),
        ):
            resp = client.post(
                "/api/v1/search/semantic",
                json={"q": "SAP"},
                headers=auth,
            )
        assert resp.status_code == 503

    def test_response_schema(self, client, auth):
        """Verifica que la respuesta cumple el schema SemanticSearchResponse."""
        with (
            patch("services.investigador.search_engine.fts5_search", return_value=[]),
            patch("services.investigador.search_engine.like_search", return_value=[]),
            patch("services.investigador.search_engine.fetch_docs", return_value={}),
        ):
            resp = client.post(
                "/api/v1/search/semantic",
                json={"q": "consulta vacia"},
                headers=auth,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) >= {"q", "top_k", "source", "hits", "elapsed_ms"}
        assert isinstance(data["hits"], list)

    def test_custom_alpha_passed(self, client, auth):
        """El parametro alpha se acepta sin error 422."""
        with (
            patch("services.investigador.search_engine.fts5_search", return_value=[]),
            patch("services.investigador.search_engine.like_search", return_value=[]),
            patch("services.investigador.search_engine.fetch_docs", return_value={}),
        ):
            resp = client.post(
                "/api/v1/search/semantic",
                json={"q": "SAP", "alpha": 0.5},
                headers=auth,
            )
        assert resp.status_code == 200


# ─── GET /api/v1/licitaciones/stream (SSE) ────────────────────────────────────


class TestSSEStream:
    """Tests para el endpoint SSE /licitaciones/stream."""

    def test_requires_api_key(self, client):
        resp = client.get("/api/v1/licitaciones/stream")
        assert resp.status_code == 401

    def test_returns_event_stream_content_type(self, client, auth):
        """El endpoint debe responder con text/event-stream."""
        with (
            patch("shared.cache_signal.check_cache_signal", return_value=False),
            # forzar cierre inmediato para el test
            patch("api.routes.stream._MAX_DURATION_SECONDS", 0),
        ):
            resp = client.get("/api/v1/licitaciones/stream", headers=auth)

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_sends_initial_heartbeat(self, client, auth):
        """El primer evento debe ser un heartbeat."""
        with (
            patch("shared.cache_signal.check_cache_signal", return_value=False),
            patch("api.routes.stream._MAX_DURATION_SECONDS", 0),
        ):
            resp = client.get("/api/v1/licitaciones/stream", headers=auth)

        body = resp.text
        assert "event: heartbeat" in body
        assert "data:" in body

    def test_emits_licitaciones_nuevas_on_signal(self, client, auth):
        """Cuando hay señal de nueva ingesta, emite evento licitaciones_nuevas."""
        fake_items = [
            {
                "id_externo": "LIC-X",
                "titulo": "Test",
                "organo_contratacion": None,
                "importe": None,
                "url": None,
                "fecha_publicacion": None,
                "ccaa": None,
                "estado": None,
            }
        ]

        call_count = 0

        def _mock_check(last_check):
            nonlocal call_count
            call_count += 1
            # Primera llamada: hay señal; después: no (para terminar)
            return call_count == 1

        with (
            patch("shared.cache_signal.check_cache_signal", side_effect=_mock_check),
            patch("api.routes.stream._fetch_recent", return_value=fake_items),
            patch("api.routes.stream._MAX_DURATION_SECONDS", 1),
            patch("api.routes.stream._POLL_INTERVAL", 0.01),
        ):
            resp = client.get("/api/v1/licitaciones/stream", headers=auth)

        body = resp.text
        assert "event: licitaciones_nuevas" in body
        event_data = None
        for line in body.splitlines():
            if line.startswith("data:") and "licitaciones_nuevas" not in line:
                try:
                    parsed = json.loads(line[len("data:") :].strip())
                    if "items" in parsed:
                        event_data = parsed
                        break
                except json.JSONDecodeError:
                    pass
        assert event_data is not None
        assert event_data["total_nuevas"] == 1

    def test_cache_control_headers(self, client, auth):
        """El stream autenticado no debe quedar almacenado en cachés compartidas."""
        with (
            patch("shared.cache_signal.check_cache_signal", return_value=False),
            patch("api.routes.stream._MAX_DURATION_SECONDS", 0),
        ):
            resp = client.get("/api/v1/licitaciones/stream", headers=auth)

        assert resp.headers.get("cache-control") == "private, no-store"

    def test_last_event_id_header_accepted(self, client, auth):
        """El header Last-Event-ID debe ser aceptado sin error."""
        ts = str(time.time())
        with (
            patch("shared.cache_signal.check_cache_signal", return_value=False),
            patch("api.routes.stream._MAX_DURATION_SECONDS", 0),
        ):
            resp = client.get(
                "/api/v1/licitaciones/stream",
                headers={**auth, "Last-Event-ID": ts},
            )
        assert resp.status_code == 200

    def test_sse_format_valid(self, client, auth):
        """Los eventos deben estar en formato SSE válido (event:\\ndata:\\n\\n)."""
        with (
            patch("shared.cache_signal.check_cache_signal", return_value=False),
            patch("api.routes.stream._MAX_DURATION_SECONDS", 0),
        ):
            resp = client.get("/api/v1/licitaciones/stream", headers=auth)

        # SSE válido: cada evento tiene "event: X" seguido de "data: {...}"
        lines = resp.text.splitlines()
        event_lines = [ln for ln in lines if ln.startswith("event:")]
        data_lines = [ln for ln in lines if ln.startswith("data:")]
        assert len(event_lines) >= 1
        assert len(data_lines) >= 1
        # Cada data line debe ser JSON válido
        for dl in data_lines:
            payload = dl[len("data:") :].strip()
            parsed = json.loads(payload)
            assert isinstance(parsed, dict)
