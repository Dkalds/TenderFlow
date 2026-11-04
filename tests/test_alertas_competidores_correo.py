"""Las alertas de competidores van al correo de la cuenta, nunca a uno cualquiera.

``POST /competitive/watchlist`` aceptaba un ``email`` libre y
``scheduler/competitor_alerts.py`` enviaba la vigilancia allí: cualquiera podía
apuntar a un tercero a recibir correos de la aplicación. Las reglas de
watchlist ya tomaban el correo de la sesión; esto lo iguala, en el alta y en el
envío (las filas guardadas antes del arreglo pueden traer el correo ajeno).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.escenarios import abrir_sesion
from tests.test_competitive import insert_contract, resolve


@pytest.fixture()
def empresa_id(client: Any, api_db: Any) -> int:
    import db.database as db_mod
    from db.database import connect_read

    insert_contract(db_mod, "ALR-1", "Rival Alertas SL", nif="B33333333")
    resolve(db_mod)
    with connect_read() as c:
        fila = c.execute(
            "SELECT empresa_id FROM empresas WHERE nombre_canonico = %s", ("Rival Alertas SL",)
        ).fetchone()
    return int(fila[0])


def test_un_correo_ajeno_en_el_alta_es_un_422(client: Any, empresa_id: int) -> None:
    sesion = abrir_sesion("vigila@example.com", client)
    resp = sesion.post(
        "/competitive/watchlist", json={"empresa_id": empresa_id, "email": "tercero@example.com"}
    )
    assert resp.status_code == 422, resp.text


def test_el_propio_correo_se_acepta_y_es_el_que_se_guarda(client: Any, empresa_id: int) -> None:
    from db.watchlist_empresas import list_all

    sesion = abrir_sesion("propio@example.com", client)
    resp = sesion.post(
        "/competitive/watchlist", json={"empresa_id": empresa_id, "email": "Propio@Example.com"}
    )
    assert resp.status_code == 201, resp.text
    assert [e["email"] for e in list_all()] == ["propio@example.com"]


def test_el_envio_usa_el_correo_de_la_cuenta_y_no_el_guardado(client: Any, empresa_id: int) -> None:
    """Una fila de antes del arreglo con un correo ajeno ya no se lo manda a él."""
    from db.users import deactivate_user
    from db.watchlist_empresas import WatchlistEmpresaEntry, add_entry, list_all

    sesion = abrir_sesion("cuenta@example.com", client)
    add_entry(
        WatchlistEmpresaEntry(
            user_key="clave-opaca",
            user_id=sesion.user_id,
            empresa_id=empresa_id,
            organization_id=sesion.organization_id,
            email="tercero@example.com",
        )
    )
    assert [e["email"] for e in list_all()] == ["cuenta@example.com"]

    deactivate_user(sesion.user_id)
    assert list_all() == []
