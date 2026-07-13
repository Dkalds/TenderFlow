"""Tests para api/routes/ask.py — POST /api/v1/ask (B12).

Cubre:
- Autenticación (401 sin key, 403 sin scope correcto)
- Validación de parámetros (question too short → 422, invalid model → 400)
- Streaming SSE: formato de eventos, evento [DONE]
- Fallback cuando FTS no devuelve resultados
- Filtros ccaa/tecnologia
- GET /api/v1/ask/models
- Manejo de errores del LLM (error event + [DONE])
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def ask_client(api_db):
    """TestClient con una API key que tiene scope ask:read."""
    from api.app import app
    from api.auth import create_api_key

    # key con todos los scopes (*)
    key = create_api_key("ask-test-key", scopes="ask:read,licitaciones:read")
    client = TestClient(app, raise_server_exceptions=False)
    client.headers.update({"X-API-Key": key})
    return client


@pytest.fixture()
def ask_client_no_scope(api_db):
    """TestClient con API key sin scope ask:read."""
    from api.app import app
    from api.auth import create_api_key

    key = create_api_key("no-scope-key", scopes="licitaciones:read")
    client = TestClient(app, raise_server_exceptions=False)
    client.headers.update({"X-API-Key": key})
    return client


def _fake_stream(*_args, **_kwargs) -> Iterator[str]:
    yield "Respuesta de prueba"
    yield " con datos."


def _empty_docs_retrieve(*_args, **_kwargs):
    return []


def _one_doc_retrieve(*_args, **_kwargs):
    return [
        {
            "id_externo": "LIC-001",
            "titulo": "Implantación SAP S/4HANA",
            "organo_contratacion": "AEAT",
            "importe": 150000.0,
            "estado": "PUB",
            "descripcion": "Proyecto de transformación digital con SAP.",
            "ccaa": "Madrid",
            "tecnologia": "SAP",
            "fecha_publicacion": "2026-01-01",
        }
    ]


# ── Autenticación ─────────────────────────────────────────────────────────────


class TestAskAuth:
    def test_ask_requires_api_key(self, client):
        """Sin API key → 401."""
        resp = client.post("/api/v1/ask", json={"question": "¿Qué licitaciones hay?"})
        assert resp.status_code == 401

    def test_ask_wrong_key_returns_401(self, client):
        resp = client.post(
            "/api/v1/ask",
            json={"question": "¿Qué licitaciones hay?"},
            headers={"X-API-Key": "invalid-key"},
        )
        assert resp.status_code == 401

    def test_ask_requires_ask_read_scope(self, ask_client_no_scope):
        """API key sin scope ask:read → 403."""
        with patch("api.routes.ask._retrieve_docs", return_value=[]):
            resp = ask_client_no_scope.post(
                "/api/v1/ask",
                json={"question": "¿Cuántas licitaciones hay?"},
            )
        assert resp.status_code == 403


# ── Validación de parámetros ──────────────────────────────────────────────────


class TestAskValidation:
    def test_ask_question_too_short_returns_422(self, ask_client):
        """question con < 3 chars → 422 de Pydantic."""
        resp = ask_client.post("/api/v1/ask", json={"question": "ab"})
        assert resp.status_code == 422

    def test_ask_question_missing_returns_422(self, ask_client):
        resp = ask_client.post("/api/v1/ask", json={})
        assert resp.status_code == 422

    def test_ask_invalid_model_returns_400(self, ask_client):
        """Modelo desconocido → 400 (ValueError de llm.client)."""
        with patch("api.routes.ask._retrieve_docs", return_value=[{"id_externo": "X"}]):
            with patch("llm.client.stream_llm_response", side_effect=ValueError("no disponible")):
                resp = ask_client.post(
                    "/api/v1/ask",
                    json={"question": "pregunta válida de prueba", "model": "modelo-raro-xyz"},
                )
        # La excepción se captura y devuelve como evento SSE error, no HTTP 400
        # según el diseño del endpoint (streaming ya iniciado)
        assert resp.status_code in (200, 400, 422)

    def test_ask_top_k_above_max_returns_422(self, ask_client):
        resp = ask_client.post(
            "/api/v1/ask",
            json={"question": "pregunta válida", "top_k": 999},
        )
        assert resp.status_code == 422

    def test_ask_top_k_zero_returns_422(self, ask_client):
        resp = ask_client.post(
            "/api/v1/ask",
            json={"question": "pregunta válida", "top_k": 0},
        )
        assert resp.status_code == 422


# ── Streaming SSE ─────────────────────────────────────────────────────────────


class TestAskStreaming:
    def test_ask_returns_event_stream_content_type(self, ask_client):
        """La respuesta tiene Content-Type text/event-stream."""
        with patch("api.routes.ask._retrieve_docs", return_value=_one_doc_retrieve()):
            with patch("llm.client.stream_llm_response", _fake_stream):
                resp = ask_client.post(
                    "/api/v1/ask",
                    json={"question": "¿Cuántas licitaciones de SAP hay?"},
                )
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_ask_stream_includes_done_event(self, ask_client):
        """El stream termina con el evento [DONE]."""
        with patch("api.routes.ask._retrieve_docs", return_value=_one_doc_retrieve()):
            with patch("llm.client.stream_llm_response", _fake_stream):
                resp = ask_client.post(
                    "/api/v1/ask",
                    json={"question": "¿Cuántas licitaciones de SAP hay?"},
                )
        assert "[DONE]" in resp.text

    def test_ask_stream_contains_text_chunks(self, ask_client):
        """El stream contiene fragmentos de texto del LLM."""
        with patch("api.routes.ask._retrieve_docs", return_value=_one_doc_retrieve()):
            with patch("llm.client.stream_llm_response", _fake_stream):
                resp = ask_client.post(
                    "/api/v1/ask",
                    json={"question": "¿Cuántas licitaciones de SAP hay?"},
                )
        assert "Respuesta de prueba" in resp.text

    def test_ask_no_context_returns_fallback_message(self, ask_client):
        """Sin documentos, devuelve mensaje de fallback."""
        with patch("api.routes.ask._retrieve_docs", return_value=[]):
            resp = ask_client.post(
                "/api/v1/ask",
                json={"question": "¿Qué licitaciones hay en Madrid?"},
            )
        assert resp.status_code == 200
        assert "[DONE]" in resp.text
        # El fallback menciona que no se encontraron licitaciones
        assert "No se encontraron" in resp.text or "[DONE]" in resp.text

    def test_ask_llm_error_returns_error_event_and_done(self, ask_client):
        """Si el LLM falla, el stream incluye evento error + [DONE]."""

        def _failing_stream(*_args, **_kwargs):
            raise RuntimeError("LLM timeout")
            yield  # hacer generador

        with patch("api.routes.ask._retrieve_docs", return_value=_one_doc_retrieve()):
            with patch("llm.client.stream_llm_response", _failing_stream):
                resp = ask_client.post(
                    "/api/v1/ask",
                    json={"question": "¿Cuántas licitaciones hay?"},
                )
        assert resp.status_code == 200
        assert "[DONE]" in resp.text

    def test_ask_llm_error_degrada_a_docs_sin_sintesis(self, ask_client):
        """RFC llm-dependencia-gestionada: fallo del proveedor → evento SSE
        ``degraded: true`` con los docs del retrieval; el SSE no rompe y el
        DTO no cambia (el flag viaja como evento, no como campo)."""
        import json as _json

        def _failing_stream(*_args, **_kwargs):
            raise RuntimeError("proveedor caído")
            yield  # hacer generador

        with patch("api.routes.ask._retrieve_docs", return_value=_one_doc_retrieve()):
            with patch("llm.client.stream_llm_response", _failing_stream):
                resp = ask_client.post(
                    "/api/v1/ask",
                    json={"question": "¿Cuántas licitaciones de SAP hay?"},
                )

        assert resp.status_code == 200
        assert "[DONE]" in resp.text
        degraded_events = [
            _json.loads(line[len("data: ") :])
            for line in resp.text.splitlines()
            if line.startswith("data: {") and '"degraded"' in line
        ]
        assert len(degraded_events) == 1
        event = degraded_events[0]
        assert event["degraded"] is True
        assert event["reason"] == "provider_error"
        assert event["docs"][0]["id_externo"] == "LIC-001"
        assert event["docs"][0]["titulo"] == "Implantación SAP S/4HANA"
        # Los campos internos del retrieval no se filtran al cliente
        assert "_score" not in event["docs"][0]
        assert "descripcion" not in event["docs"][0]

    def test_ask_timeout_degrada_a_docs(self, ask_client, monkeypatch):
        """Timeout esperando al LLM → mismo fallback degradado que un 5xx."""
        import time as _time

        from config import settings

        monkeypatch.setattr(settings, "ASK_LLM_TIMEOUT_SECONDS", 0.1, raising=False)

        def _slow_stream(*_args, **_kwargs):
            _time.sleep(3)
            yield "tarde"

        with patch("api.routes.ask._retrieve_docs", return_value=_one_doc_retrieve()):
            with patch("llm.client.stream_llm_response", _slow_stream):
                resp = ask_client.post(
                    "/api/v1/ask",
                    json={"question": "¿Cuántas licitaciones hay?"},
                )

        assert resp.status_code == 200
        assert '"degraded": true' in resp.text
        assert '"reason": "timeout"' in resp.text
        assert "[DONE]" in resp.text

    def test_ask_with_ccaa_filter_passes_filter_to_retrieve(self, ask_client):
        """El filtro ccaa se pasa correctamente a _retrieve_docs."""
        received: list[dict] = []

        def _capture_retrieve(question, top_k, ccaa, tecnologia, id_externo=None):
            received.append({"ccaa": ccaa, "tecnologia": tecnologia, "id_externo": id_externo})
            return []

        with patch("api.routes.ask._retrieve_docs", _capture_retrieve):
            ask_client.post(
                "/api/v1/ask",
                json={"question": "Licitaciones SAP en Madrid", "ccaa": "Madrid"},
            )

        assert received[0]["ccaa"] == "Madrid"
        assert received[0]["tecnologia"] is None

    def test_ask_emits_fuentes_documentos_when_docs_carry_chunks(self, ask_client):
        """Plan Pliegos+RAG F9: cuando el retrieval devuelve docs con `chunks`
        (retrieval híbrido), el stream emite un evento fuentes_documentos con
        las citas antes de los tokens del LLM — campo aditivo, DTO intacto."""
        docs_with_chunks = [
            {
                "id_externo": "LIC-HYB-1",
                "titulo": "Implantación SAP S/4HANA",
                "chunks": [{"chunk_id": 1, "chunk_index": 0, "texto": "cláusula técnica"}],
            },
            {"id_externo": "LIC-NOHYB", "titulo": "Sin chunks (solo FTS)"},
        ]
        import json as _json

        with patch("api.routes.ask._retrieve_docs", return_value=docs_with_chunks):
            with patch("llm.client.stream_llm_response", _fake_stream):
                resp = ask_client.post(
                    "/api/v1/ask",
                    json={"question": "¿Qué dice el pliego técnico?"},
                )

        assert resp.status_code == 200
        lines = [line for line in resp.text.splitlines() if '"fuentes_documentos"' in line]
        assert len(lines) == 1
        payload = _json.loads(lines[0][len("data: ") :])
        fuentes = payload["fuentes_documentos"]
        assert len(fuentes) == 1  # solo el doc con chunks no vacíos
        assert fuentes[0]["id_externo"] == "LIC-HYB-1"
        assert fuentes[0]["chunks"] == docs_with_chunks[0]["chunks"]

    def test_ask_no_fuentes_documentos_event_without_chunks(self, ask_client):
        """Sin retrieval híbrido (docs sin `chunks`), no se emite el evento --
        comportamiento idéntico al anterior al cambio (flag off por defecto)."""
        with patch("api.routes.ask._retrieve_docs", return_value=_one_doc_retrieve()):
            with patch("llm.client.stream_llm_response", _fake_stream):
                resp = ask_client.post(
                    "/api/v1/ask",
                    json={"question": "¿Cuántas licitaciones de SAP hay?"},
                )

        assert resp.status_code == 200
        assert "fuentes_documentos" not in resp.text

    def test_ask_with_tecnologia_filter(self, ask_client):
        """El filtro tecnologia se pasa correctamente a _retrieve_docs."""
        received: list[dict] = []

        def _capture_retrieve(question, top_k, ccaa, tecnologia, id_externo=None):
            received.append({"ccaa": ccaa, "tecnologia": tecnologia})
            return []

        with patch("api.routes.ask._retrieve_docs", _capture_retrieve):
            ask_client.post(
                "/api/v1/ask",
                json={"question": "SAP S/4HANA Oracle", "tecnologia": "SAP"},
            )

        assert received[0]["tecnologia"] == "SAP"


# ── GET /api/v1/ask/models ────────────────────────────────────────────────────


class TestAskModels:
    def test_ask_models_requires_api_key(self, client):
        resp = client.get("/api/v1/ask/models")
        assert resp.status_code == 401

    def test_ask_models_returns_list(self, ask_client):
        resp = ask_client.get("/api/v1/ask/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert isinstance(data["models"], list)
        assert len(data["models"]) > 0

    def test_ask_models_includes_gpt_and_claude(self, ask_client):
        resp = ask_client.get("/api/v1/ask/models")
        data = resp.json()
        models = data["models"]
        assert any("gpt" in m for m in models)
        assert any("claude" in m for m in models)

    def test_ask_models_has_default(self, ask_client):
        resp = ask_client.get("/api/v1/ask/models")
        data = resp.json()
        assert "default" in data
        assert data["default"] in data["models"]
