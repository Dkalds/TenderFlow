"""Allowlist OAuth dinámica: composición y fail-closed."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.routes.auth import _oauth_access_allowed


def test_static_grant_skips_database():
    with (
        patch("api.routes.auth.oauth_email_allowed", return_value=True),
        patch("db.access_grants.is_access_granted") as dynamic,
    ):
        assert asyncio.run(_oauth_access_allowed("allowed@example.test")) is True
    dynamic.assert_not_called()


def test_dynamic_grant_allows_email():
    with (
        patch("api.routes.auth.oauth_email_allowed", return_value=False),
        patch("db.access_grants.is_access_granted", return_value=True),
    ):
        assert asyncio.run(_oauth_access_allowed("allowed@example.test")) is True


def test_dynamic_allowlist_failure_is_closed():
    with (
        patch("api.routes.auth.oauth_email_allowed", return_value=False),
        patch(
            "db.access_grants.is_access_granted",
            side_effect=RuntimeError("database unavailable"),
        ),
    ):
        assert asyncio.run(_oauth_access_allowed("unknown@example.test")) is False


def test_dynamic_grant_is_normalized_idempotent_and_revocable(tmp_db):
    from db.access_grants import grant_access, is_access_granted, revoke_access

    first = grant_access("email", " Allowed@Example.Test ", granted_by=None)
    second = grant_access("email", "allowed@example.test", granted_by=None)

    assert second["id"] == first["id"]
    assert is_access_granted("ALLOWED@example.test") is True

    revoked = revoke_access(first["id"])
    assert revoked is not None
    assert revoked["active"] is False
    assert is_access_granted("allowed@example.test") is False


# ── Sin BD: lo que se decide antes de tocar la tabla ────────────────────────
#
# Los tests con Postgres de estas mismas funciones (concesión de dominio,
# reactivación tras revocar, transacción de `grant_access_request`) viven en
# `tests/test_access_grants_integration.py`.


class _ConexionFalsa:
    """Conexión de pega: devuelve una fila y apunta lo que se le pide ejecutar."""

    def __init__(self, fila: tuple[object, ...] | None) -> None:
        self._fila = fila
        self.sentencias: list[str] = []

    def execute(self, sql: str, _params: object = ()) -> SimpleNamespace:
        self.sentencias.append(sql)
        return SimpleNamespace(fetchone=lambda: self._fila)


def _connect_falso(conexion: _ConexionFalsa):
    @contextmanager
    def _connect():
        yield conexion

    return _connect


def _no_debe_abrir_conexion():
    raise AssertionError("no debía llegar a la base de datos")


@pytest.mark.parametrize(
    "email",
    [
        # Tras el último `@` hay un dominio que sí podría estar concedido.
        "x@evil.com@example.com",
        "@example.com",
        # Sin `@`: es un dominio, no la dirección de nadie.
        "example.com",
        "persona@",
        "@",
        "",
    ],
)
def test_is_access_granted_deniega_sin_consultar_lo_que_no_es_una_direccion(email):
    from db.access_grants import is_access_granted

    with patch("db.access_grants.connect_read", side_effect=_no_debe_abrir_conexion):
        assert is_access_granted(email) is False


def test_normalize_grant_deja_el_valor_como_se_compara():
    from db.access_grants import normalize_grant

    assert normalize_grant("email", " Ana@Example.COM ") == "ana@example.com"
    assert normalize_grant("domain", " @Example.COM ") == "example.com"


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("email", "x@evil.com@example.com"),
        ("email", "example.com"),
        ("email", "@example.com"),
        ("email", "persona@"),
        ("email", ""),
        ("domain", "persona@example.com"),
        ("domain", "localhost"),
        ("domain", ""),
    ],
)
def test_normalize_grant_rechaza_lo_que_no_podria_casar_con_nadie(kind, value):
    from db.access_grants import ConcesionInvalida, normalize_grant

    with pytest.raises(ConcesionInvalida):
        normalize_grant(kind, value)


def test_la_concesion_invalida_sigue_siendo_un_value_error():
    """Quien ya capturase ``ValueError`` de ``normalize_grant`` no se queda sin red."""
    from db.access_grants import ConcesionInvalida

    assert issubclass(ConcesionInvalida, ValueError)


def test_grant_access_rechaza_un_dominio_publico_antes_de_escribir():
    """La normalización no sirve para esquivar la regla: ``@Gmail.com`` es ``gmail.com``."""
    from db.access_grants import ConcesionInvalida, grant_access

    with (
        patch("db.access_grants.connect", side_effect=_no_debe_abrir_conexion),
        pytest.raises(ConcesionInvalida, match=r"gmail\.com"),
    ):
        grant_access("domain", " @Gmail.com ", granted_by=None)


@pytest.mark.parametrize(
    "email_de_la_solicitud",
    [
        # Un clic en «Conceder dominio» sobre esta solicitud abría la puerta a
        # cualquier cuenta de Gmail.
        "Quien-Sea@Gmail.com",
        # El dominio se deriva de la dirección: si la dirección no tiene forma
        # de tal, no hay dominio que conceder.
        "x@evil.com@example.com",
    ],
)
def test_grant_access_request_no_escribe_una_concesion_de_dominio_rechazada(
    email_de_la_solicitud,
):
    from db.access_grants import ConcesionInvalida, grant_access_request

    conexion = _ConexionFalsa((email_de_la_solicitud, None, "pendiente"))

    with (
        patch("db.access_grants.connect", _connect_falso(conexion)),
        pytest.raises(ConcesionInvalida),
    ):
        grant_access_request(7, "domain", granted_by=1)

    # Solo la lectura de la solicitud: ni la concesión ni el cambio de estado.
    assert len(conexion.sentencias) == 1
    assert conexion.sentencias[0].startswith("SELECT")
