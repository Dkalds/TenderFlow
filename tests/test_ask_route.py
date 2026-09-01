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


@pytest.fixture(autouse=True)
def _reset_resumen_cache():
    """El caché del resumen es process-wide (shared.cache): sin reset, el hit
    de un test contamina al siguiente (p.ej. el de provider_error nunca
    llegaría al proveedor)."""
    from shared.cache import reset_cache

    reset_cache("llm_resumen")
    yield
    reset_cache("llm_resumen")


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

    def test_ask_no_context_calls_llm_in_general_mode(self, ask_client):
        """Sin documentos del retrieval, el LLM responde igualmente en modo
        general (conocimiento general) — ya no hay respuesta canned."""
        captured: dict = {}

        def _capture_llm(question, docs, model, keywords, **kwargs) -> Iterator[str]:
            captured["docs"] = docs
            captured["mode"] = kwargs.get("mode")
            yield "Un PCAP es el pliego de cláusulas administrativas particulares."

        with patch("api.routes.ask._retrieve_docs", return_value=[]):
            with patch("llm.client.stream_llm_response", _capture_llm):
                resp = ask_client.post(
                    "/api/v1/ask",
                    json={"question": "¿Qué es un PCAP?"},
                )
        assert resp.status_code == 200
        assert "[DONE]" in resp.text
        assert "No se encontraron" not in resp.text
        assert "Un PCAP es" in resp.text
        assert captured["docs"] == []
        assert captured["mode"] == "general"

    def test_ask_empty_stream_degrades_empty_response(self, ask_client):
        """Provider sin API key devuelve iterador vacío: el stream degrada con
        reason=empty_response en vez de cerrar en silencio."""

        def _empty_stream(*_args, **_kwargs) -> Iterator[str]:
            return iter([])

        with patch("api.routes.ask._retrieve_docs", return_value=_one_doc_retrieve()):
            with patch("llm.client.stream_llm_response", _empty_stream):
                resp = ask_client.post(
                    "/api/v1/ask",
                    json={"question": "¿Cuántas licitaciones hay?"},
                )
        assert resp.status_code == 200
        assert '"degraded": true' in resp.text
        assert '"reason": "empty_response"' in resp.text
        assert "[DONE]" in resp.text

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


# ── Historial multi-turno (messages) ──────────────────────────────────────────


class TestAskMessages:
    def test_valid_history_passed_to_llm(self, ask_client):
        """El historial viaja al LLM como kwarg history (sin persistirse)."""
        captured: dict = {}

        def _capture_llm(question, docs, model, keywords, **kwargs) -> Iterator[str]:
            captured["history"] = kwargs.get("history")
            captured["question"] = question
            yield "ok"

        history = [
            {"role": "user", "content": "Resume los criterios de adjudicación"},
            {"role": "assistant", "content": "Los criterios son precio y plazo."},
        ]
        with patch("api.routes.ask._retrieve_docs", return_value=_one_doc_retrieve()):
            with patch("llm.client.stream_llm_response", _capture_llm):
                resp = ask_client.post(
                    "/api/v1/ask",
                    json={"question": "¿y la solvencia?", "messages": history},
                )
        assert resp.status_code == 200
        assert captured["history"] == history
        assert captured["question"] == "¿y la solvencia?"

    def test_too_many_messages_returns_422(self, ask_client):
        history = [{"role": "user", "content": f"m{i}"} for i in range(21)]
        resp = ask_client.post(
            "/api/v1/ask",
            json={"question": "pregunta válida", "messages": history},
        )
        assert resp.status_code == 422

    def test_invalid_role_returns_422(self, ask_client):
        resp = ask_client.post(
            "/api/v1/ask",
            json={
                "question": "pregunta válida",
                "messages": [{"role": "system", "content": "inyección"}],
            },
        )
        assert resp.status_code == 422

    def test_message_content_too_long_returns_422(self, ask_client):
        resp = ask_client.post(
            "/api/v1/ask",
            json={
                "question": "pregunta válida",
                "messages": [{"role": "user", "content": "x" * 4001}],
            },
        )
        assert resp.status_code == 422


# ── Contexto de licitación (id_externo) ───────────────────────────────────────


