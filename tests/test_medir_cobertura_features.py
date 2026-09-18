"""Medición de cobertura de las features pendientes del modelo de baja.

El P3 «Medir la cobertura de procedimiento, tramitacion y peso_precio_pct»
pedía un número con fecha antes de decidir si entran en ``FEATURE_COLUMNS``.
Estos tests fijan el script que lo produce; el número en sí sale de una BD real.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scripts.medir_cobertura_features import (
    CAMPOS,
    UMBRAL_COBERTURA_PCT,
    con_porcentajes,
    render_markdown,
)


def test_mide_exactamente_las_features_pendientes():
    """Si alguien añade una cuarta candidata, el script tiene que medirla."""
    from services.ml.features import FEATURES_PENDIENTES_COBERTURA

    assert CAMPOS == FEATURES_PENDIENTES_COBERTURA
    assert UMBRAL_COBERTURA_PCT == 50.0


def _fila(poblacion: str, n: int, **kw: Any) -> dict[str, Any]:
    base = {
        "poblacion": poblacion,
        "por_fuente": False,
        "por_anio": False,
        "fuente": None,
        "anio": None,
        "n": n,
        "procedimiento": 0,
        "tramitacion": 0,
        "peso_precio_pct": 0,
    }
    return {**base, **kw}


def test_porcentajes_y_poblacion_vacia():
    filas = con_porcentajes(
        [
            _fila("dataset_baja", 200, procedimiento=150, tramitacion=40, peso_precio_pct=0),
            _fila("universo_abierto", 0),
        ]
    )
    assert filas[0]["procedimiento_pct"] == 75.0
    assert filas[0]["tramitacion_pct"] == 20.0
    assert filas[0]["peso_precio_pct_pct"] == 0.0
    # Sin filas no hay porcentaje: None, nunca un 0 % inventado.
    assert filas[1]["procedimiento_pct"] is None


def test_el_veredicto_solo_mira_el_total_del_dataset():
    filas = con_porcentajes(
        [
            _fila("dataset_baja", 100, procedimiento=50, tramitacion=49, peso_precio_pct=10),
            # Un corte al 100 % no convierte el total en «supera».
            _fila("dataset_baja", 10, por_fuente=True, fuente="placsp", tramitacion=10),
            _fila("universo_abierto", 100, tramitacion=100),
        ]
    )
    informe = render_markdown(filas)
    assert "`procedimiento`: 50.0 % — supera" in informe
    assert "`tramitacion`: 49.0 % — no supera" in informe
    assert "`peso_precio_pct`: 10.0 % — no supera" in informe
    assert "fuente=placsp" in informe


def test_sin_dataset_no_hay_veredicto():
    assert "sin filas en el dataset de baja" in render_markdown(con_porcentajes([]))


def test_la_query_pasa_los_parametros_del_dataset():
    """El SQL del dataset lleva el corte de fecha plausible como ``%s``."""
    from db.repositories import ml_dataset

    conexion = MagicMock()
    contexto = MagicMock()
    contexto.__enter__.return_value = conexion
    with (
        patch.object(ml_dataset, "connect_read", return_value=contexto),
        patch.object(ml_dataset, "rows_to_dicts", return_value=[]),
    ):
        assert ml_dataset.MlDatasetRepository().cobertura_features_pendientes() == []
    sql, params = conexion.execute.call_args.args
    assert sql.count("%s") == len(params)
    assert "GROUPING SETS" in sql


# ---------------------------------------------------------------------------
# Contra Postgres
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def test_cuenta_el_dataset_y_el_universo_abierto(db):
    from db.database import connect
    from db.repositories.ml_dataset import MlDatasetRepository

    with connect() as c:
        for lic_id, procedimiento in (("COB1", "1"), ("COB2", None), ("COB3", "2")):
            c.execute(
                "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, ccaa, "
                " importe, tipo_contrato, fuente, fecha_publicacion, fecha_extraccion, "
                " procedimiento) "
                "VALUES (%s, 'Lic', 'Organo A', '72000000', 'Madrid', 100000, 'Servicios', "
                " 'placsp', '2026-01-01', CURRENT_TIMESTAMP, %s)",
                (lic_id, procedimiento),
            )
        for lic_id in ("COB1", "COB2"):
            c.execute(
                "INSERT INTO adjudicaciones (licitacion_id, nombre, importe_adjudicado, "
                " fecha_adjudicacion, n_ofertas_recibidas, fecha_extraccion) "
                "VALUES (%s, 'E1', 80000, '2026-03-01', 3, CURRENT_TIMESTAMP)",
                (lic_id,),
            )

    filas = MlDatasetRepository().cobertura_features_pendientes()
    totales = {f["poblacion"]: f for f in filas if not f["por_fuente"] and not f["por_anio"]}
    assert totales["dataset_baja"]["n"] == 2
    assert totales["dataset_baja"]["procedimiento"] == 1
    assert totales["universo_abierto"]["n"] == 1
    assert totales["universo_abierto"]["procedimiento"] == 1
