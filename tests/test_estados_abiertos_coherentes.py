"""Todas las superficies coinciden en qué expediente sigue abierto.

`shared/estados.py` existe para que nadie reenumere la lista, pero exportar la
constante no impidió que cada llamante escribiera su propio fragmento SQL. Así
acabó `overview_para_hoy` con una lista blanca `estado IN ('PUB','EV')`: el
resumen contaba 0 activas sobre los mismos datos en los que el Radar listaba 12
—todos en `ADM`, que no es un estado terminal—. Cada uno decía la verdad según
su propia definición, y se contradecían en pantalla.

Lo que se fija aquí es la coherencia entre superficies, no el número: si mañana
cambia `ESTADOS_CERRADOS`, las tres se mueven juntas o el test cae.
"""

from __future__ import annotations

import pytest

from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from db.repositories.licitaciones import LicitacionRepository
from shared.estados import ESTADOS_CERRADOS, abierta_sql

# Un expediente por estado: los tres terminales, dos abiertos conocidos, uno
# abierto que la lista blanca se comía (`ADM`) y otro que la fuente aún no ha
# documentado.
_FILAS = (
    ("EST-PUB", "PUB"),
    ("EST-EV", "EV"),
    ("EST-ADM", "ADM"),
    ("EST-FUTURO", "XYZ"),
    ("EST-NULL", None),
    ("EST-RES", "RES"),
    ("EST-ADJ", "ADJ"),
    ("EST-ANUL", "ANUL"),
)

_ABIERTOS = {"EST-PUB", "EST-EV", "EST-ADM", "EST-FUTURO", "EST-NULL"}


@pytest.fixture()
def estados_db(tmp_db):
    db_mod, _ = tmp_db
    with db_mod.connect() as conn:
        for id_externo, estado in _FILAS:
            conn.execute(
                "INSERT INTO licitaciones (id_externo, titulo, estado, fecha_publicacion, "
                "fecha_limite, fecha_extraccion, tecnologia, importe) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    id_externo,
                    f"Licitación {id_externo}",
                    estado,
                    "2026-07-02",
                    "2027-01-01",
                    "2026-07-30T00:00:00+00:00",
                    "SAP",
                    100_000.0,
                ),
            )
    return db_mod


def test_abierta_sql_admite_nulos_y_estados_no_documentados():
    predicado = abierta_sql()

    assert "IS NULL" in predicado
    for cerrado in ESTADOS_CERRADOS:
        assert f"'{cerrado}'" in predicado
    # Nunca enumera la apertura: si apareciera un estado abierto concreto,
    # el siguiente que publique la fuente quedaría fuera.
    for abierto in ("PUB", "EV", "ADM"):
        assert f"'{abierto}'" not in predicado


def test_abierta_sql_admite_otra_columna():
    assert abierta_sql("l.estado").startswith("(l.estado IS NULL")


def test_el_resumen_y_el_listado_cuentan_lo_mismo(estados_db):
    """`total_activas` usaba lista blanca; el listado, la lista de cierre."""
    overview = AggregateRepository().overview_para_hoy(
        LicitacionesFilters(),
        hoy_iso="2026-08-08T00:00:00+00:00",
        limite_48h_iso="2026-08-10T00:00:00+00:00",
        hace_24h_iso="2026-08-07T00:00:00+00:00",
    )
    listados, _ = LicitacionRepository().list_paginated(
        limit=50, solo_abiertas=True, with_total=False
    )

    assert overview["total_activas"] == len(_ABIERTOS)
    assert {row["id_externo"] for row in listados} == _ABIERTOS


def test_el_ranking_ve_el_mismo_universo_que_el_resumen(estados_db):
    """El Radar puntúa `scoring_candidates`; el resumen cuenta `total_activas`."""
    puntuables = {row["id_externo"] for row in AggregateRepository().scoring_candidates()}
    overview = AggregateRepository().overview_para_hoy(
        LicitacionesFilters(),
        hoy_iso="2026-08-08T00:00:00+00:00",
        limite_48h_iso="2026-08-10T00:00:00+00:00",
        hace_24h_iso="2026-08-07T00:00:00+00:00",
    )

    assert puntuables == _ABIERTOS
    assert overview["total_activas"] == len(puntuables)


def test_calientes_hoy_no_descarta_un_expediente_en_admision(estados_db):
    """`calientes_hoy` llevaba la misma lista blanca que `total_activas`.

    Las ocho filas comparten importe, así que el P75 las incluye a todas: lo
    único que decide es el estado y la fecha límite.
    """
    overview = AggregateRepository().overview_para_hoy(
        LicitacionesFilters(),
        hoy_iso="2026-08-08T00:00:00+00:00",
        limite_48h_iso="2026-08-10T00:00:00+00:00",
        hace_24h_iso="2026-08-07T00:00:00+00:00",
    )

    assert overview["calientes_hoy"] == len(_ABIERTOS)
