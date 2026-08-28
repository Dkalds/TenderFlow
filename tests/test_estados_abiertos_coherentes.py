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

# Un expediente por estado: los cinco terminales, tres abiertos conocidos, uno
# abierto que la lista blanca se comía (`ADM`) y otro que la fuente aún no ha
# documentado.
_FILAS = (
    ("EST-PUB", "PUB"),
    ("EST-EV", "EV"),
    ("EST-CPM", "CPM"),
    ("EST-ADM", "ADM"),
    ("EST-FUTURO", "XYZ"),
    ("EST-NULL", None),
    ("EST-RES", "RES"),
    ("EST-ADJ", "ADJ"),
    ("EST-ANUL", "ANUL"),
    # Las dos fases PSCP canonizadas en v91. `AGR` es el caso que motivó el
    # cambio: 645.664 filas que contaban como abiertas por no estar mapeadas.
    ("EST-AGR", "AGR"),
    ("EST-EJEC", "EJEC"),
)

_ABIERTOS = {"EST-PUB", "EST-EV", "EST-CPM", "EST-ADM", "EST-FUTURO", "EST-NULL"}


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


def test_las_fases_pscp_canonizadas_cuentan_como_cerradas():
    """`AGR` y `EJEC` son terminales, y eso es una decisión, no un detalle.

    Mientras `PUBLICACIÓ AGREGADA` no estuvo mapeada contaba como abierta por
    omisión, y el "Total activas" del Resumen decía 657.156 sobre un corpus de
    691.974. Si alguien las saca de `ESTADOS_CERRADOS` sin querer, el KPI
    vuelve a medir el tamaño del corpus.
    """
    assert "AGR" in ESTADOS_CERRADOS
    assert "EJEC" in ESTADOS_CERRADOS
    # `CPM` (consulta preliminar) sí es una oportunidad futura: abierta.
    assert "CPM" not in ESTADOS_CERRADOS


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


def test_el_ranking_aplica_la_misma_regla_de_estado_que_el_resumen(estados_db):
    """El Radar puntúa `scoring_candidates`; el resumen cuenta `total_activas`.

    Con el plazo vivo en todas las filas del fixture, lo único que decide es el
    estado — y ahí las dos superficies tienen que coincidir, que es el fallo
    que este módulo fija.
    """
    puntuables = {
        row["id_externo"] for row in AggregateRepository().scoring_candidates(hoy_iso="2026-08-08")
    }
    overview = AggregateRepository().overview_para_hoy(
        LicitacionesFilters(),
        hoy_iso="2026-08-08T00:00:00+00:00",
        limite_48h_iso="2026-08-10T00:00:00+00:00",
        hace_24h_iso="2026-08-07T00:00:00+00:00",
    )

    assert puntuables == _ABIERTOS
    assert overview["total_activas"] == len(puntuables)


def test_el_ranking_ademas_exige_plazo_y_por_eso_puede_contar_menos(estados_db):
    """La única divergencia permitida entre ranking y resumen, y es deliberada.

    `total_activas` responde "cuántas siguen vivas en el sistema"; el ranking,
    "a cuántas puedo presentarme hoy". Sin esa segunda pregunta el universo
    puntuable era el 91% de la tabla (1,5 M filas en producción) y la API moría
    cargándolo. Lo que no puede pasar es que diverjan por el *estado*: eso lo
    fija el test de arriba.
    """
    puntuables = {
        row["id_externo"] for row in AggregateRepository().scoring_candidates(hoy_iso="2027-06-01")
    }
    overview = AggregateRepository().overview_para_hoy(
        LicitacionesFilters(),
        hoy_iso="2027-06-01T00:00:00+00:00",
        limite_48h_iso="2027-06-03T00:00:00+00:00",
        hace_24h_iso="2027-05-31T00:00:00+00:00",
    )

    # Todas las filas del fixture vencen el 2027-01-01: ninguna es puntuable ya.
    assert puntuables == set()
    assert overview["total_activas"] == len(_ABIERTOS)


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
