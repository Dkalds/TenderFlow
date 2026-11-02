"""Tests para observability/sentry.py — configuración y recorte del evento."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import sentry_sdk

REPO = Path(__file__).resolve().parents[1]
DSN_FALSO = "https://x@sentry.io/1"


class TestSentry:
    def setup_method(self):
        import observability.sentry as mod

        mod._configured = False
        self._mod = mod

    def teardown_method(self):
        self._mod._configured = False

    def test_configure_no_dsn(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SENTRY_DSN", None)
            result = self._mod.configure_sentry()
        assert result is False
        assert self._mod._configured is True

    def test_configure_already_configured(self):
        self._mod._configured = True
        assert self._mod.configure_sentry() is True

    def test_configure_import_error(self):
        with patch.dict(os.environ, {"SENTRY_DSN": DSN_FALSO}):
            import builtins

            real_import = builtins.__import__

            def fake_import(name, *args, **kwargs):
                if "sentry_sdk" in name:
                    raise ImportError("no sentry")
                return real_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=fake_import):
                result = self._mod.configure_sentry()
        assert result is False

    def test_configure_pasa_las_opciones_de_privacidad(self):
        entorno = {
            "SENTRY_DSN": DSN_FALSO,
            "ENV": "prod",
            "APP_PROFILE": "worker",
            "RENDER_GIT_COMMIT": "abc123",
        }
        with (
            patch.dict(os.environ, entorno),
            patch.object(sentry_sdk, "init") as init,
            patch.object(sentry_sdk, "set_tag") as set_tag,
        ):
            for nombre in ("ENVIRONMENT", "APP_VERSION", "GIT_SHA"):
                os.environ.pop(nombre, None)
            assert self._mod.configure_sentry(service="test-svc") is True

        opciones = init.call_args.kwargs
        assert opciones["dsn"] == DSN_FALSO
        # `ENV` es la variable que declara render.yaml; con `ENVIRONMENT` a secas
        # producción se etiquetaba como «dev».
        assert opciones["environment"] == "prod"
        assert opciones["release"] == "abc123"
        assert opciones["send_default_pii"] is False
        assert opciones["include_local_variables"] is False
        assert opciones["max_request_body_size"] == "never"
        assert opciones["traces_sample_rate"] == 0.0
        assert opciones["before_send"] is self._mod._strip_pii
        assert opciones["before_send_transaction"] is self._mod._strip_pii
        assert opciones["before_breadcrumb"] is self._mod._limpiar_miga
        set_tag.assert_any_call("service", "test-svc")
        set_tag.assert_any_call("app_profile", "worker")

    def test_version_prefiere_la_declarada_a_mano(self):
        with patch.dict(os.environ, {"APP_VERSION": "1.0", "RENDER_GIT_COMMIT": "abc123"}):
            assert self._mod._version() == "1.0"

    def test_strip_pii(self):
        event = {
            "request": {
                "url": "https://api.test/api/v1/licitaciones?organo=ACME#x",
                "query_string": "organo=ACME",
                "cookies": {"session": "s3cr3t"},
                "data": {"comentario": "texto del formulario"},
                "env": {"REMOTE_ADDR": "1.2.3.4"},
                "headers": {
                    "Authorization": "Bearer xxx",
                    "X-API-Key": "tf_live_abc",
                    "X-Forwarded-For": "1.2.3.4",
                    "Content-Type": "text/html",
                    "User-Agent": "pytest",
                    "Referer": "https://app.test/radar?q=ACME",
                    "Host": "api.test",
                },
            },
            "user": {"id": "abc", "email": "test@test.com", "ip_address": "1.2.3.4"},
        }
        result = self._mod._strip_pii(event, {})
        assert result["request"] == {
            "url": "https://api.test/api/v1/licitaciones",
            "headers": {
                "User-Agent": "pytest",
                "Referer": "https://app.test/radar",
                "Host": "api.test",
            },
        }
        assert result["user"] == {"id": "abc"}

    def test_strip_pii_redacta_los_textos_libres(self):
        """Mensajes de excepción, de log y `extra` pasan por el redactor del log."""
        event = {
            "exception": {
                "values": [
                    {
                        "type": "UniqueViolation",
                        "value": "duplicate key (email)=(ana@example.test) con ?token=abc123secreto",
                    },
                    {"type": "Sin valor"},
                ]
            },
            "message": "fallo para ana@example.test",
            "logentry": {
                "message": "usuario %s",
                "formatted": "usuario ana@example.test",
                "params": ["ana@example.test"],
            },
            "extra": {"contacto": "ana@example.test", "intentos": 3},
        }
        result = self._mod._strip_pii(event, {})

        volcado = json.dumps(result)
        assert "ana@example.test" not in volcado
        assert "abc123secreto" not in volcado
        assert result["exception"]["values"][1] == {"type": "Sin valor"}
        assert "params" not in result["logentry"]
        assert result["extra"]["intentos"] == 3

    def test_strip_pii_no_user(self):
        event = {"request": {"headers": {}}}
        result = self._mod._strip_pii(event, {})
        assert "user" not in result

    def test_strip_pii_usuario_sin_id_queda_vacio(self):
        event = {"user": {"email": "a@b.com", "ip_address": "1.1.1.1"}}
        result = self._mod._strip_pii(event, {})
        assert result["user"] == {}

    def test_limpiar_miga_solo_deja_salida_http_sin_query(self):
        miga_http = {
            "type": "http",
            "category": "httplib",
            "data": {"url": "https://x.test/a?token=1", "http.query": "token=1", "method": "GET"},
        }
        assert self._mod._limpiar_miga(miga_http, {}) == {
            "type": "http",
            "category": "httplib",
            "data": {"url": "https://x.test/a", "method": "GET"},
        }
        # La clave de Redis del rate limiting es la IP del cliente.
        miga_redis = {"type": "redis", "category": "redis", "data": {"redis.key": "rl:1.2.3.4"}}
        assert self._mod._limpiar_miga(miga_redis, {}) is None
        assert self._mod._limpiar_miga({"category": "query", "message": "SELECT 1"}, {}) is None

    def test_set_user_context_no_sdk(self):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if "sentry_sdk" in name:
                raise ImportError
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            self._mod.set_user_context("hash123")  # should not raise

    def test_set_user_context_with_sdk(self):
        mock_sdk = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": mock_sdk}):
            self._mod.set_user_context("hash123", locale="en")
        mock_sdk.set_user.assert_called_once_with({"id": "hash123", "locale": "en"})

    def test_set_user_context_no_locale(self):
        mock_sdk = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": mock_sdk}):
            self._mod.set_user_context("hash456")
        mock_sdk.set_user.assert_called_once_with({"id": "hash456"})


# Una app mínima con los manejadores de error de producción, el SDK real y un
# transporte que guarda los eventos en vez de enviarlos. Corre en un proceso
# aparte porque las integraciones de Starlette y FastAPI parchean esas clases
# para lo que quede de proceso: dentro de la suite cambiarían la pila de
# middlewares de los tests que vinieran detrás en el mismo worker.
_ESCENARIO = """
import json
import sentry_sdk
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sentry_sdk.transport import Transport

