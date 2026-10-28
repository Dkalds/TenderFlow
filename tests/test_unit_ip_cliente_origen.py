"""IP del cliente tras Vercel y Render: opción B del RFC 2026-10-24.

Detrás de Render el peer es siempre un nodo interno ``10.19x`` de su proxy, y
recorrer ``X-Forwarded-For`` solo llega al egreso de Vercel, compartido por
todos. Con el secreto que Vercel añade al reenviar ``/api/*`` (``web/vercel.json``)
y que manda el prefetch SSR (``web/src/lib/server-prefetch.ts``), la API toma la
IP del visitante de ``x-real-ip``. Sin él, o con uno que no casa, todo sigue
como antes: el fallo de configuración degrada al estado previo, no bloquea.
"""

from __future__ import annotations

import hmac
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient

from api.middleware import CABECERA_SECRETO_ORIGEN, ObservabilityMiddleware, _trusted_client_ip
from config.settings import Settings

SECRETO = "a" * 64
SECRETO_ANTERIOR = "b" * 64
VISITANTE = "81.33.120.45"
OTRO_VISITANTE = "88.12.7.200"
NODO_RENDER = "10.192.214.29"


def _settings_con_secretos(actual: str = SECRETO, anterior: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        FORWARDED_ALLOW_IPS="127.0.0.1",
        API_ORIGIN_SECRET=SecretStr(actual),
        API_ORIGIN_SECRET_PREVIOUS=SecretStr(anterior),
    )


def _peticion(cabeceras: dict[str, str], peer: str = NODO_RENDER) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/auth/me",
        "headers": [(k.lower().encode(), v.encode()) for k, v in cabeceras.items()],
        "client": (peer, 47742),
    }
    return Request(scope)


def _ip(cabeceras: dict[str, str], settings_doble: object) -> str:
    with patch.dict("sys.modules", {"config": MagicMock(settings=settings_doble)}):
        return _trusted_client_ip(_peticion(cabeceras))


