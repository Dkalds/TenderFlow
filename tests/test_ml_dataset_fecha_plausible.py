"""Las adjudicaciones con fecha imposible no anclan el dataset de baja (C4.4).

Desde C4.4 el conector de PSCP descarta en origen el ``1899-12-30`` —el cero de
la epoch de Excel, o sea una celda vacía—, pero las 47 filas ya escritas
(medidas contra producción el 2026-09-03) seguían en ``adjudicaciones``. Ganaban
el ``LEAST(fecha_publicacion, fecha_adjudicacion)`` que calcula
``fecha_anchor`` y entraban en el train de todos los folds.

La decisión: el SQL del dataset las trata como adjudicación sin fecha —lo que
son— con el umbral de plausibilidad de ``shared.dates``, **no** subiendo el
``_ANIO_MINIMO`` del parser de ``services/ml/features.py``, que es un hecho del
formato y no de los datos.

Dos bloques: los que fijan el SQL y sus parámetros sin BD, y los que lo
comprueban contra Postgres.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from db.repositories import ml_dataset
from db.repositories.ml_dataset import MlDatasetRepository

# ---------------------------------------------------------------------------
# Sin BD: el SQL y sus parámetros
# ---------------------------------------------------------------------------


def test_el_corte_es_el_umbral_de_plausibilidad_de_shared_dates():
    from shared.dates import ANIO_MINIMO_PLAUSIBLE

    assert f"{ANIO_MINIMO_PLAUSIBLE:04d}-01-01" == ml_dataset._FECHA_ADJ_MINIMA
    assert ml_dataset._FECHA_ADJ_MINIMA > "1899-12-30"


def test_el_anio_minimo_del_parser_no_cambia_de_significado():
    """``_ANIO_MINIMO`` sigue siendo el de la asimetría de ``%Y``, no un filtro de datos."""
    from services.ml.features import _ANIO_MINIMO

    assert _ANIO_MINIMO == 1000


@pytest.mark.parametrize("builder", [ml_dataset._sql_agregado, ml_dataset._sql_por_lote])
def test_sin_corte_temporal_el_filtro_de_plausibilidad_va_en_las_dos_subconsultas(builder):
    sql, params = builder(None)
    assert params == [ml_dataset._FECHA_ADJ_MINIMA, ml_dataset._FECHA_ADJ_MINIMA]
    assert sql.count("fecha_adjudicacion >= %s") == 2
    assert sql.count("%s") == len(params)


@pytest.mark.parametrize("builder", [ml_dataset._sql_agregado, ml_dataset._sql_por_lote])
def test_con_corte_temporal_los_parametros_siguen_el_orden_del_sql(builder):
    sql, params = builder("2026-01-01")
    minimo = ml_dataset._FECHA_ADJ_MINIMA
    assert params == [minimo, "2026-01-01", minimo, "2026-01-01"]
    assert sql.count("%s") == len(params)
    # Cada `>=` va inmediatamente antes de su `<=`: el orden de los %s es el de params.
    assert sql.index("a.fecha_adjudicacion >= %s") < sql.index("a.fecha_adjudicacion <= %s")


def _capturar(metodo: Any) -> tuple[str, list[Any]]:
    conexion = MagicMock()
    conexion.execute.return_value = MagicMock(description=[], fetchall=list)
    contexto = MagicMock()
    contexto.__enter__.return_value = conexion
    with (
        patch.object(ml_dataset, "connect_read", return_value=contexto),
        patch.object(ml_dataset, "rows_to_dicts", return_value=[]),
    ):
        metodo()
    sql, params = conexion.execute.call_args.args
    return str(sql), list(params)


def test_adjudicaciones_por_empresa_tampoco_alimenta_el_hhi_con_la_epoch_de_excel():
    sql, params = _capturar(MlDatasetRepository().adjudicaciones_por_empresa)
    assert params == [ml_dataset._FECHA_ADJ_MINIMA]
    assert "a.fecha_adjudicacion >= %s" in sql


def test_pares_baja_agregada_pasa_el_corte_a_la_query():
    sql, params = _capturar(lambda: MlDatasetRepository().pares_baja_agregada("2026-06-30"))
    assert ml_dataset._FECHA_ADJ_MINIMA in params
    assert sql.count("%s") == len(params)


# ---------------------------------------------------------------------------
# Contra Postgres
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def _seed(c, lic_id: str, fecha_adj: str, *, importe: float = 100_000.0) -> None:
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, ccaa, "
        " importe, tipo_contrato, fuente, fecha_publicacion, fecha_extraccion) "
        "VALUES (%s, 'Lic', 'Organo A', '72000000', 'Madrid', %s, 'Servicios', "
        " 'pscp', '2025-06-01', CURRENT_TIMESTAMP)",
        (lic_id, importe),
    )
    c.execute(
        "INSERT INTO adjudicaciones (licitacion_id, nombre, importe_adjudicado, "
        " fecha_adjudicacion, n_ofertas_recibidas, fecha_extraccion) "
        "VALUES (%s, 'E1', %s, %s, 3, CURRENT_TIMESTAMP)",
        (lic_id, importe * 0.8, fecha_adj),
    )


def test_la_epoch_de_excel_no_ancla_ninguna_fila(db):
    with db.connect() as c:
        _seed(c, "OK1", "2025-09-01")
        _seed(c, "EXCEL1", "1899-12-30")

    agregado = MlDatasetRepository().pares_baja_agregada()
    por_lote = MlDatasetRepository().pares_baja_por_lote()
    empresas = MlDatasetRepository().adjudicaciones_por_empresa()

    assert [f["id_externo"] for f in agregado] == ["OK1"]
    assert [f["id_externo"] for f in por_lote] == ["OK1"]
    assert [f["licitacion_id"] for f in empresas] == ["OK1"]
    assert all(str(f["fecha_anchor"]) >= ml_dataset._FECHA_ADJ_MINIMA for f in agregado)
