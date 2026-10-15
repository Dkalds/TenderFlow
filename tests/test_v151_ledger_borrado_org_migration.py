"""v151: el ledger se va con la organización, y con nada más.

La migración abre una sola puerta en el trigger append-only de
``pursuit_events``: el ``DELETE`` de los eventos de una organización que ya no
existe, que es lo que hace la cascada de ``POST /organizations/{id}/delete``.
Aquí se fija que esa puerta no se ensancha: un evento suelto no se borra, una
oportunidad sola no arrastra su historia y ningún evento se reescribe.
"""

from __future__ import annotations

import psycopg
import pytest

from tests.escenarios import abrir_sesion, sembrar_licitacion


def _organizacion_con_historia(client) -> tuple[int, int]:
    sembrar_licitacion("EXP-LEDGER-1", "Mantenimiento con historia")
    sesion = abrir_sesion("ledger@example.com", client)
    oid = sesion.post("/organizations", json={"name": "Equipo con ledger"}).json()["id"]
    pid = sesion.post(
        "/pursuits", json={"licitacion_id": "EXP-LEDGER-1", "organization_id": oid}
    ).json()["id"]
    movida = sesion.patch(
        f"/pursuits/{pid}", params={"organization_id": oid}, json={"status": "qualifying"}
    )
    assert movida.status_code == 200, movida.text
    return oid, pid


def _eventos(oid: int) -> int:
    from db.database import connect

    with connect() as c:
        fila = c.execute(
            "SELECT count(*) FROM pursuit_events WHERE organization_id = %s", (oid,)
        ).fetchone()
    return int(fila[0]) if fila else 0


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM pursuit_events WHERE organization_id = %s",
        "UPDATE pursuit_events SET payload_json = '{}' WHERE organization_id = %s",
        "DELETE FROM pursuits WHERE organization_id = %s",
    ],
    ids=["evento-suelto", "reescritura", "oportunidad-sola"],
)
def test_con_la_organizacion_viva_el_ledger_no_se_toca(client, api_db, sql):
    from db.database import connect

    oid, _ = _organizacion_con_historia(client)
    antes = _eventos(oid)
    assert antes > 0

    with pytest.raises(psycopg.errors.RaiseException, match="append-only"), connect() as c:
        c.execute(sql, (oid,))
    assert _eventos(oid) == antes


def test_borrar_la_organizacion_se_lleva_su_ledger(client, api_db):
    from db.database import connect

    oid, _ = _organizacion_con_historia(client)

    with connect() as c:
        c.execute("DELETE FROM organizations WHERE id = %s", (oid,))

    assert _eventos(oid) == 0
