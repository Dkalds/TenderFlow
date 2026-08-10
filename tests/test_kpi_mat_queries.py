"""Las consultas materializadas del export Parquet corren contra Postgres.

`_MAT_QUERIES` se ejecuta por DuckDB *si* está instalado el extra
`tenderflow[analytics]`; si no —el caso de la imagen que se despliega, porque
`requirements.txt` no trae duckdb— cae a `_export_parquet_pandas_fallback`, que
va contra Postgres. Ese camino no tenía ninguna prueba.

`mat_licitaciones_por_mes` usaba `strftime`, que existe en SQLite y en DuckDB
pero no en Postgres. El bucle envuelve cada tabla en su propio `except` y
registra el fallo como `kpi_export_parquet_pandas.skip`, así que el Parquet
simplemente no se escribía: sin excepción que subiera, sin fichero, sin nadie
mirando. Las otras cuatro consultas sí funcionaban, que es lo que hacía el
hueco fácil de no ver.
"""

from __future__ import annotations

import pandas as pd
import pytest

from db.database import connect
from scheduler.kpi_precompute import _MAT_QUERIES


def test_hay_consultas_que_verificar():
    """Si alguien vacía el dict, el parametrizado de abajo pasaría sin probar nada."""
    assert len(_MAT_QUERIES) >= 5


@pytest.mark.parametrize("nombre", sorted(_MAT_QUERIES))
def test_cada_consulta_materializada_es_sql_valido_en_postgres(tmp_db, nombre):
    """Se ejecuta de verdad: es el motor quien sabe qué funciones existen."""
    with connect() as conn:
        raw = getattr(conn, "_conn", None) or getattr(conn, "connection", None)
        assert raw is not None, "el fallback necesita la conexión DBAPI cruda"
        df = pd.read_sql(_MAT_QUERIES[nombre], raw)

    assert isinstance(df, pd.DataFrame)


def test_ninguna_consulta_usa_funciones_de_sqlite():
    """`strftime` es la que se coló; el motor de producción es Postgres."""
    for nombre, sql in _MAT_QUERIES.items():
        assert "strftime" not in sql, f"{nombre} usa strftime, que Postgres no tiene"


def test_el_mes_sale_del_texto_iso(tmp_db):
    """El agregado por mes tiene que agrupar de verdad, no devolver una columna vacía."""
    db_mod, _ = tmp_db
    with db_mod.connect() as conn:
        for i, (id_externo, fecha) in enumerate(
            [("KPI-1", "2026-03-14"), ("KPI-2", "2026-03-28"), ("KPI-3", "2026-04-02")]
        ):
            conn.execute(
                "INSERT INTO licitaciones (id_externo, titulo, fecha_publicacion, "
                "fecha_extraccion, importe, analysis_universe) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (id_externo, f"L{i}", fecha, "2026-07-30T00:00:00+00:00", 1000.0, None),
            )

    with connect() as conn:
        raw = getattr(conn, "_conn", None) or getattr(conn, "connection", None)
        df = pd.read_sql(_MAT_QUERIES["mat_licitaciones_por_mes"], raw)

    por_mes = dict(zip(df["mes"], df["n"], strict=True))
    assert por_mes == {"2026-03": 2, "2026-04": 1}
