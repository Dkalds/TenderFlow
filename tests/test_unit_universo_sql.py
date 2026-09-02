"""Fragmentos SQL nuevos: universo tecnológico y origen de la fecha de fin."""

from __future__ import annotations

from db.sql_fragments import (
    ORIGENES_FECHA_FIN,
    UNIVERSOS_TECNOLOGICOS,
    fecha_fin_origen_sql,
    universo_tecnologico_sql,
)


def test_universo_incluye_los_tres_universos_filtrados_en_ingesta() -> None:
    sql = universo_tecnologico_sql("l")
    for universo in UNIVERSOS_TECNOLOGICOS:
        assert f"'{universo}'" in sql
    assert "pscp_observed" not in sql
    assert "watched_company_awards_observed" not in sql


def test_el_primer_disyunto_es_el_predicado_canonico_del_indice_v84() -> None:
    """Byte a byte: es lo que hace que el índice parcial lo sirva y lo que
    ``tests/test_scoring_universo_index.py`` exige a cualquier ``COALESCE``."""
    from db.sql_fragments import TECHNOLOGY_OBSERVED_SQL

    assert universo_tecnologico_sql("l").startswith(f"({TECHNOLOGY_OBSERVED_SQL} OR ")


def test_universo_rescata_las_filas_con_tecnologia_etiquetada() -> None:
    """Un expediente de PSCP que casó con el diccionario es tecnología aunque
    su universo sea ``pscp_observed``."""
    sql = universo_tecnologico_sql("c")
    assert "c.tecnologia IS NOT NULL AND c.tecnologia <> ''" in sql
    assert "COALESCE(c.analysis_universe, 'technology_observed')" in sql
    assert sql.startswith("(") and sql.endswith(")")


def test_origen_de_fecha_fin_cubre_las_mismas_ramas_que_la_fecha() -> None:
    sql = fecha_fin_origen_sql()
    for origen in ORIGENES_FECHA_FIN:
        assert f"'{origen}'" in sql
    # Mismo orden de prioridad que FECHA_FIN_SQL: real → inicio → adjudicación.
    assert (
        sql.index("'real'") < sql.index("'estimada_inicio'") < sql.index("'estimada_adjudicacion'")
    )
