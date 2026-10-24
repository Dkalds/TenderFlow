"""El login gasta el mismo KDF exista o no la cuenta (punto 7 del ítem del #243).

Si el correo no tenía cuenta, o la cuenta era solo-OAuth, ``POST /auth/login``
respondía 401 sin pasar por argon2; con contraseña, tardaba lo que tarda
``verify_password``. La diferencia de tiempo decía qué correos tienen una
cuenta con contraseña. Ahora esas dos ramas verifican contra un hash ficticio
del mismo KDF y coste que :func:`shared.auth_core.hash_password`.

No se mide el tiempo (sería frágil en CI): se cuenta que cada rama llama una
vez a ``PasswordHasher.verify`` y con un hash de los mismos parámetros que el
de una cuenta recién creada.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from argon2 import PasswordHasher
from fastapi import HTTPException, Response
from starlette.requests import Request

from api.routes import auth
from shared.auth_core import hash_password, verify_password_against_dummy

_CORREO = "ana@example.com"
_CONTRASENA = "no-es-la-buena-1234"  # pragma: allowlist secret


def _parametros(pw_hash: str) -> tuple[str, str]:
    """Variante y coste de un hash argon2 (``$argon2id$v=19$m=…,t=…,p=…$sal$hash``)."""
    partes = pw_hash.split("$")
    return partes[1], partes[3]


def _peticion() -> Request:
    return Request({"type": "http", "headers": [], "client": ("203.0.113.7", 4321)})


@pytest.fixture
def hashes_verificados() -> Iterator[list[str]]:
    """Cada hash que pasa por ``PasswordHasher.verify``, en orden."""
    original = PasswordHasher.verify
    vistos: list[str] = []

    def _espia(self: PasswordHasher, pw_hash: str | bytes, password: str | bytes) -> Any:
        vistos.append(pw_hash if isinstance(pw_hash, str) else pw_hash.decode())
        return original(self, pw_hash, password)

    with patch.object(PasswordHasher, "verify", autospec=True, side_effect=_espia):
        yield vistos


def _login_con(usuario: dict[str, Any] | None) -> HTTPException:
    """Ejecuta el handler de login con la BD sustituida y devuelve el rechazo."""
    with (
        patch.object(auth, "get_user_by_email", return_value=usuario),
        patch.object(auth, "log_event"),
        patch("db.rate_limits.is_login_locked_out", return_value=(False, 0)),
        patch("db.rate_limits.record_failed_login"),
        pytest.raises(HTTPException) as rechazo,
    ):
        asyncio.run(
            auth.login(
                auth.LoginRequest(email=_CORREO, password=_CONTRASENA),
                Response(),
                _peticion(),
            )
        )
    return rechazo.value


def test_el_hash_ficticio_tiene_el_kdf_y_el_coste_de_una_cuenta_nueva(hashes_verificados):
    assert verify_password_against_dummy("cualquiera") is False
    assert len(hashes_verificados) == 1
    assert _parametros(hashes_verificados[0]) == _parametros(hash_password("otra"))


@pytest.mark.parametrize(
    "usuario",
    [
        pytest.param(None, id="sin-cuenta"),
        pytest.param({"id": 7, "email": _CORREO, "password_hash": None}, id="solo-oauth"),
        pytest.param({"id": 7, "email": _CORREO, "password_hash": ""}, id="hash-vacio"),
    ],
)
def test_sin_hash_el_login_pasa_igual_por_el_kdf(usuario, hashes_verificados):
    rechazo = _login_con(usuario)

    assert rechazo.status_code == 401
    assert rechazo.detail == "Invalid credentials"
    assert len(hashes_verificados) == 1
    assert _parametros(hashes_verificados[0]) == _parametros(hash_password("otra"))


def test_con_cuenta_y_contrasena_mala_se_verifica_una_sola_vez(hashes_verificados):
    """La rama de control: con hash real, una verificación (la suya), no dos."""
    real = hash_password("la-buena-de-verdad-1234")
    rechazo = _login_con({"id": 7, "email": _CORREO, "password_hash": real})

    assert rechazo.status_code == 401
    assert hashes_verificados == [real]
