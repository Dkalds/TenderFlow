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


def test_cu18_de_la_concentracion_del_segmento_a_la_baja_de_referencia(client, api_db):
    """CU-18 — qué segmento está concentrado, quién se lo reparte y a qué baja se gana.

    Es el recorrido de «Mercado por segmento» en Competencia: el HHI ordena los
    segmentos, la cuota dice quién manda en el elegido y la baja de referencia,
    cuánto se rebajó para ganarlo. Las tres cifras miden el mismo universo.
    """
    import db.database as db_mod

    # CPV 72: una empresa con casi todo. CPV 48: tres a partes iguales.
    insert_contract(db_mod, "SEG-72-1", "Dominante SL", importe=500_000.0, adjudicado=400_000.0)
    insert_contract(db_mod, "SEG-72-2", "Dominante SL", importe=250_000.0, adjudicado=200_000.0)
    insert_contract(db_mod, "SEG-72-3", "Menor SA", importe=40_000.0, adjudicado=36_000.0)
    for i, nombre in enumerate(("Uno SL", "Dos SL", "Tres SL")):
        insert_contract(
            db_mod,
            f"SEG-48-{i}",
            nombre,
            cpv="48000000",
            organo="Diputación Z",
            importe=125_000.0,
            adjudicado=100_000.0,
        )
    resolve(db_mod)
    sesion = abrir_sesion("segmentos@example.com", client)

    hhi = sesion.get("/competitive/hhi", params={"segment_by": "cpv", "min_contratos": 1})
    assert hhi.status_code == 200, hhi.text
    segmentos = {s["segmento"]: s for s in hhi.json()["items"]}
    # El más concentrado primero; el reparto a tercios es exactamente 3.333.
    assert [s["segmento"] for s in hhi.json()["items"]] == ["72", "48"]
    assert segmentos["72"]["hhi"] > 2500
    assert round(segmentos["48"]["hhi"]) == 3333
    assert (segmentos["72"]["empresas"], segmentos["72"]["contratos"]) == (2, 3)

    # Quién se reparte el segmento 72, con su cuota sobre ese segmento.
    cuota = sesion.get("/competitive/cuota", params={"cpv": "72", "limit": 10})
    assert cuota.status_code == 200, cuota.text
    reparto = [(c["empresa"], c["contratos"], c["cuota_pct"]) for c in cuota.json()["items"]]
    assert reparto == [("Dominante SL", 2, 94.34), ("Menor SA", 1, 5.66)]
    assert cuota.json()["scope"]["filters"] == {"cpv_prefix": "72"}
    assert cuota.json()["scope"]["denominator_records"] == 3

    # A qué baja se gana ahí: 20 % y 10 %, y sobre qué base de importe.
    referencia = sesion.get("/competitive/bajas/referencia", params={"cpv": "72"})
    assert referencia.status_code == 200, referencia.text
    ref = referencia.json()
    assert (ref["contratos"], ref["baja_min_pct"], ref["baja_max_pct"]) == (3, 10, 20)
    assert ref["base"] == "mixta"

    # Y por órgano, las bajas del ámbito con su masa mínima.
    bajas = sesion.get("/competitive/bajas", params={"group_by": "organo", "min_contratos": 3})
    assert bajas.status_code == 200, bajas.text
    por_organo = {b["grupo"]: b for b in bajas.json()["items"]}
    assert set(por_organo) == {"Ministerio X", "Diputación Z"}
    assert por_organo["Diputación Z"]["baja_media_pct"] == 20
    assert bajas.json()["base"] == "mixta"
