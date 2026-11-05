"""``POST /auth/dev-login`` solo existe con ``ENV=dev``.

Abre sesión como el usuario 1 sin credenciales: en cualquier otro entorno sería
una puerta trasera. La ruta se registra al importar
``api/routes/auth/dev_login.py`` según ``settings.ENV``, así que el test ejecuta
ese módulo de nuevo con cada ``ENV`` —en un módulo aparte, sin tocar
``sys.modules`` ni el ``app`` que comparte la suite— y monta su router en una
app mínima con el mismo prefijo que la real.
"""

from __future__ import annotations

import importlib.util
from types import ModuleType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import settings

_RUTA = "/api/v1/auth/dev-login"


def _dev_login_con_env(monkeypatch: pytest.MonkeyPatch, env: str) -> ModuleType:
    """El módulo ``dev_login`` tal como quedaría al importarlo con ``ENV=env``."""
    import api.routes.auth.dev_login as original

    monkeypatch.setattr(settings, "ENV", env)
    spec = importlib.util.spec_from_file_location(f"_dev_login_{env}", original.__file__)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _cliente(modulo: ModuleType) -> TestClient:
    app = FastAPI()
    app.include_router(modulo.router, prefix="/api/v1/auth")
    return TestClient(app)


@pytest.mark.parametrize("env", ["prod", "staging"])
def test_fuera_de_dev_la_ruta_no_existe(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    modulo = _dev_login_con_env(monkeypatch, env)

    respuesta = _cliente(modulo).post(_RUTA)

    assert respuesta.status_code in (404, 405), respuesta.text
    assert modulo.router.routes == []


def test_en_dev_la_ruta_si_existe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Control: sin él, el test de arriba pasaría también si la ruta cambiara de sitio."""
    modulo = _dev_login_con_env(monkeypatch, "dev")

    assert [(r.path, r.methods) for r in modulo.router.routes] == [("/dev-login", {"POST"})]
