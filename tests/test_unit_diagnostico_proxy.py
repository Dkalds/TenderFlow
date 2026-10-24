"""Diagnóstico temporal de cabeceras de reenvío (``api/diagnostico_proxy.py``).

Lo que hay que garantizar es doble: que la línea dice lo suficiente para
decidir de dónde sale la IP del cliente (RFC 2026-10-24), y que **ninguna IP
sale entera** al log.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient

from api.diagnostico_proxy import describir_ip
from api.middleware import ObservabilityMiddleware

VISITANTE = "81.33.120.45"
VERCEL = "3.120.10.20"
CLOUDFLARE = "172.71.150.7"
RENDER = "10.192.214.29"


def _app() -> TestClient:
    async def handler(request: Request) -> Response:
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[Route("/api/v1/auth/me", handler), Route("/api/v1/licitaciones", handler)]
    )
    app.add_middleware(ObservabilityMiddleware)
    return TestClient(app)


def _lineas_diag(mock_log: MagicMock) -> list[dict[str, object]]:
    llamadas = mock_log.info.call_args_list
    return [c.kwargs for c in llamadas if c.args and c.args[0] == "proxy_cabeceras_diag"]


class TestDescribirIp:
    def test_publica_truncada_a_16_sin_la_ip(self) -> None:
        d = describir_ip(VISITANTE)
        assert d is not None
        assert d["clase"] == "publica"
        assert d["red"] == "81.33.0.0/16"
        assert len(d["h"]) == 8
        assert VISITANTE not in json.dumps(d)

    def test_privada_y_loopback(self) -> None:
        assert (describir_ip(RENDER) or {})["clase"] == "privada"
        assert (describir_ip("127.0.0.1") or {})["clase"] == "loopback"

    def test_ipv6_truncada_a_32(self) -> None:
        d = describir_ip("[2a02:9130:1:2::5]:443")
        assert d is not None
        assert d["red"] == "2a02:9130::/32"

    def test_host_puerto_ipv4(self) -> None:
        assert describir_ip(f"{VISITANTE}:51234") == describir_ip(VISITANTE)

    def test_misma_ip_misma_huella_distinta_ip_distinta(self) -> None:
        a, b, c = describir_ip(VISITANTE), describir_ip(f" {VISITANTE} "), describir_ip(VERCEL)
        assert a is not None and b is not None and c is not None
        assert a["h"] == b["h"]
        assert a["h"] != c["h"]

    def test_valor_no_ip_no_se_copia(self) -> None:
        d = describir_ip("<script>alert(1)</script>")
        assert d is not None
        assert d["clase"] == "invalida"
        assert "script" not in json.dumps(d)

    def test_vacio_y_ausente(self) -> None:
        assert describir_ip(None) is None
        assert describir_ip("  ") == {"clase": "vacia"}


class TestLineaDeDiagnostico:
    def test_auth_emite_una_linea_sin_ips_en_claro(self) -> None:
        cabeceras = {
            "X-Forwarded-For": f"{VISITANTE}, {VERCEL}, {CLOUDFLARE}, {RENDER}",
            "X-Real-IP": VISITANTE,
            "True-Client-IP": VERCEL,
            "X-Forwarded-Host": "tenderflow.app",
        }
        with patch("api.diagnostico_proxy.log") as mock_log:
            respuesta = _app().get("/api/v1/auth/me", headers=cabeceras)
        assert respuesta.status_code == 200
        lineas = _lineas_diag(mock_log)
        assert len(lineas) == 1
        linea = lineas[0]

        volcado = json.dumps(linea)
        for ip in (VISITANTE, VERCEL, CLOUDFLARE, RENDER):
            assert ip not in volcado

        saltos = linea["xff"]
        assert isinstance(saltos, list)
        assert [s["clase"] for s in saltos] == ["publica", "publica", "publica", "privada"]
        assert linea["xff_saltos"] == 4
        # La huella es lo que permite decir «x-real-ip es el primer salto».
        assert linea["x_real_ip"] == saltos[0]
        assert linea["true_client_ip"] == saltos[1]
        assert linea["x_forwarded_host"] == "tenderflow.app"
        nombres = linea["cabeceras"]
        assert isinstance(nombres, list)
        assert "x-real-ip" in nombres

    def test_fuera_de_auth_no_emite(self) -> None:
        with patch("api.diagnostico_proxy.log") as mock_log:
            _app().get("/api/v1/licitaciones", headers={"X-Forwarded-For": VISITANTE})
        assert _lineas_diag(mock_log) == []

    def test_cabecera_inflada_se_acota(self) -> None:
        xff = ", ".join([VISITANTE] * 50)
        with patch("api.diagnostico_proxy.log") as mock_log:
            _app().get("/api/v1/auth/me", headers={"X-Forwarded-For": xff})
        (linea,) = _lineas_diag(mock_log)
        assert linea["xff_saltos"] == 50
        saltos = linea["xff"]
        assert isinstance(saltos, list)
        assert len(saltos) == 8

    def test_un_fallo_del_diagnostico_no_rompe_la_respuesta(self) -> None:
        with patch("api.diagnostico_proxy.describir_peticion", side_effect=RuntimeError("x")):
            respuesta = _app().get("/api/v1/auth/me")
        assert respuesta.status_code == 200