class TestSecretoDeOrigen:
    def test_secreto_valido_toma_x_real_ip(self) -> None:
        cabeceras = {
            CABECERA_SECRETO_ORIGEN: SECRETO,
            "X-Real-IP": VISITANTE,
            "X-Forwarded-For": f"{VISITANTE}, 3.120.10.20, 172.71.150.7, {NODO_RENDER}",
        }
        assert _ip(cabeceras, _settings_con_secretos()) == VISITANTE

    def test_dos_visitantes_dan_dos_ips(self) -> None:
        settings_doble = _settings_con_secretos()
        a = _ip({CABECERA_SECRETO_ORIGEN: SECRETO, "X-Real-IP": VISITANTE}, settings_doble)
        b = _ip({CABECERA_SECRETO_ORIGEN: SECRETO, "X-Real-IP": OTRO_VISITANTE}, settings_doble)
        assert (a, b) == (VISITANTE, OTRO_VISITANTE)

    def test_secreto_valido_sin_x_real_ip_usa_el_primer_salto(self) -> None:
        cabeceras = {
            CABECERA_SECRETO_ORIGEN: SECRETO,
            "X-Forwarded-For": f"{VISITANTE}, 172.71.150.7, {NODO_RENDER}",
        }
        assert _ip(cabeceras, _settings_con_secretos()) == VISITANTE

    def test_secreto_valido_sin_ip_utilizable_cae_al_comportamiento_de_siempre(self) -> None:
        cabeceras = {
            CABECERA_SECRETO_ORIGEN: SECRETO,
            "X-Real-IP": "no-es-una-ip",
            "X-Forwarded-For": "tampoco",
        }
        assert _ip(cabeceras, _settings_con_secretos()) == NODO_RENDER

    def test_secreto_invalido_ignora_la_ip_declarada(self) -> None:
        cabeceras = {CABECERA_SECRETO_ORIGEN: "c" * 64, "X-Real-IP": "6.6.6.6"}
        assert _ip(cabeceras, _settings_con_secretos()) == NODO_RENDER

    def test_prefijo_del_secreto_no_basta(self) -> None:
        cabeceras = {CABECERA_SECRETO_ORIGEN: SECRETO[:-1], "X-Real-IP": "6.6.6.6"}
        assert _ip(cabeceras, _settings_con_secretos()) == NODO_RENDER

    def test_secreto_ausente_ignora_la_ip_declarada(self) -> None:
        cabeceras = {"X-Real-IP": "6.6.6.6", "X-Forwarded-For": "6.6.6.6"}
        assert _ip(cabeceras, _settings_con_secretos()) == NODO_RENDER

    def test_sin_secreto_configurado_no_hay_verificacion(self) -> None:
        # Incluido el literal que manda el transform de Vercel cuando la
        # variable no existe en ese entorno, y una cabecera vacía.
        settings_doble = _settings_con_secretos(actual="")
        for valor in ("$API_ORIGIN_SECRET", ""):
            cabeceras = {CABECERA_SECRETO_ORIGEN: valor, "X-Real-IP": "6.6.6.6"}
            assert _ip(cabeceras, settings_doble) == NODO_RENDER

    def test_rotacion_acepta_el_vigente_y_el_anterior(self) -> None:
        settings_doble = _settings_con_secretos(actual=SECRETO, anterior=SECRETO_ANTERIOR)
        for secreto in (SECRETO, SECRETO_ANTERIOR):
            cabeceras = {CABECERA_SECRETO_ORIGEN: secreto, "X-Real-IP": VISITANTE}
            assert _ip(cabeceras, settings_doble) == VISITANTE

    def test_rotacion_terminada_rechaza_el_anterior(self) -> None:
        settings_doble = _settings_con_secretos(actual=SECRETO, anterior="")
        cabeceras = {CABECERA_SECRETO_ORIGEN: SECRETO_ANTERIOR, "X-Real-IP": VISITANTE}
        assert _ip(cabeceras, settings_doble) == NODO_RENDER

    def test_compara_en_tiempo_constante_contra_todos_los_valores(self) -> None:
        settings_doble = _settings_con_secretos(actual=SECRETO, anterior=SECRETO_ANTERIOR)
        cabeceras = {CABECERA_SECRETO_ORIGEN: SECRETO, "X-Real-IP": VISITANTE}
        with patch("api.middleware.hmac.compare_digest", wraps=hmac.compare_digest) as cmp:
            assert _ip(cabeceras, settings_doble) == VISITANTE
        # Sin cortar al primer acierto: cuánto tarda no dice cuál casó.
        assert cmp.call_count == 2

    def test_settings_sin_los_campos_no_rompe(self) -> None:
        """Los dobles de settings de otros tests no declaran los secretos."""
        settings_doble = SimpleNamespace(FORWARDED_ALLOW_IPS="127.0.0.1")
        cabeceras = {CABECERA_SECRETO_ORIGEN: SECRETO, "X-Real-IP": "6.6.6.6"}
        assert _ip(cabeceras, settings_doble) == NODO_RENDER