from api.errors import register_exception_handlers
from observability.sentry import configure_sentry

eventos = []

class Captura(Transport):
    def capture_envelope(self, envelope):
        evento = envelope.get_event()
        if evento is not None:
            eventos.append(evento)

_init = sentry_sdk.init
sentry_sdk.init = lambda **opciones: _init(**opciones, transport=Captura())
assert configure_sentry(service="escenario") is True

app = FastAPI()
register_exception_handlers(app)

@app.post("/revienta")
async def revienta(cuerpo: dict):
    variable_local = "LOCAL-SECRETA"
    raise RuntimeError("fallo inesperado")

@app.get("/degradado")
async def degradado():
    raise HTTPException(status_code=503, detail="sin modelo")

@app.get("/roto")
async def roto():
    raise HTTPException(status_code=500, detail="roto")

cliente = TestClient(app, raise_server_exceptions=False)
cliente.cookies.set("session", "COOKIE-SECRETA")
estados = [
    cliente.post(
        "/revienta?organo=QUERY-SECRETA",
        json={"comentario": "CUERPO-SECRETO"},
        headers={"X-API-Key": "CLAVE-SECRETA", "X-Forwarded-For": "203.0.113.7"},
    ).status_code,
    cliente.get("/degradado").status_code,
    cliente.get("/roto").status_code,
]
sentry_sdk.flush()
print(json.dumps({"estados": estados, "eventos": eventos}, default=str))
"""


def test_el_sdk_real_captura_los_500_y_no_envia_dato_del_visitante():
    entorno = {
        **os.environ,
        "SENTRY_DSN": DSN_FALSO,
        "ENV": "dev",
        "PYTHONPATH": str(REPO),
        "PYTHONUTF8": "1",
    }
    proceso = subprocess.run(
        [sys.executable, "-c", _ESCENARIO],
        cwd=REPO,
        env=entorno,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert proceso.returncode == 0, proceso.stderr[-2000:]
    salida = json.loads(proceso.stdout.strip().splitlines()[-1])

    assert salida["estados"] == [500, 503, 500]
    eventos = salida["eventos"]
    # El manejador genérico de `api/errors.py` responde 500 sin tragarse la
    # excepción para Sentry; el 503 es una degradación declarada y no cuenta.
    tipos = [evento["exception"]["values"][-1]["type"] for evento in eventos]
    assert tipos == ["RuntimeError", "HTTPException"]

    volcado = json.dumps(eventos)
    for secreto in (
        "LOCAL-SECRETA",
        "COOKIE-SECRETA",
        "QUERY-SECRETA",
        "CUERPO-SECRETO",
        "CLAVE-SECRETA",
        "203.0.113.7",
    ):
        assert secreto not in volcado, secreto

    peticion = eventos[0]["request"]
    assert peticion["url"].endswith("/revienta")
    assert {nombre.lower() for nombre in peticion["headers"]} <= {"host", "user-agent", "referer"}
    assert eventos[0]["tags"]["service"] == "escenario"
