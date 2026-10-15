"""El 403 de «vuelve a entrar» se distingue de un 403 de permiso.

``require_recent_session`` corta las acciones sensibles —activar o quitar el
segundo factor, acuñar o revocar claves, borrar la cuenta o una organización—
cuando la sesión ya no es reciente. Ese 403 tiene arreglo (cerrar sesión y
volver a entrar); el de un rol que no llega, no. Con el mismo ``type`` en los
dos, la consola sólo podía distinguirlos comparando el texto en inglés del
``detail``, que no es contrato de nada.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api.errors import TIPO_REAUTENTICACION, ReautenticacionRequerida, register_exception_handlers
from api.routes.dual_auth import require_recent_session
from config import settings


def _hace(segundos: int) -> str:
    return (datetime.now(UTC) - timedelta(seconds=segundos)).isoformat()


def _comprobar(ctx: dict[str, Any]) -> dict[str, Any]:
    """Ejecuta la comprobación de ``require_recent_session`` sobre un principal."""
    dependencia = require_recent_session()
    return asyncio.run(dependencia(ctx))


def test_el_403_de_reautenticacion_lleva_su_propio_tipo() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/sensible")
    def sensible() -> None:
        raise ReautenticacionRequerida("Reauthenticate before performing this sensitive operation.")

    resp = TestClient(app).get("/sensible")

    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["type"] == TIPO_REAUTENTICACION
    assert resp.json()["detail"] == "Reauthenticate before performing this sensitive operation."


def test_un_403_de_permiso_sigue_siendo_forbidden() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/ajeno")
    def ajeno() -> None:
        raise HTTPException(status_code=403, detail="Admin required.")

    assert TestClient(app).get("/ajeno").json()["type"].endswith("/forbidden")


def test_sesion_antigua_pide_reautenticarse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SENSITIVE_ACTION_MAX_AGE_SECONDS", 900)
    ctx = {"auth_method": "session", "authenticated_at": _hace(901)}

    with pytest.raises(ReautenticacionRequerida) as exc:
        _comprobar(ctx)

    assert exc.value.status_code == 403


def test_segundo_factor_antiguo_pide_reautenticarse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Volver a entrar vuelve a pedir el código: el arreglo es el mismo."""
    monkeypatch.setattr(settings, "SENSITIVE_ACTION_MAX_AGE_SECONDS", 900)
    monkeypatch.setattr(settings, "MFA_STEP_UP_MAX_AGE_SECONDS", 900)
    ctx = {
        "auth_method": "session",
        "authenticated_at": _hace(10),
        "mfa_required": True,
        "mfa_verified_at": _hace(901),
    }

    with pytest.raises(ReautenticacionRequerida):
        _comprobar(ctx)


def test_una_clave_de_api_no_se_arregla_reautenticando() -> None:
    """Con clave de API no hay sesión que renovar: es un 403 de permiso."""
    with pytest.raises(HTTPException) as exc:
        _comprobar({"auth_method": "api_key"})

    assert exc.value.status_code == 403
    assert not isinstance(exc.value, ReautenticacionRequerida)


def test_sesion_reciente_pasa() -> None:
    ctx = {"auth_method": "session", "authenticated_at": _hace(5)}

    assert _comprobar(ctx) is ctx