class TestSecretoNoSeFiltra:
    def test_el_secreto_no_aparece_en_ningun_log(self) -> None:
        """Ni en ``http_request`` ni en el diagnóstico temporal; la IP elegida sí."""

        async def handler(request: Request) -> Response:
            return JSONResponse({"ok": True})

        app = Starlette(routes=[Route("/api/v1/auth/me", handler)])
        app.add_middleware(ObservabilityMiddleware)
        cabeceras = {CABECERA_SECRETO_ORIGEN: SECRETO, "X-Real-IP": VISITANTE}
        settings_doble = _settings_con_secretos()
        with (
            patch.dict("sys.modules", {"config": MagicMock(settings=settings_doble)}),
            patch("api.middleware.log") as log_middleware,
            patch("api.diagnostico_proxy.log") as log_diag,
        ):
            respuesta = TestClient(app).get("/api/v1/auth/me", headers=cabeceras)
        assert respuesta.status_code == 200

        volcado = repr(log_middleware.mock_calls) + repr(log_diag.mock_calls)
        assert SECRETO not in volcado
        (acceso,) = [
            c.kwargs for c in log_middleware.info.call_args_list if c.args == ("http_request",)
        ]
        assert acceso["client_ip"] == VISITANTE
        (diag,) = [
            c.kwargs for c in log_diag.info.call_args_list if c.args == ("proxy_cabeceras_diag",)
        ]
        assert diag["origen_acreditado"] is True

    def test_sentry_no_envia_la_cabecera_del_secreto(self) -> None:
        from observability.sentry import _strip_pii

        evento: Any = {"request": {"headers": {CABECERA_SECRETO_ORIGEN: SECRETO, "Host": "x"}}}
        resultado = _strip_pii(evento, {})
        assert SECRETO not in repr(resultado)

    def test_secreto_corto_no_arranca(self) -> None:
        for campo in ("API_ORIGIN_SECRET", "API_ORIGIN_SECRET_PREVIOUS"):
            with pytest.raises(ValueError, match=campo):
                Settings(ENV="dev", DATABASE_URL="", **{campo: "corto"})

    def test_settings_acepta_vacio_y_largo_y_no_lo_imprime(self) -> None:
        s = Settings(ENV="dev", DATABASE_URL="", API_ORIGIN_SECRET=SECRETO)
        assert s.API_ORIGIN_SECRET.get_secret_value() == SECRETO
        assert s.API_ORIGIN_SECRET_PREVIOUS.get_secret_value() == ""
        assert SECRETO not in repr(s)
        assert SECRETO not in str(s.API_ORIGIN_SECRET)


class TestSesionUsaLaIpVerificada:
    def test_la_sesion_guarda_la_ip_del_visitante(self) -> None:
        """``/me/sesiones`` enseñaba el nodo del proxy: ``request.client.host``."""
        from api.routes import auth as auth_routes

        settings_doble = _settings_con_secretos()
        peticion = _peticion({CABECERA_SECRETO_ORIGEN: SECRETO, "X-Real-IP": VISITANTE})
        with (
            patch.dict("sys.modules", {"config": MagicMock(settings=settings_doble)}),
            patch.object(auth_routes, "create_session", return_value="tok") as crear,
        ):
            auth_routes._set_session_cookie(Response(), 7, peticion)
        assert crear.call_args.kwargs["ip"] == VISITANTE


class TestFrontendMandaLaMismaCabecera:
    """Vercel y el SSR tienen que usar el nombre que verifica la API."""

    _WEB = Path(__file__).resolve().parent.parent / "web"

    def test_vercel_json_pone_el_secreto_en_api(self) -> None:
        config = json.loads((self._WEB / "vercel.json").read_text(encoding="utf-8"))
        rutas = [r for r in config.get("routes", []) if str(r.get("src", "")).startswith("^/api/")]
        assert len(rutas) == 1, "web/vercel.json necesita una ruta de /api/* con el transform"
        (ruta,) = rutas
        # Sin `continue` la ruta se quedaría con /api/* y el rewrite de
        # next.config.ts no llegaría a reenviarlo.
        assert ruta.get("continue") is True
        assert "dest" not in ruta
        transforms = ruta["transforms"]
        objetivo = {"key": CABECERA_SECRETO_ORIGEN}
        # Primero se borra lo que mande el visitante; luego se pone el secreto.
        assert transforms[0] == {"type": "request.headers", "op": "delete", "target": objetivo}
        assert transforms[1] == {
            "type": "request.headers",
            "op": "set",
            "target": objetivo,
            "args": "$API_ORIGIN_SECRET",
            "env": ["API_ORIGIN_SECRET"],
        }

    def test_el_prefetch_ssr_manda_la_misma_cabecera(self) -> None:
        fuente = (self._WEB / "src" / "lib" / "server-prefetch.ts").read_text(encoding="utf-8")
        assert f'"{CABECERA_SECRETO_ORIGEN}"' in fuente
        assert "process.env.API_ORIGIN_SECRET" in fuente
        assert "NEXT_PUBLIC_API_ORIGIN_SECRET" not in fuente
