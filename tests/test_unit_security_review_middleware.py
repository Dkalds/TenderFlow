"""Regresiones del review de seguridad sobre el stack de middlewares.

Cubre tres defectos que se arreglaron juntos:

* Los límites de endpoints pesados se indexaban por path literal, así que las
  rutas con path params (``/licitaciones/{id}/explain``,
  ``/models/{name}/activate/{version}``) nunca matcheaban.
* CORS y las cabeceras OWASP quedaban por dentro de los middlewares que
  cortocircuitan la request, de modo que un 429 o un 413 salían pelados.
* El handler de ``ValueError`` reflejaba el mensaje verbatim al cliente.

Ninguno de estos tests necesita Postgres: se monta el stack sobre apps
efímeras y se sustituye el rate limiter por un doble.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.applications import Starlette
from starlette.testclient import TestClient

from api.middleware import (
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    _effective_max_calls,
)

_ORIGIN = "https://app.example.test"

# Cabeceras que SecurityHeadersMiddleware debe poner en cualquier respuesta.
_SECURITY_HEADERS = (
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
    "content-security-policy",
)


class _StubLimiter:
    """Rate limiter de test: registra los kwargs y responde lo que se le diga."""

    def __init__(self, *, allow: bool) -> None:
        self.allow = allow
        self.calls: list[dict[str, Any]] = []

    def check(self, key: str, *, max_calls: int = 120, window_seconds: float = 60.0) -> bool:
        self.calls.append({"key": key, "max_calls": max_calls, "window_seconds": window_seconds})
        return self.allow


def _observed_max_calls(monkeypatch: pytest.MonkeyPatch, path: str) -> int:
    """Ejecuta una request contra ``path`` y devuelve el ``max_calls`` aplicado.

    Se monta ``RateLimitMiddleware`` sobre una app sin rutas a propósito: el
    middleware corre antes del routing, así que el 404 posterior es irrelevante
    y evita tener que declarar cada ruta real.
    """
    limiter = _StubLimiter(allow=True)
    monkeypatch.setattr("api.middleware.get_rate_limiter", lambda: limiter)

    app = Starlette(routes=[])
    app.add_middleware(RateLimitMiddleware)
    TestClient(app).get(path)

    assert len(limiter.calls) == 1
    return int(limiter.calls[0]["max_calls"])


# ── C1: límites de endpoints pesados con path params ────────────────────────


class TestHeavyEndpointMatching:
    def test_explain_con_id_externo_recibe_limite_bajo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert _observed_max_calls(monkeypatch, "/api/v1/licitaciones/ABC-123/explain") == 30

    def test_explain_con_id_externo_que_lleva_barra(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # id_externo usa el conversor ``:path`` y admite '/' ("PA-S 2026/000058").
        assert _observed_max_calls(monkeypatch, "/api/v1/licitaciones/PA-S%202026/58/explain") == 30

    def test_activate_con_nombre_y_version_recibe_limite_bajo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert _observed_max_calls(monkeypatch, "/api/v1/models/relevancia/activate/7") == 10

    def test_exports_descarga_sincrona_recibe_limite_bajo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert _observed_max_calls(monkeypatch, "/api/v1/exports/download") == 10

    def test_ruta_no_relacionada_usa_el_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert _observed_max_calls(monkeypatch, "/api/v1/licitaciones") == 120

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/licitaciones/ABC-123",
            "/api/v1/licitaciones/ABC-123/eventos",
            "/api/v1/models/relevancia",
            "/api/v1/models/relevancia/versions",
            # El job asíncrono comparte prefijo con /exports pero no su coste.
            "/api/v1/exports/42",
            "/api/v1/exports/calendario.ics",
        ],
    )
    def test_rutas_vecinas_no_heredan_el_limite_bajo(self, path: str) -> None:
        assert _effective_max_calls(path, 120) == 120

    def test_gana_el_limite_mas_restrictivo(self) -> None:
        assert _effective_max_calls("/api/v1/exports/download", 120) == 10
        assert _effective_max_calls("/api/v1/exports", 120) == 20


# ── C2: orden del stack de middlewares ──────────────────────────────────────


def _app_con_stack_completo() -> FastAPI:
    """App efímera con el stack real de ``api.app`` y una ruta trivial."""
    from api.app import register_middlewares

    target = FastAPI()

    @target.api_route("/api/v1/probe", methods=["GET", "POST"])
    async def _probe() -> dict[str, bool]:
        return {"ok": True}

    register_middlewares(target, cors_origins=[_ORIGIN])
    return target


def _assert_cabeceras_completas(response: Any) -> None:
    assert response.headers.get("access-control-allow-origin") == _ORIGIN
    for header in _SECURITY_HEADERS:
        assert header in response.headers, f"falta {header}"


class TestOrdenDelStack:
    def test_cors_es_el_middleware_mas_externo(self) -> None:
        from api.app import _MaxBodyMiddleware, app

        # user_middleware[0] es el más externo: add_middleware inserta al frente.
        clases = [mw.cls for mw in app.user_middleware]
        assert clases[0] is CORSMiddleware
        assert clases.index(SecurityHeadersMiddleware) < clases.index(RateLimitMiddleware)
        assert clases.index(SecurityHeadersMiddleware) < clases.index(_MaxBodyMiddleware)

    def test_429_lleva_cabeceras_cors_y_de_seguridad(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("api.middleware.get_rate_limiter", lambda: _StubLimiter(allow=False))
        client = TestClient(_app_con_stack_completo())
        resp = client.get("/api/v1/probe", headers={"Origin": _ORIGIN})

        assert resp.status_code == 429
        _assert_cabeceras_completas(resp)

    def test_413_lleva_cabeceras_cors_y_de_seguridad(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("api.middleware.get_rate_limiter", lambda: _StubLimiter(allow=True))
        client = TestClient(_app_con_stack_completo())
        resp = client.post(
            "/api/v1/probe",
            content=b"x" * (2 * 1024 * 1024),
            headers={"Origin": _ORIGIN, "Content-Type": "application/json"},
        )

        assert resp.status_code == 413
        _assert_cabeceras_completas(resp)

    def test_correlation_id_sigue_presente(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("api.middleware.get_rate_limiter", lambda: _StubLimiter(allow=True))
        client = TestClient(_app_con_stack_completo())
        resp = client.get("/api/v1/probe", headers={"Origin": _ORIGIN})

        assert resp.status_code == 200
        assert resp.headers.get("X-Correlation-Id")


# ── C3: el handler de ValueError no filtra el mensaje ───────────────────────

_MENSAJE_SENSIBLE = "Host resuelve a una dirección no global: 10.0.0.7"


class TestValueErrorNoFiltra:
    @pytest.fixture()
    def client(self) -> TestClient:
        from api.errors import register_exception_handlers

        target = FastAPI()

        @target.get("/boom")
        async def _boom() -> dict[str, bool]:
            raise ValueError(_MENSAJE_SENSIBLE)

        register_exception_handlers(target)
        return TestClient(target, raise_server_exceptions=False)

    def test_sigue_devolviendo_400(self, client: TestClient) -> None:
        assert client.get("/boom").status_code == 400

    def test_el_mensaje_no_llega_al_cliente(self, client: TestClient) -> None:
        resp = client.get("/boom")
        assert "10.0.0.7" not in resp.text
        assert "no global" not in resp.text
        assert _MENSAJE_SENSIBLE not in resp.text

    def test_devuelve_problem_json_generico(self, client: TestClient) -> None:
        body = client.get("/boom").json()
        assert body["status"] == 400
        assert body["title"] == "Bad Request"
        assert body["detail"] == "La solicitud contiene un valor inválido."
