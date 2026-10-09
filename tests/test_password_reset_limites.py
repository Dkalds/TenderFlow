"""Cuotas de la recuperación de contraseña (``_password_reset_rate_allowed``).

El limitador iba siempre simulado en ``tests/test_password_reset.py``: ningún
test miraba qué claves consulta, con qué tope ni qué pasa cuando el almacén
falla. Aquí se fija todo eso, y que pedir el enlace y confirmarlo no comparten
cubo: antes cada solicitud gastaba uno de los cinco intentos de confirmar.
"""

from __future__ import annotations

import asyncio
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.routes import auth as auth_mod

_REQUEST = "/api/v1/auth/password-reset/request"
_CONFIRM = "/api/v1/auth/password-reset/confirm"
_NEW_PASSWORD = "NuevaClave-2026-Segura"  # pragma: allowlist secret # gitleaks:allow
_IP = "203.0.113.7"
_EMAIL = "persona@example.com"
_CUBO_IP_REQUEST = f"password-reset:ip:{_IP}"
_CUBO_IP_CONFIRM = f"password-reset:confirm:ip:{_IP}"
_CUBO_SUJETO = "password-reset:subject:" + hashlib.sha256(_EMAIL.encode()).hexdigest()[:16]


class _LimitadorEspia:
    """Limitador de pega: apunta cada consulta y deniega las claves agotadas."""

    def __init__(self, *agotadas: str) -> None:
        self.consultas: list[tuple[str, int, float]] = []
        self._agotadas = frozenset(agotadas)

    def check(self, key: str, *, max_calls: int = 120, window_seconds: float = 60.0) -> bool:
        self.consultas.append((key, max_calls, window_seconds))
        return key not in self._agotadas

    @property
    def claves(self) -> list[str]:
        return [clave for clave, _tope, _ventana in self.consultas]


def _permitido(limitador: object, email: str | None = None, **kwargs: object) -> bool:
    """Llama al limitador de la ruta con una IP de cliente fija."""
    with (
        patch("api.middleware._trusted_client_ip", return_value=_IP),
        patch("services.rate_limiting.get_rate_limiter", return_value=limitador),
    ):
        return asyncio.run(auth_mod._password_reset_rate_allowed(MagicMock(), email, **kwargs))


def _confirm_kwargs() -> dict[str, object]:
    return {"bucket": auth_mod._RESET_CONFIRM_BUCKET}


def test_pedir_el_enlace_consulta_el_cubo_de_ip_y_el_del_destinatario():
    espia = _LimitadorEspia()

    assert _permitido(espia, _EMAIL) is True

    assert espia.consultas == [
        (_CUBO_IP_REQUEST, 5, 900),
        (_CUBO_SUJETO, 3, 3600),
    ]


def test_el_cubo_del_destinatario_es_el_hash_del_correo_no_el_correo():
    espia = _LimitadorEspia()

    _permitido(espia, "  Persona@Example.COM ")

    # Las claves acaban en `rate_limits` o en Redis: ahí no se guarda la
    # dirección, y la misma cuenta escrita de dos formas cae en el mismo cubo.
    assert espia.claves[1] == _CUBO_SUJETO
    assert not any("@" in clave or "persona" in clave.lower() for clave in espia.claves)


def test_confirmar_tiene_su_propio_cubo_con_el_mismo_tope_y_ventana():
    espia = _LimitadorEspia()

    assert _permitido(espia, **_confirm_kwargs()) is True

    assert espia.consultas == [(_CUBO_IP_CONFIRM, 5, 900)]
    assert _CUBO_IP_CONFIRM != _CUBO_IP_REQUEST


def test_agotar_las_solicitudes_no_bloquea_la_confirmacion_ni_al_reves():
    assert _permitido(_LimitadorEspia(_CUBO_IP_REQUEST), _EMAIL) is False
    assert _permitido(_LimitadorEspia(_CUBO_IP_REQUEST), **_confirm_kwargs()) is True
    assert _permitido(_LimitadorEspia(_CUBO_IP_CONFIRM), **_confirm_kwargs()) is False
    assert _permitido(_LimitadorEspia(_CUBO_IP_CONFIRM), _EMAIL) is True


def test_con_la_ip_agotada_no_se_gasta_la_cuota_del_destinatario():
    espia = _LimitadorEspia(_CUBO_IP_REQUEST)

    assert _permitido(espia, _EMAIL) is False

    assert espia.claves == [_CUBO_IP_REQUEST]


def test_el_destinatario_agotado_deniega_aunque_la_ip_tenga_cuota():
    assert _permitido(_LimitadorEspia(_CUBO_SUJETO), _EMAIL) is False


@pytest.mark.parametrize("confirmar", [False, True])
def test_un_limitador_que_falla_deniega(confirmar: bool):
    roto = MagicMock()
    roto.check.side_effect = RuntimeError("redis y postgres caídos")

    if confirmar:
        assert _permitido(roto, **_confirm_kwargs()) is False
    else:
        assert _permitido(roto, _EMAIL) is False