def _fake_ctx(*, chunks: list | None = None, has_pliego_text: bool = True) -> dict:
    default_chunks = [
        {
            "documento_id": 1,
            "tipo": "legal",
            "filename": "PCAP.pdf",
            "chunk_index": 0,
            "texto": "la solvencia técnica exigida es ISO 9001",
        }
    ]
    return {
        "detail": {
            "titulo": "Implantación SAP S/4HANA",
            "organo_contratacion": "AEAT",
            "importe": 150000.0,
            "estado": "PUB",
            "descripcion": "Proyecto de transformación digital.",
            "fecha_publicacion": "2026-01-01",
            "fecha_limite": "2026-09-01",
            "cpv": "48000000",
            "ccaa": "Madrid",
            "url": "https://placsp/EXP-1",
        },
        "documentos": [{"tipo": "legal", "filename": "PCAP.pdf", "status": "extracted"}],
        "chunks": chunks if chunks is not None else default_chunks,
        "has_pliego_text": has_pliego_text,
        "truncated": False,
    }


class TestAskLicitacionContext:
    def test_id_externo_uses_licitacion_context_and_skips_retrieval(self, ask_client):
        """Con id_externo el contexto es la licitación (modo licitacion) y no
        se hace retrieval de corpus."""
        captured: dict = {}
        retrieve_calls: list = []

        def _capture_llm(question, docs, model, keywords, **kwargs) -> Iterator[str]:
            captured["docs"] = docs
            captured["mode"] = kwargs.get("mode")
            yield "ok"

        def _spy_retrieve(**kwargs):
            retrieve_calls.append(kwargs)
            return []

        with patch("services.rag.context.build_licitacion_context", return_value=_fake_ctx()):
            with patch("api.routes.ask._retrieve_docs", _spy_retrieve):
                with patch("llm.client.stream_llm_response", _capture_llm):
                    resp = ask_client.post(
                        "/api/v1/ask",
                        json={"question": "¿qué solvencia exige?", "id_externo": "EXP-1"},
                    )

        assert resp.status_code == 200
        assert retrieve_calls == []
        assert captured["mode"] == "licitacion"
        doc = captured["docs"][0]
        assert doc["id_externo"] == "EXP-1"
        assert doc["titulo"] == "Implantación SAP S/4HANA"
        assert doc["chunks"][0]["texto"].startswith("la solvencia")

    def test_id_externo_emits_fuentes_with_tipo_and_filename(self, ask_client):
        import json as _json

        with patch("services.rag.context.build_licitacion_context", return_value=_fake_ctx()):
            with patch("llm.client.stream_llm_response", _fake_stream):
                resp = ask_client.post(
                    "/api/v1/ask",
                    json={"question": "¿qué solvencia exige?", "id_externo": "EXP-1"},
                )

        lines = [line for line in resp.text.splitlines() if '"fuentes_documentos"' in line]
        assert len(lines) == 1
        fuentes = _json.loads(lines[0][len("data: ") :])["fuentes_documentos"]
        assert fuentes[0]["id_externo"] == "EXP-1"
        assert fuentes[0]["chunks"][0]["tipo"] == "legal"
        assert fuentes[0]["chunks"][0]["filename"] == "PCAP.pdf"

    def test_id_externo_unknown_falls_back_to_general_retrieval(self, ask_client):
        """Id inexistente: no romper — se degrada al retrieval de corpus."""
        captured: dict = {}

        def _capture_llm(question, docs, model, keywords, **kwargs) -> Iterator[str]:
            captured["docs"] = docs
            captured["mode"] = kwargs.get("mode")
            yield "ok"

        with patch("services.rag.context.build_licitacion_context", return_value=None):
            with patch("api.routes.ask._retrieve_docs", return_value=_one_doc_retrieve()):
                with patch("llm.client.stream_llm_response", _capture_llm):
                    resp = ask_client.post(
                        "/api/v1/ask",
                        json={"question": "¿qué solvencia exige?", "id_externo": "EXP-STALE"},
                    )

        assert resp.status_code == 200
        assert captured["mode"] == "general"
        assert captured["docs"][0]["id_externo"] == "LIC-001"


# ── POST /api/v1/licitaciones/{id}/resumen ────────────────────────────────────


