"""``PATCH /pursuits/cartera/{id}``: la fecha de fin puesta a mano, por su ruta.

La regla —quién puede, qué fecha vale, qué se devuelve— vive en
``services.cartera.fijar_fecha_fin`` y tiene sus tests en
``tests/test_cartera_escritor.py``. Lo que solo vive en la ruta es **qué código
recibe cada fallo**, y eso es lo que la consola lee para decidir qué decirle a
quien acaba de escribir una fecha: un 404 es «ese contrato no es tuyo», un 422
es «esa fecha no puede ser» y un 403 es «no puedes escribir aquí». Con los tres
aplastados en un 500 la capa de la fila solo podría decir «algo falló».

El camino contra Postgres está en ``tests/test_cartera_escritor_integration.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from services.cartera import CarteraNoEncontradaError, ContratoCartera, FechaFinInvalidaError
from services.organizations import OrganizationAccessError, OrganizationPermissionError

_RUTA = "/api/v1/pursuits/cartera/11"


@pytest.fixture
def client() -> Iterator[TestClient]:
    from api.app import app
    from api.routes.dual_auth import require_any_auth

    app.dependency_overrides[require_any_auth] = lambda: {
        "user_id": 5,
        "user_key": "cartera-5",
        "scopes": ["*"],
    }
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.clear()


def test_devuelve_el_contrato_como_queda_tras_guardar(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    llamadas: list[tuple[Any, ...]] = []

    def _fijar(
        user_id: int, cartera_id: int, fecha_fin: date, *, organization_id: int | None = None
    ) -> ContratoCartera:
        llamadas.append((user_id, cartera_id, fecha_fin, organization_id))
        return ContratoCartera(
            id=11,
            organization_id=7,
            pursuit_id=3,
            licitacion_id="LIC-1",
            fecha_fin_efectiva="2027-06-30",
            fecha_fin_origen="manual",
            relicitacion_desde="2026-12-30",
            relicitacion_hasta="2027-03-30",
        )

    monkeypatch.setattr("api.routes.pursuits.fijar_fecha_fin", _fijar)

    respuesta = client.patch(_RUTA, params={"organization_id": 7}, json={"fecha_fin": "2027-06-30"})

    assert respuesta.status_code == 200, respuesta.text
    # La fecha llega ya como fecha: la ruta no le pasa texto al servicio.
    assert llamadas == [(5, 11, date(2027, 6, 30), 7)]
    cuerpo = respuesta.json()
    assert (cuerpo["fecha_fin_efectiva"], cuerpo["fecha_fin_origen"]) == ("2027-06-30", "manual")
    # La ventana viaja en la misma respuesta: la fila la pinta sin otra petición.
    assert cuerpo["relicitacion_desde"] == "2026-12-30"


@pytest.mark.parametrize(
    ("fallo", "estado"),
    [
        (CarteraNoEncontradaError("Contrato no encontrado en la cartera."), 404),
        (FechaFinInvalidaError("La fecha de fin no puede ser anterior al inicio."), 422),
        (OrganizationAccessError("No perteneces a esta organización."), 403),
        (OrganizationPermissionError("Tu rol no permite escribir."), 403),
    ],
)
def test_cada_fallo_tiene_su_codigo(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, fallo: Exception, estado: int
) -> None:
    def _falla(*_a: Any, **_k: Any) -> ContratoCartera:
        raise fallo

    monkeypatch.setattr("api.routes.pursuits.fijar_fecha_fin", _falla)

    respuesta = client.patch(_RUTA, json={"fecha_fin": "2027-06-30"})

    assert respuesta.status_code == estado
    assert respuesta.json()["detail"] == str(fallo)


@pytest.mark.parametrize(
    "cuerpo",
    [
        {},
        {"fecha_fin": None},
        {"fecha_fin": "31/12/2027"},
        {"fecha_fin": "2027-06-30", "fecha_fin_origen": "publicada"},
    ],
)
def test_un_cuerpo_que_no_es_una_fecha_no_llega_al_servicio(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, cuerpo: dict[str, Any]
) -> None:
    """El origen no se elige: una fecha puesta por esta ruta es ``manual``."""
    llamado: list[bool] = []
    monkeypatch.setattr("api.routes.pursuits.fijar_fecha_fin", lambda *a, **k: llamado.append(True))

    assert client.patch(_RUTA, json=cuerpo).status_code == 422
    assert llamado == []
