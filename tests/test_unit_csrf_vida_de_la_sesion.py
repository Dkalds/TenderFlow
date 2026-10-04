"""El token CSRF vive lo que la sesión en las **dos** puertas de las mutaciones.

Regresión de producción (2026-10-04): pasadas 24 h del login, «Generar resumen»,
el guion y la extracción de la ficha respondían 403 con la sesión viva, y la
pantalla decía «No tienes permiso para ver esto».

El token se emite una sola vez, en el login, y lo validan dos dependencias:
``require_csrf`` (las rutas de ``/auth``) y ``require_any_auth`` (el resto de la
API). Cuando la sesión se hizo deslizante (#311), la primera pasó a aceptarlo
durante toda la vida de la sesión; la segunda conservó un literal de 24 h, así
que una sesión renovada seguía leyendo y dejaba de poder escribir.

Los tests no tocan Postgres: sustituyen la lectura de la sesión.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException, Request

import api.routes.auth as auth_routes
from api.routes.dual_auth import require_any_auth
from db.sessions import session_max_age_seconds
from shared.csrf import generate_csrf_token

_SESSION_TOKEN = "tok-de-prueba"  # pragma: allowlist secret
_HORA = 3600


@pytest.fixture(autouse=True)
def _sesion_viva(monkeypatch: pytest.MonkeyPatch) -> None:
    """Una sesión que el servidor sigue dando por buena (la renovó el uso)."""
    monkeypatch.setattr(
        auth_routes,
        "validate_session_principal",
        lambda token: {
            "id": 7,
            "user_id": 7,
            "email": "usuario@example.com",
            "display_name": "Usuario",
            "is_admin": False,
            "authenticated_at": "2026-10-02T14:59:46+00:00",
            "mfa_verified_at": None,
            "mfa_required": False,
        },
    )


def _token_emitido_hace(segundos: int) -> str:
    """El token que el login dejó en la cookie hace ``segundos``."""
    with patch("shared.csrf.time") as reloj:
        reloj.time.return_value = time.time() - segundos
        return generate_csrf_token(_SESSION_TOKEN)


def _mutar_por_require_csrf(token: str | None) -> dict[str, Any]:
    async def _llamar() -> dict[str, Any]:
        user = await auth_routes.get_current_session_user(_SESSION_TOKEN)
        return await auth_routes.require_csrf(user=user, x_csrf_token=token)

    return asyncio.run(_llamar())


def _mutar_por_require_any_auth(token: str | None) -> dict[str, Any]:
    peticion = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/licitaciones/J260025/resumen",
            "query_string": b"",
            "headers": [],
        }
    )
    return asyncio.run(
        require_any_auth(peticion, api_key_raw=None, session=_SESSION_TOKEN, x_csrf_token=token)
    )


_PUERTAS: list[Callable[[str | None], dict[str, Any]]] = [
    _mutar_por_require_csrf,
    _mutar_por_require_any_auth,
]


@pytest.mark.parametrize("mutar", _PUERTAS)
@pytest.mark.parametrize(
    "edad",
    [
        pytest.param(25 * _HORA, id="25h"),
        pytest.param(session_max_age_seconds() - _HORA, id="al_borde_del_techo"),
    ],
)
def test_el_token_del_login_vale_mientras_viva_la_sesion(
    mutar: Callable[[str | None], dict[str, Any]], edad: int
) -> None:
    """Una sesión de más de un día sigue pudiendo mutar, entre por donde entre."""
    principal = mutar(_token_emitido_hace(edad))

    assert principal["user_id"] == 7


@pytest.mark.parametrize("mutar", _PUERTAS)
def test_un_token_mas_viejo_que_el_techo_de_la_sesion_se_rechaza(
    mutar: Callable[[str | None], dict[str, Any]],
) -> None:
    """Alinear la vida del token con la sesión no le quita la caducidad."""
    with pytest.raises(HTTPException) as exc:
        mutar(_token_emitido_hace(session_max_age_seconds() + _HORA))

    assert exc.value.status_code == 403


@pytest.mark.parametrize("mutar", _PUERTAS)
def test_sin_token_la_mutacion_se_rechaza(
    mutar: Callable[[str | None], dict[str, Any]],
) -> None:
    with pytest.raises(HTTPException) as exc:
        mutar(None)

    assert exc.value.status_code == 403
    assert "CSRF" in exc.value.detail
