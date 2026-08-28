"""Tests de ``POST /api/v1/security/client-error``.

El endpoint es el canal de reporte de errores de cliente: público, sin
autenticación y sin persistencia (solo log). Lo que se fija aquí es lo que hace
que eso sea aceptable — los topes que impiden usarlo como sumidero de logs y la
lista de campos que **no** puede registrar.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest


@pytest.fixture
def _rate_limit_ok():
    """Deja pasar el rate limit por IP del endpoint (el backend real va a BD)."""
    with patch("api.routes.security.get_rate_limiter") as mock_rl:
        mock_rl.return_value.check.return_value = True
        yield mock_rl


def _kwargs_del_log(mock_log: Any) -> dict[str, Any]:
    mock_log.warning.assert_called_once()
    kwargs: dict[str, Any] = mock_log.warning.call_args.kwargs
    return kwargs


class TestClientErrorPayloadValido:
    def test_acepta_payload_valido_y_lo_loguea(self, client, _rate_limit_ok):
        with patch("api.routes.security.log") as mock_log:
            resp = client.post(
                "/api/v1/security/client-error",
                json={
                    "message": "Cannot read properties of undefined",
                    "source": "onerror",
                    "context": "ConsoleRail.logout",
                    "path": "/mercado",
                    "stack": "at f (/_next/static/chunks/app.js:1:2)",
                    "digest": "1a2b3c4d",
                },
            )
        assert resp.status_code == 204
        kwargs = _kwargs_del_log(mock_log)
        assert mock_log.warning.call_args.args[0] == "client_error"
        assert kwargs["message"] == "Cannot read properties of undefined"
        assert kwargs["source"] == "onerror"
        assert kwargs["context"] == "ConsoleRail.logout"
        assert kwargs["path"] == "/mercado"
        assert kwargs["digest"] == "1a2b3c4d"

    def test_origen_desconocido_no_llega_al_log_como_texto_libre(self, client, _rate_limit_ok):
        # `source` es una dimensión del log: si admitiera texto libre del
        # emisor, cualquiera podría reventar la cardinalidad del agregador.
        with patch("api.routes.security.log") as mock_log:
            resp = client.post(
                "/api/v1/security/client-error",
                json={"message": "boom", "source": "x" * 200},
            )
        assert resp.status_code == 204
        assert _kwargs_del_log(mock_log)["source"] == "desconocido"

    def test_digest_invalido_se_descarta(self, client, _rate_limit_ok):
        with patch("api.routes.security.log") as mock_log:
            resp = client.post(
                "/api/v1/security/client-error",
                json={"message": "boom", "digest": "no es un digest; DROP TABLE"},
            )
        assert resp.status_code == 204
        assert _kwargs_del_log(mock_log)["digest"] == ""

    def test_trunca_mensaje_y_stack(self, client, _rate_limit_ok):
        # El payload tiene que quedar **por debajo** del tope de cuerpo
        # (`_MAX_CLIENT_ERROR_BYTES`, 4096) y por encima de los topes de campo
        # (300 y 2000): con 2000+3000 caracteres el endpoint respondía 413 y
        # este caso no llegaba a comprobar el truncado que venía a comprobar.
        # El rechazo del cuerpo grande tiene su propio test más abajo.
        with patch("api.routes.security.log") as mock_log:
            resp = client.post(
                "/api/v1/security/client-error",
                json={"message": "m" * 500, "stack": "s" * 2500},
            )
        assert resp.status_code == 204
        kwargs = _kwargs_del_log(mock_log)
        assert len(kwargs["message"]) == 300
        assert len(kwargs["stack"]) == 2000


class TestClientErrorSinDatosPersonales:
    def test_ignora_campos_no_declarados(self, client, _rate_limit_ok):
        # `extra="ignore"` en el modelo es la garantía: aunque un call-site del
        # frontend mande contexto extra con datos de formulario, aquí se cae.
        with patch("api.routes.security.log") as mock_log:
            resp = client.post(
                "/api/v1/security/client-error",
                json={
                    "message": "boom",
                    "email": "persona@example.com",
                    "extra": {"nif": "B12345678"},  # pragma: allowlist secret
                    "cookie": "session=abc",
                },
            )
        assert resp.status_code == 204
        kwargs = _kwargs_del_log(mock_log)
        assert "email" not in kwargs
        assert "extra" not in kwargs
        assert "cookie" not in kwargs
        serializado = json.dumps(kwargs, default=str)
        assert "persona@example.com" not in serializado
        assert "B12345678" not in serializado  # pragma: allowlist secret

    def test_recorta_la_query_string_de_la_ruta(self, client, _rate_limit_ok):
        with patch("api.routes.security.log") as mock_log:
            resp = client.post(
                "/api/v1/security/client-error",
                json={
                    "message": "boom",
                    "path": "/mercado?empresa=Acme+SL&email=persona@example.com#seccion",
                },
            )
        assert resp.status_code == 204
        kwargs = _kwargs_del_log(mock_log)
        assert kwargs["path"] == "/mercado"

    def test_no_registra_la_ip_del_cliente(self, client, _rate_limit_ok):
        """La IP es dato personal, y aquí iría junto a `path` y `user_agent`.

        Con las tres en la misma línea, un endpoint sin autenticación acaba
        escribiendo un rastro de navegación por IP. El precedente del propio
        fichero es `csp_violation`, que tampoco la registra. La IP se sigue
        leyendo para la clave del rate limiter (`clierr:{ip}`), que no se
        persiste como texto.
        """
        with patch("api.routes.security.log") as mock_log:
            resp = client.post(
                "/api/v1/security/client-error",
                json={"message": "boom", "path": "/mercado"},
                headers={"X-Forwarded-For": "203.0.113.7"},
            )
        assert resp.status_code == 204
        kwargs = _kwargs_del_log(mock_log)
        assert "client_ip" not in kwargs
        assert "203.0.113.7" not in json.dumps(kwargs, default=str)

    def test_descarta_rutas_absolutas(self, client, _rate_limit_ok):
        # Una URL absoluta puede traer credenciales en el userinfo
        # (`https://user:pass@host/…`), se tira entera.  # pragma: allowlist secret
        with patch("api.routes.security.log") as mock_log:
            resp = client.post(
                "/api/v1/security/client-error",
                # Credenciales inventadas: la prueba comprueba que NO se registran.
                json={
                    "message": "boom",
                    "path": "https://user:secreto@evil.example/x",  # pragma: allowlist secret
                },
            )
        assert resp.status_code == 204
        assert _kwargs_del_log(mock_log)["path"] == ""


class TestClientErrorAbuso:
    def test_rechaza_payload_demasiado_grande(self, client, _rate_limit_ok):
        # 4 KiB es el presupuesto; por encima no hay diagnóstico, hay sumidero.
        with patch("api.routes.security.log") as mock_log:
            resp = client.post(
                "/api/v1/security/client-error",
                content=json.dumps({"message": "x" * 8000}).encode(),
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == 413
        mock_log.warning.assert_not_called()

    def test_rate_limit_descarta_en_silencio(self, client):
        with (
            patch("api.routes.security.get_rate_limiter") as mock_rl,
            patch("api.routes.security.log") as mock_log,
        ):
            mock_rl.return_value.check.return_value = False
            resp = client.post("/api/v1/security/client-error", json={"message": "boom"})
        # 204 y no 429: revelar el descarte solo conseguiría que el navegador
        # reintentara. Lo que importa es que no escribe en el log.
        assert resp.status_code == 204
        mock_log.warning.assert_not_called()

    def test_body_no_json_se_ignora(self, client, _rate_limit_ok):
        with patch("api.routes.security.log") as mock_log:
            resp = client.post(
                "/api/v1/security/client-error",
                content=b"no es json",
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == 204
        mock_log.warning.assert_not_called()

    def test_mensaje_vacio_no_ensucia_el_log(self, client, _rate_limit_ok):
        with patch("api.routes.security.log") as mock_log:
            resp = client.post(
                "/api/v1/security/client-error",
                json={"message": "   ", "source": "onerror"},
            )
        assert resp.status_code == 204
        mock_log.warning.assert_not_called()

    def test_tipos_incorrectos_se_ignoran(self, client, _rate_limit_ok):
        with patch("api.routes.security.log") as mock_log:
            resp = client.post(
                "/api/v1/security/client-error",
                json={"message": {"anidado": True}},
            )
        assert resp.status_code == 204
        mock_log.warning.assert_not_called()

    def test_no_requiere_autenticacion(self, client, _rate_limit_ok):
        # Sin cabecera de auth: un fallo del layout raíz ocurre por encima de la
        # sesión, así que exigir credenciales dejaría fuera lo más grave.
        with patch("api.routes.security.log"):
            resp = client.post("/api/v1/security/client-error", json={"message": "boom"})
        assert resp.status_code == 204
