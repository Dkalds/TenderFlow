"""F1.4 — la tasa de anulación o desierto por órgano, calculada en Postgres.

El fixture es el del plan: un órgano con el 40 % de sus expedientes resueltos
anulados o desiertos. Se comprueba que la tasa sale de SQL con sus conteos, que
lo abierto no diluye el denominador, que el desierto llega por el resultado de
adjudicación y que el scoring la convierte en el flag.
"""

from __future__ import annotations

from typing import Any

_ORGANO = "Ayuntamiento de Anulaciones"
_DESDE = "2024-09-01"


def _licitacion(
    id_externo: str, *, estado: str, cpv: str = "72260000", organo: str = _ORGANO
) -> None:
    from db.database import connect

    with connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, estado, "
            "fecha_publicacion, fecha_extraccion) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                id_externo,
                f"Contrato {id_externo}",
                organo,
                cpv,
                estado,
                "2025-06-01",
                "2025-06-01T00:00:00+00:00",
            ),
        )


def _adjudicacion(licitacion_id: str, result_code: str) -> None:
    from db.database import connect

    with connect() as conn:
        conn.execute(
            "INSERT INTO adjudicaciones (licitacion_id, nombre, result_code, fecha_extraccion) "
            "VALUES (%s, %s, %s, %s)",
            (licitacion_id, "Empresa", result_code, "2025-07-01T00:00:00+00:00"),
        )


def _sembrar() -> None:
    # 10 resueltos: 6 adjudicados, 3 anulados y 1 desierto por resultado → 40 %.
    for i in range(6):
        _licitacion(f"ANU-ADJ-{i}", estado="ADJ")
    for i in range(3):
        _licitacion(f"ANU-ANUL-{i}", estado="ANUL")
    _licitacion("ANU-DESIERTO", estado="RES")
    _adjudicacion("ANU-DESIERTO", "3")
    # Abiertos: no cuentan en el denominador.
    for i in range(5):
        _licitacion(f"ANU-PUB-{i}", estado="PUB")
    # Otro órgano sin anulaciones.
    for i in range(10):
        _licitacion(f"OTRO-{i}", estado="ADJ", organo="Diputación Cumplidora")


def test_la_tasa_sale_de_sql_con_sus_conteos(tmp_db: Any) -> None:
    from db.repositories.tasas_anulacion import recalcular, tasas_por_organos

    _sembrar()
    assert recalcular(desde_iso=_DESDE) > 0

    tasas = tasas_por_organos([_ORGANO.lower(), "diputación cumplidora"])
    assert tasas[(_ORGANO.lower(), "*")] == (10, 4)
    assert tasas[(_ORGANO.lower(), "7226")] == (10, 4)
    assert tasas[("diputación cumplidora", "*")] == (10, 0)


def test_recalcular_reemplaza_y_respeta_la_ventana(tmp_db: Any) -> None:
    from db.repositories.tasas_anulacion import recalcular, tasas_por_organos

    _sembrar()
    recalcular(desde_iso=_DESDE)
    # Una ventana que empieza después de todo lo sembrado deja la tabla vacía:
    # no se acumulan filas de pasadas anteriores.
    assert recalcular(desde_iso="2026-01-01") == 0
    assert tasas_por_organos([_ORGANO.lower()]) == {}


def test_el_scoring_marca_el_organo(tmp_db: Any) -> None:
    import pandas as pd

    from db.repositories.tasas_anulacion import recalcular
    from services.analytics import scoring as sc_mod

    _sembrar()
    recalcular(desde_iso=_DESDE)
    df = pd.DataFrame(
        [
            {"id_externo": "X1", "organo_contratacion": _ORGANO, "cpv": "72260000"},
            {"id_externo": "X2", "organo_contratacion": "Diputación Cumplidora", "cpv": "72"},
        ]
    )
    tasas = sc_mod._load_tasas_anulacion(df)
    assert tasas is not None
    assert sc_mod.tasa_anulacion(_ORGANO, "72260000", tasas) == (0.4, 10)
    assert sc_mod.tasa_anulacion("Diputación Cumplidora", "72", tasas) == (0.0, 10)
