"""``GET /api/v1/security/csp-violations`` — lo que la CSP bloqueó, agrupado.

Lo que importa fijar aquí es la guarda y la ventana: la lista la mira un
administrador desde la consola, y ``dias`` acota de verdad lo que se lee.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from api.app import app
from api.routes.dual_auth import require_any_auth

RUTA = "/api/v1/security/csp-violations"


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    return TestClient(app)


def _admin():
    return {"user_id": 1, "email": "admin@test.com", "is_admin": True, "auth_method": "session"}


def _no_admin():
    return {"user_id": 2, "email": "user@test.com", "is_admin": False, "auth_method": "session"}


def _fila(**extra):
    base = {
        "directiva": "frame-src",
        "origen": "https://www.youtube.com",
        "documento": "https://app.example/detalle",
        "ocurrencias": 14,
        "primera_vez": "2026-10-02T10:00:00+00:00",
        "ultima_vez": "2026-10-09T10:00:00+00:00",
    }
    base.update(extra)
    return base


def test_sin_sesion_no_se_lee(client):
    with patch("db.repositories.csp_violations.listar_agrupadas") as listar:
        resp = client.get(RUTA)
    assert resp.status_code == 401, resp.text
    listar.assert_not_called()


def test_exige_admin(client):
    app.dependency_overrides[require_any_auth] = _no_admin
    try:
        with patch("db.repositories.csp_violations.listar_agrupadas") as listar:
            resp = client.get(RUTA)
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 403, resp.text
    listar.assert_not_called()


def test_devuelve_los_grupos_y_la_ventana_que_consulto(client):
    app.dependency_overrides[require_any_auth] = _admin
    try:
        with patch(
            "db.repositories.csp_violations.listar_agrupadas", return_value=[_fila()]
        ) as listar:
            resp = client.get(RUTA, params={"dias": 3, "limit": 20})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    cuerpo = resp.json()
    assert cuerpo["dias"] == 3
    assert cuerpo["items"] == [_fila()]
    # `desde` es hace `dias` días, en ISO con zona: la misma forma con la que
    # escribe `created_at` el endpoint de recepción.
    llamada = listar.call_args.kwargs
    assert llamada["limit"] == 20
    desde = datetime.fromisoformat(llamada["desde"])
    assert desde.tzinfo is not None
    assert abs((datetime.now(UTC) - timedelta(days=3)) - desde) < timedelta(minutes=1)


@pytest.mark.parametrize("params", [{"dias": 0}, {"dias": 91}, {"limit": 0}, {"limit": 501}])
def test_rechaza_ventanas_y_topes_fuera_de_rango(client, params):
    app.dependency_overrides[require_any_auth] = _admin
    try:
        with patch("db.repositories.csp_violations.listar_agrupadas") as listar:
            resp = client.get(RUTA, params=params)
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 422, resp.text
    listar.assert_not_called()