def test_si_el_almacen_de_cuotas_falla_el_limitador_real_deniega():
    """Sin simular el limitador: la tabla ``rate_limits`` no responde y se deniega."""
    from services.rate_limiting import DbRateLimiter

    with patch("db.rate_limits._connect", side_effect=RuntimeError("sin base de datos")):
        assert _permitido(DbRateLimiter(), _EMAIL) is False
        assert _permitido(DbRateLimiter(), **_confirm_kwargs()) is False


def test_por_http_cada_paso_consulta_su_cubo():
    espia = _LimitadorEspia()
    client = TestClient(app)
    with (
        patch("api.middleware._trusted_client_ip", return_value=_IP),
        patch("services.rate_limiting.get_rate_limiter", return_value=espia),
        patch("services.password_reset.process_password_reset_request"),
        patch("db.password_reset.consume_reset_token", return_value=None),
    ):
        pedido = client.post(_REQUEST, json={"email": _EMAIL})
        tras_pedir = list(espia.claves)
        confirmacion = client.post(_CONFIRM, json={"token": "x" * 43, "password": _NEW_PASSWORD})

    assert pedido.status_code == 202, pedido.text
    assert confirmacion.status_code == 400, confirmacion.text
    assert tras_pedir == [_CUBO_IP_REQUEST, _CUBO_SUJETO]
    assert espia.claves[len(tras_pedir) :] == [_CUBO_IP_CONFIRM]


def test_por_http_un_cubo_de_solicitudes_agotado_no_da_429_al_confirmar():
    client = TestClient(app)
    with (
        patch("api.middleware._trusted_client_ip", return_value=_IP),
        patch(
            "services.rate_limiting.get_rate_limiter",
            return_value=_LimitadorEspia(_CUBO_IP_REQUEST),
        ),
        patch("services.password_reset.process_password_reset_request") as aplazado,
        patch("db.password_reset.consume_reset_token", return_value=7),
        patch("api.routes.auth.log_event"),
    ):
        pedido = client.post(_REQUEST, json={"email": _EMAIL})
        confirmacion = client.post(_CONFIRM, json={"token": "x" * 43, "password": _NEW_PASSWORD})

    # Limitada, la solicitud responde lo de siempre y no llega a emitir nada…
    assert pedido.status_code == 202, pedido.text
    aplazado.assert_not_called()
    # …y la confirmación, que va por otro cubo, sigue su curso.
    assert confirmacion.status_code == 200, confirmacion.text


def test_el_429_de_confirm_anuncia_la_ventana_del_cubo():
    client = TestClient(app)
    with patch("api.routes.auth._password_reset_rate_allowed", new=AsyncMock(return_value=False)):
        response = client.post(_CONFIRM, json={"token": "x" * 43, "password": _NEW_PASSWORD})

    assert response.status_code == 429
    assert response.headers["Retry-After"] == str(auth_mod._RESET_IP_WINDOW_SECONDS) == "900"


# ---------------------------------------------------------------------------
# Con el limitador real y su tabla
# ---------------------------------------------------------------------------


@pytest.fixture()
def limitador_en_bd(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fija el backend de BD: el singleton podría haber quedado en Redis en otro test."""
    from services.rate_limiting import DbRateLimiter

    monkeypatch.setattr("services.rate_limiting.get_rate_limiter", lambda: DbRateLimiter())


def test_el_sexto_intento_de_confirmar_en_la_ventana_responde_429(client, limitador_en_bd):
    cuerpo = {"token": "x" * 43, "password": _NEW_PASSWORD}

    for _ in range(5):
        # El token no existe, pero el intento cuenta: es lo que se limita.
        assert client.post(_CONFIRM, json=cuerpo).status_code == 400

    limitado = client.post(_CONFIRM, json=cuerpo)
    assert limitado.status_code == 429, limitado.text
    assert limitado.headers["Retry-After"] == "900"


def test_pedir_el_enlace_no_gasta_los_intentos_de_confirmarlo(client, limitador_en_bd):
    from db.database import connect

    with patch("services.password_reset.process_password_reset_request") as aplazado:
        for i in range(6):
            pedido = client.post(_REQUEST, json={"email": f"persona{i}@example.com"})
            assert pedido.status_code == 202, pedido.text

    # Cinco por IP cada quince minutos, exista o no la cuenta: la sexta
    # responde igual y ya no emite nada.
    assert aplazado.call_count == 5
    # Confirmar va por su cubo: responde por el token (400), no por la cuota.
    confirmacion = client.post(_CONFIRM, json={"token": "x" * 43, "password": _NEW_PASSWORD})
    assert confirmacion.status_code == 400, confirmacion.text

    with connect() as connection:
        claves = [fila[0] for fila in connection.execute("SELECT key FROM rate_limits").fetchall()]
    assert any(clave.startswith("password-reset:subject:") for clave in claves)
    assert not any("@" in clave for clave in claves)
