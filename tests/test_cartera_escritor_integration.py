"""F4.3 — el escritor de la cartera contra Postgres.

Lo que ``tests/test_cartera_escritor.py`` fija con el repositorio doblado,
aquí se comprueba de punta a punta: cerrar como ganada por la API deja el
contrato en la cartera, una prórroga registrada por ``contract_events`` mueve
la fecha de fin en la resincronización, «preparar renovación» crea una sola
oportunidad enlazada, y los avisos no se repiten.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.routes.dual_auth import require_any_auth
from db.repositories.cartera import CarteraRepository
from db.repositories.organizations import OrganizationRepository
from shared.dto import PursuitCreate

_GANADA = "LIC-ESCR-GANADA"
_RELICITACION = "LIC-ESCR-RELICITACION"
_AJENA = "LIC-ESCR-AJENA"


class _Sesion:
    user_id: int | None = None

    def __call__(self) -> dict[str, Any]:
        return {"user_id": self.user_id, "auth_method": "session", "user_key": "escritor"}


@pytest.fixture()
def sesion(api_db: Any) -> Iterator[_Sesion]:
    from api.app import app

    principal = _Sesion()
    app.dependency_overrides[require_any_auth] = principal
    try:
        yield principal
    finally:
        app.dependency_overrides.pop(require_any_auth, None)


def _user(email: str) -> int:
    from db.users import create_user

    return create_user(email=email, password_hash="test-hash")  # pragma: allowlist secret


def _licitacion(id_externo: str, **campos: Any) -> None:
    from db.database import connect

    columnas = {
        "id_externo": id_externo,
        "titulo": f"Contrato {id_externo}",
        "organo_contratacion": "Ayuntamiento de Prueba",
        "fecha_limite": "2025-01-15T10:00:00+00:00",
        "fecha_extraccion": "2025-01-01T10:00:00+00:00",
        **campos,
    }
    nombres = ", ".join(columnas)
    marcas = ", ".join(["%s"] * len(columnas))
    with connect() as conn:
        conn.execute(
            f"INSERT INTO licitaciones ({nombres}) VALUES ({marcas})",  # noqa: S608 - columnas fijas del test
            tuple(columnas.values()),
        )


def _presentada(owner: int, organization_id: int, licitacion_id: str) -> int:
    """Oportunidad ya presentada: el paso previo a ganar."""
    from db.database import connect
    from services.pursuits import create_pursuit

    creado, _ = create_pursuit(
        owner, PursuitCreate(licitacion_id=licitacion_id, organization_id=organization_id)
    )
    with connect() as conn:
        conn.execute(
            "UPDATE pursuits SET status = 'submitted', decision = 'go', "
            "decision_reason = 'encaja', submitted_at = '2025-01-10T00:00:00+00:00' "
            "WHERE id = %s",
            (int(creado.id),),
        )
    return int(creado.id)


@pytest.fixture()
def equipo(sesion: _Sesion) -> tuple[int, int]:
    owner = _user("owner-escritor@example.test")
    organizacion = int(OrganizationRepository().create_organization("Equipo", owner)["id"])
    sesion.user_id = owner
    return owner, organizacion


def _ganar(client: TestClient, organizacion: int, pursuit_id: int) -> None:
    respuesta = client.patch(
        f"/api/v1/pursuits/{pursuit_id}",
        params={"organization_id": organizacion},
        json={"status": "won", "awarded_amount_eur": 150000},
    )
    assert respuesta.status_code == 200, respuesta.text


def test_cerrar_como_ganada_deja_el_contrato_en_la_cartera(
    client: TestClient, equipo: tuple[int, int]
) -> None:
    owner, organizacion = equipo
    _licitacion(_GANADA, fecha_inicio="2025-03-01", duracion_valor=24.0, duracion_unidad="MON")
    pursuit_id = _presentada(owner, organizacion, _GANADA)

    _ganar(client, organizacion, pursuit_id)

    fila = CarteraRepository().get_by_pursuit(organizacion, pursuit_id)
    assert fila is not None
    assert fila["fecha_fin_efectiva"] == "2027-03-01"
    assert fila["fecha_fin_origen"] == "duracion"
    assert fila["importe_adjudicado"] == 150000.0

    cartera = client.get("/api/v1/pursuits/cartera", params={"organization_id": organizacion})
    assert [c["pursuit_id"] for c in cartera.json()] == [pursuit_id]


def test_una_prorroga_registrada_mueve_la_fecha_de_fin(
    client: TestClient, equipo: tuple[int, int]
) -> None:
    from db.database import connect
    from services.cartera import sincronizar_cartera

    owner, organizacion = equipo
    _licitacion(_GANADA, fecha_fin="2026-12-31")
    pursuit_id = _presentada(owner, organizacion, _GANADA)
    _ganar(client, organizacion, pursuit_id)

    # Lo que deja `contract_events` al detectar la prórroga: la licitación con
    # la fecha nueva y el evento que la registra.
    with connect() as conn:
        conn.execute(
            "UPDATE licitaciones SET fecha_fin = '2027-12-31' WHERE id_externo = %s", (_GANADA,)
        )
        conn.execute(
            "INSERT INTO contrato_eventos (licitacion_id, tipo, fecha, campo, valor_antes, "
            "valor_despues) VALUES (%s, 'prorroga', '2026-06-01', 'fecha_fin', "
            "'2026-12-31', '2027-12-31')",
            (_GANADA,),
        )

    resumen = sincronizar_cartera(dry_run=False)
    assert resumen.actualizados == 1

    fila = CarteraRepository().get_by_pursuit(organizacion, pursuit_id)
    assert fila is not None
    assert (fila["fecha_fin_efectiva"], fila["fecha_fin_origen"]) == ("2027-12-31", "prorroga")
    assert fila["prorrogas_aplicadas"] == 1

    # Idempotente: la segunda pasada no escribe.
    assert sincronizar_cartera(dry_run=False).actualizados == 0


def test_preparar_renovacion_crea_una_sola_oportunidad(
    client: TestClient, equipo: tuple[int, int]
) -> None:
    owner, organizacion = equipo
    _licitacion(_GANADA, fecha_fin="2026-12-31")
    _licitacion(_RELICITACION)
    pursuit_id = _presentada(owner, organizacion, _GANADA)
    _ganar(client, organizacion, pursuit_id)
    fila = CarteraRepository().get_by_pursuit(organizacion, pursuit_id)
    assert fila is not None
    ruta = f"/api/v1/pursuits/cartera/{fila['id']}/renovacion"

    primera = client.post(
        ruta, params={"organization_id": organizacion}, json={"licitacion_id": _RELICITACION}
    )
    assert primera.status_code == 200, primera.text
    assert primera.json()["creada"] is True
    renovacion_id = primera.json()["renovacion_pursuit_id"]

    segunda = client.post(
        ruta, params={"organization_id": organizacion}, json={"licitacion_id": _RELICITACION}
    )
    assert segunda.json() == {
        "cartera_id": fila["id"],
        "renovacion_pursuit_id": renovacion_id,
        "creada": False,
    }

    detalle = client.get(
        f"/api/v1/pursuits/{renovacion_id}", params={"organization_id": organizacion}
    ).json()
    assert detalle["status"] == "identified"
    assert detalle["licitacion_id"] == _RELICITACION
    comentarios = client.get(
        f"/api/v1/pursuits/{renovacion_id}/comments", params={"organization_id": organizacion}
    ).json()
    assert any(_GANADA in c["body"] for c in comentarios["items"])


def test_preparar_renovacion_rechaza_el_expediente_vigente_y_lo_ajeno(
    client: TestClient, sesion: _Sesion, equipo: tuple[int, int]
) -> None:
    owner, organizacion = equipo
    _licitacion(_GANADA, fecha_fin="2026-12-31")
    _licitacion(_AJENA, fecha_fin="2026-12-31")
    pursuit_id = _presentada(owner, organizacion, _GANADA)
    _ganar(client, organizacion, pursuit_id)
    fila = CarteraRepository().get_by_pursuit(organizacion, pursuit_id)
    assert fila is not None

    mismo = client.post(
        f"/api/v1/pursuits/cartera/{fila['id']}/renovacion",
        params={"organization_id": organizacion},
        json={"licitacion_id": _GANADA},
    )
    assert mismo.status_code == 422

    otro = _user("otro-escritor@example.test")
    ajena = int(OrganizationRepository().create_organization("Ajena", otro)["id"])
    sesion.user_id = otro
    respuesta = client.post(
        f"/api/v1/pursuits/cartera/{fila['id']}/renovacion",
        params={"organization_id": ajena},
        json={"licitacion_id": _AJENA},
    )
    assert respuesta.status_code == 404


def test_los_avisos_no_se_repiten(client: TestClient, equipo: tuple[int, int]) -> None:
    from db.events import get_events
    from services.cartera import EVENTO_CARTERA_VENCE, emitir_avisos_de_fin

    owner, organizacion = equipo
    _licitacion(_GANADA, fecha_fin="2026-11-30")
    pursuit_id = _presentada(owner, organizacion, _GANADA)
    _ganar(client, organizacion, pursuit_id)
    fila = CarteraRepository().get_by_pursuit(organizacion, pursuit_id)
    assert fila is not None

    hoy = date(2026, 9, 19)
    assert emitir_avisos_de_fin(hoy) == 1
    assert emitir_avisos_de_fin(hoy) == 0
    eventos = get_events("contrato_cartera", fila["id"], event_type=EVENTO_CARTERA_VENCE)
    assert [e["payload"]["meses"] for e in eventos] == [3]
    assert eventos[0]["payload"]["destinatarios"] == [owner]