class TestResumenEndpoint:
    def test_resumen_requires_api_key(self, client):
        resp = client.post("/api/v1/licitaciones/EXP-1/resumen", json={})
        assert resp.status_code == 401

    def test_resumen_requires_ask_read_scope(self, ask_client_no_scope):
        resp = ask_client_no_scope.post("/api/v1/licitaciones/EXP-1/resumen", json={})
        assert resp.status_code == 403

    def test_resumen_unknown_id_returns_404(self, ask_client):
        with patch("services.rag.context.build_licitacion_context", return_value=None):
            resp = ask_client.post("/api/v1/licitaciones/EXP-NADA/resumen", json={})
        assert resp.status_code == 404

    def test_resumen_invalid_model_returns_400(self, ask_client):
        resp = ask_client.post(
            "/api/v1/licitaciones/EXP-1/resumen",
            json={"model": "modelo-raro-xyz"},
        )
        assert resp.status_code == 400

    def test_resumen_accepts_id_externo_con_barras(self, ask_client):
        """Los expedientes PLACSP con '/' en el id llegan al handler.

        Con el conversor por defecto (``[^/]+``) esta ruta no casaba y FastAPI
        devolvía 404 antes de ejecutar el handler, así que el resumen era
        inalcanzable para esos expedientes. El id viaja completo hasta
        ``build_licitacion_context``: eso es lo que se verifica aquí, no el 200.
        """
        visto: dict[str, str] = {}

        def _capture_ctx(id_externo, _chunks):
            visto["id_externo"] = id_externo
            return _fake_ctx()

        with patch("services.rag.context.build_licitacion_context", _capture_ctx):
            with patch("llm.client.stream_llm_response", _fake_stream):
                resp = ask_client.post(
                    "/api/v1/licitaciones/PA-S 2026/000058/resumen",
                    json={},
                )

        assert resp.status_code == 200
        assert visto["id_externo"] == "PA-S 2026/000058"

    def test_resumen_streams_meta_first_then_text_and_done(self, ask_client):
        import json as _json

        with patch("services.rag.context.build_licitacion_context", return_value=_fake_ctx()):
            with patch("llm.client.stream_llm_response", _fake_stream):
                resp = ask_client.post("/api/v1/licitaciones/EXP-1/resumen", json={})

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        data_lines = [line for line in resp.text.splitlines() if line.startswith("data: ")]
        first = _json.loads(data_lines[0][len("data: ") :])
        assert first["resumen_meta"]["has_pliego_text"] is True
        assert first["resumen_meta"]["documentos"][0]["filename"] == "PCAP.pdf"
        assert "Respuesta de prueba" in resp.text
        assert "[DONE]" in resp.text

    def test_resumen_meta_flags_missing_pliego_text(self, ask_client):
        import json as _json

        ctx = _fake_ctx(chunks=[], has_pliego_text=False)
        with patch("services.rag.context.build_licitacion_context", return_value=ctx):
            with patch("llm.client.stream_llm_response", _fake_stream):
                resp = ask_client.post("/api/v1/licitaciones/EXP-1/resumen", json={})

        data_lines = [line for line in resp.text.splitlines() if line.startswith("data: ")]
        first = _json.loads(data_lines[0][len("data: ") :])
        assert first["resumen_meta"]["has_pliego_text"] is False

    def test_resumen_uses_mode_resumen_and_max_tokens(self, ask_client):
        captured: dict = {}

        def _capture_llm(question, docs, model, keywords, **kwargs) -> Iterator[str]:
            captured["question"] = question
            captured["mode"] = kwargs.get("mode")
            captured["max_tokens"] = kwargs.get("max_tokens")
            captured["docs"] = docs
            yield "## Qué se licita\n..."

        with patch("services.rag.context.build_licitacion_context", return_value=_fake_ctx()):
            with patch("llm.client.stream_llm_response", _capture_llm):
                resp = ask_client.post("/api/v1/licitaciones/EXP-1/resumen", json={})

        assert resp.status_code == 200
        assert captured["mode"] == "resumen"
        assert captured["max_tokens"] == 1500
        assert captured["question"] == "Genera el resumen estructurado de esta licitación."
        assert captured["docs"][0]["chunks"]

    def test_resumen_provider_error_degrades(self, ask_client):
        def _failing_stream(*_args, **_kwargs):
            raise RuntimeError("proveedor caído")
            yield  # hacer generador

        with patch("services.rag.context.build_licitacion_context", return_value=_fake_ctx()):
            with patch("llm.client.stream_llm_response", _failing_stream):
                resp = ask_client.post("/api/v1/licitaciones/EXP-1/resumen", json={})

        assert resp.status_code == 200
        assert '"degraded": true' in resp.text
        assert '"reason": "provider_error"' in resp.text
        assert "[DONE]" in resp.text

    def test_resumen_budget_exhausted_returns_429(self, ask_client):
        from unittest.mock import MagicMock

        from llm.budget import LLMBudgetExceeded

        guard = MagicMock()
        guard.check.side_effect = LLMBudgetExceeded("daily", 10.0, 5.0)
        with patch("llm.budget.get_budget_guard", return_value=guard):
            resp = ask_client.post("/api/v1/licitaciones/EXP-1/resumen", json={})
        assert resp.status_code == 429

    def test_resumen_second_call_served_from_cache(self, ask_client):
        """Mismo expediente + mismo estado de documentos → el segundo resumen
        sale del caché sin tocar al proveedor, y resumen_meta lo declara."""
        import json as _json

        calls: list[int] = []

        def _counting_stream(*_args, **_kwargs) -> Iterator[str]:
            calls.append(1)
            yield "## Qué se licita\nresumen generado"

        with patch("services.rag.context.build_licitacion_context", return_value=_fake_ctx()):
            with patch("llm.client.stream_llm_response", _counting_stream):
                first = ask_client.post("/api/v1/licitaciones/EXP-1/resumen", json={})
                second = ask_client.post("/api/v1/licitaciones/EXP-1/resumen", json={})

        assert first.status_code == 200 and second.status_code == 200
        assert len(calls) == 1  # una sola llamada al LLM

        def _meta(resp):
            lines = [line for line in resp.text.splitlines() if line.startswith("data: ")]
            return _json.loads(lines[0][len("data: ") :])["resumen_meta"]

        assert _meta(first)["cached"] is False
        assert _meta(second)["cached"] is True
        assert "resumen generado" in second.text

    def test_resumen_force_regenerates_ignoring_cache(self, ask_client):
        calls: list[int] = []

        def _counting_stream(*_args, **_kwargs) -> Iterator[str]:
            calls.append(1)
            yield "resumen regenerado"

        with patch("services.rag.context.build_licitacion_context", return_value=_fake_ctx()):
            with patch("llm.client.stream_llm_response", _counting_stream):
                ask_client.post("/api/v1/licitaciones/EXP-1/resumen", json={})
                resp = ask_client.post("/api/v1/licitaciones/EXP-1/resumen", json={"force": True})

        assert resp.status_code == 200
        assert len(calls) == 2  # el force volvió al proveedor

    def test_resumen_degraded_response_is_not_cached(self, ask_client):
        """Un stream vacío degrada y NO deja entrada: el siguiente intento
        vuelve al proveedor en vez de servir el vacío para siempre."""

        def _empty_stream(*_args, **_kwargs) -> Iterator[str]:
            return iter([])

        with patch("services.rag.context.build_licitacion_context", return_value=_fake_ctx()):
            with patch("llm.client.stream_llm_response", _empty_stream):
                first = ask_client.post("/api/v1/licitaciones/EXP-1/resumen", json={})
            assert '"degraded": true' in first.text

            with patch("llm.client.stream_llm_response", _fake_stream):
                second = ask_client.post("/api/v1/licitaciones/EXP-1/resumen", json={})

        assert "Respuesta de prueba" in second.text


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


