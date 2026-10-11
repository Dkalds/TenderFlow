"""Escenario de competencia: del ranking a vigilar a un rival.

Recorrido completo por la API con sesión real. Ver ``tests/escenarios.py`` y
``docs/casos-de-uso.md``. Las adjudicaciones las trae la ingesta, así que se
siembran con los mismos ayudantes que ``tests/test_competitive.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tests.escenarios import abrir_sesion
from tests.test_competitive import insert_contract, resolve


def test_cu18_del_ranking_al_perfil_del_rival_y_a_vigilarlo(client, api_db):
    """CU-18 — quién gana, cómo es el que más gana, y enterarse de lo siguiente que haga."""
    import db.database as db_mod

    reciente = (datetime.now(UTC) - timedelta(days=5)).strftime("%Y-%m-%d")
    insert_contract(
        db_mod,
        "CMP-1",
        "Rival Consultores SL",
        nif="B11111111",
        importe=350_000.0,
        adjudicado=300_000.0,
    )
    insert_contract(
        db_mod,
        "CMP-2",
        "Rival Consultores SL",
        nif="B11111111",
        importe=210_000.0,
        adjudicado=200_000.0,
        ccaa="Galicia",
        fecha_adjudicacion=reciente,
    )
    insert_contract(
        db_mod,
        "CMP-3",
        "Pequeña Integradora SA",
        nif="A22222222",
        importe=60_000.0,
        adjudicado=50_000.0,
    )
    resolve(db_mod)
    sesion = abrir_sesion("competencia@example.com", client)

    # El ranking ordena por lo adjudicado y reparte la cuota entre todas.
    mercado = sesion.get("/analytics/competitors")
    assert mercado.status_code == 200, mercado.text
    datos = mercado.json()
    assert [c["nombre"] for c in datos["competitors"]] == [
        "Rival Consultores SL",
        "Pequeña Integradora SA",
    ]
    assert datos["total_adjudicaciones"] == 3
    assert datos["importe_total"] == 550_000
    assert round(sum(c["cuota"] for c in datos["competitors"])) == 100
    rival = datos["competitors"][0]
    assert (rival["count"], rival["importe"]) == (2, 500_000)

    # Su perfil cuenta lo mismo que el ranking, y dice dónde está en el mercado.
    perfil = sesion.get(f"/competitive/empresas/{rival['empresa_id']}/perfil")
    assert perfil.status_code == 200, perfil.text
    ficha = perfil.json()
    assert ficha["empresa"]["nombre"] == "Rival Consultores SL"
    assert (ficha["totales"]["contratos"], ficha["totales"]["importe_total"]) == (2, 500_000)
    assert (ficha["posicion_mercado"]["rank"], ficha["posicion_mercado"]["empresas"]) == (1, 2)
    assert ficha["totales"]["territorios"] == 2

    # Y sus adjudicaciones, la más reciente primero.
    contratos = sesion.get(f"/competitive/empresas/{rival['empresa_id']}/adjudicaciones").json()
    assert [c["licitacion_id"] for c in contratos["items"]] == ["CMP-2", "CMP-1"]
    assert contratos["total"] == ficha["totales"]["contratos"]

    # Vigilarlo trae lo que ha hecho en el último mes, explicado.
    assert sesion.get("/competitive/watchlist").json()["items"] == []
    vigilada = sesion.post("/competitive/watchlist", json={"empresa_id": rival["empresa_id"]})
    assert vigilada.status_code == 201, vigilada.text
    (entrada,) = sesion.get("/competitive/watchlist").json()["items"]
    assert entrada["nombre_canonico"] == "Rival Consultores SL"

    movimientos = sesion.get("/competitive/watchlist/movimientos", params={"dias": 30}).json()
    assert [(e["nombre"], e["adjudicaciones"]) for e in movimientos["empresas"]] == [
        ("Rival Consultores SL", 1)
    ]
    (senal,) = movimientos["senales"]
    assert (senal["tipo"], senal["licitacion_id"]) == ("nueva_ccaa", "CMP-2")

    # Otra persona no hereda la vigilancia.
    otra = abrir_sesion("otra-competencia@example.com")
    assert otra.get("/competitive/watchlist").json()["items"] == []

    assert sesion.delete(f"/competitive/watchlist/{rival['empresa_id']}").status_code == 200
    assert sesion.get("/competitive/watchlist").json()["items"] == []
    assert sesion.get("/competitive/watchlist/movimientos").json()["empresas"] == []
