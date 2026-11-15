"""``GET /api/v1/security/csp-violations``: la vista agrupada, sin base de datos.

El repositorio se sustituye; lo que se fija es el contrato (solo
administradores, forma del DTO) y que ``dias`` se traduce en el ``desde`` que
recibe el SQL. El SQL contra Postgres está en
``tests/test_csp_violations_agrupadas.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.routes.dual_auth import require_any_auth

_URL = "/api/v1/security/csp-violations"

_FILA = {
    "directiva": "frame-src",
    "origen": "https://www.youtube.com",
    "veces": 14,
    "primera_vez": "2026-11-01T10:00:00+00:00",
    "ultima_vez": "2026-11-08T09:30:00+00:00",
    "documento_ejemplo": "https://app.example.test/licitaciones/abc",
}


def _admin() -> dict[str, Any]:
    return {"user_id": 1, "email": "admin@test.com", "is_admin": True, "auth_method": "session"}


def _no_admin() -> dict[str, Any]:
    return {"user_id": 2, "email": "user@test.com", "is_admin": False, "auth_method": "session"}


@pytest.fixture()
def cliente_admin() -> Iterator[TestClient]:
    app.dependency_overrides[require_any_auth] = _admin
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_quien_no_es_admin_recibe_403() -> None:
    app.dependency_overrides[require_any_auth] = _no_admin
    try:
        with patch("db.repositories.csp_violations.agrupadas") as agrupadas:
            resp = TestClient(app).get(_URL)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 403
    agrupadas.assert_not_called()


def test_devuelve_las_filas_agrupadas_con_su_forma(cliente_admin: TestClient) -> None:
    with patch("db.repositories.csp_violations.agrupadas", return_value=[_FILA]):
        resp = cliente_admin.get(_URL)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"dias": 30, "items": [_FILA]}


def test_dias_se_traduce_en_el_desde_del_sql(cliente_admin: TestClient) -> None:
    antes = datetime.now(UTC)
    with patch("db.repositories.csp_violations.agrupadas", return_value=[]) as agrupadas:
        resp = cliente_admin.get(_URL, params={"dias": 7, "limit": 5})
    despues = datetime.now(UTC)

    assert resp.status_code == 200, resp.text
    kwargs = agrupadas.call_args.kwargs
    assert kwargs["limit"] == 5
    desde = datetime.fromisoformat(kwargs["desde"])
    assert antes - timedelta(days=7) <= desde <= despues - timedelta(days=7)


@pytest.mark.parametrize("params", [{"dias": 0}, {"dias": 91}, {"limit": 0}, {"limit": 201}])
def test_rechaza_ventanas_y_limites_fuera_de_rango(
    cliente_admin: TestClient, params: dict[str, int]
) -> None:
    with patch("db.repositories.csp_violations.agrupadas") as agrupadas:
        resp = cliente_admin.get(_URL, params=params)

    assert resp.status_code == 422
    agrupadas.assert_not_called()