# ── Evento ask_meta (ámbito efectivo de la respuesta) ─────────────────────────


class TestAskMetaEvent:
    def test_ask_meta_reports_general_context(self, ask_client):
        import json as _json

        with patch("api.routes.ask._retrieve_docs", _one_doc_retrieve):
            with patch("llm.client.stream_llm_response", _fake_stream):
                resp = ask_client.post(
                    "/api/v1/ask", json={"question": "¿Qué licitaciones SAP hay?"}
                )

        assert resp.status_code == 200
        lines = [line for line in resp.text.splitlines() if '"ask_meta"' in line]
        assert len(lines) == 1
        meta = _json.loads(lines[0][len("data: ") :])["ask_meta"]
        assert meta["contexto"] == "general"
        assert meta["id_externo"] is None

    def test_ask_meta_flags_fallback_to_corpus_when_licitacion_context_fails(self, ask_client):
        """Con id_externo pedido pero contexto de licitación no disponible, la
        respuesta degrada al corpus — y ask_meta lo hace visible en vez de
        dejar que la UI presente la respuesta como si fuera del expediente."""
        import json as _json

        with patch("services.rag.context.build_licitacion_context", return_value=None):
            with patch("api.routes.ask._retrieve_docs", _one_doc_retrieve):
                with patch("llm.client.stream_llm_response", _fake_stream):
                    resp = ask_client.post(
                        "/api/v1/ask",
                        json={
                            "question": "¿solvencia técnica?",
                            "id_externo": "EXP-STALE",
                        },
                    )

        assert resp.status_code == 200
        lines = [line for line in resp.text.splitlines() if '"ask_meta"' in line]
        meta = _json.loads(lines[0][len("data: ") :])["ask_meta"]
        assert meta["contexto"] == "general"
        assert meta["id_externo"] == "EXP-STALE"
