"""El listado enseña lo que entra por su CPV, no solo lo etiquetado (2026-10-31).

Sin BD. Hasta esta fecha el listado exigía ``tecnologia`` informada y dejaba
fuera lo que la ingesta guarda solo por su CPV (48, 72 y 32): 528 de las 13.079
filas de la CPV 32 publicadas desde 2025. El listado, la búsqueda de texto, el
calendario de vencimientos y la lectura de fichas de PSCP comparten ahora un
predicado, :func:`db.sql_fragments.universo_producto_sql`.
"""

from __future__ import annotations

from sqlalchemy.dialects import postgresql

from db.sql_fragments import universo_producto_sql, universo_tecnologico_sql


def test_es_el_universo_tecnologico_mas_lo_que_entra_por_cpv() -> None:
    assert universo_producto_sql("l") == (
        f"({universo_tecnologico_sql('l')} OR l.inclusion_reason = 'cpv_ti_universe')"
    )


def test_el_literal_es_el_que_escriben_los_conectores() -> None:
    from scraper.connectors.pscp import INCLUSION_CPV_TI as pscp
    from scraper.pipeline import INCLUSION_CPV_TI as placsp

    assert pscp == placsp
    assert f"l.inclusion_reason = '{placsp}'" in universo_producto_sql("l")


def test_el_listado_filtra_por_el_universo_y_no_por_la_etiqueta() -> None:
    from db.repositories.licitaciones import LicitacionRepository

    def compilado(**kw: bool) -> str:
        clausulas = LicitacionRepository._base_filters(**kw)
        return " AND ".join(
            str(c.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
            for c in clausulas
        )

    con = compilado()
    assert universo_producto_sql("licitaciones") in con
    assert "licitaciones.tecnologia != ''" not in con
    assert universo_producto_sql("licitaciones") not in compilado(solo_universo=False)


def test_el_calendario_cuenta_el_mismo_universo_que_el_listado() -> None:
    from db.repositories.aggregates import AggregateRepository

    assert universo_producto_sql("licitaciones") == AggregateRepository._VENCIMIENTOS_UNIVERSO
