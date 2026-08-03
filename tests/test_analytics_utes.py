"""Tests para services/analytics/utes — analítica UTE agregada en SQL.

Caracterización de la migración pandas -> SQL (ADR-023): siembran
licitaciones + adjudicaciones reales en el schema aislado (``tmp_db``) — los
KPIs, ranking y evolución los resuelve ``AdjudicacionRepository`` y el grafo
de socios la proyección acotada de filas UTE — y afirman los mismos valores
que daba el motor pandas. Antes estos tests mockeaban el loader con una
columna ``es_ute`` que el camino real nunca producía (``socios_frecuentes``
llegaba siempre vacío en producción — reparado por la migración).
"""

from __future__ import annotations

from datetime import date

import pytest

from services.analytics.utes import UTEFilters, get_utes

pytestmark = pytest.mark.usefixtures("tmp_db")


def _seed(rows: list[dict]) -> None:
    """Siembra una licitación mínima por adjudicación (FK) + la adjudicación."""
    from db.upsert import (
        Adjudicacion,
        Licitacion,
        replace_adjudicaciones_batch,
        upsert_licitaciones,
    )

    lics = []
    grouped: dict[str, list[Adjudicacion]] = {}
    for i, r in enumerate(rows):
        lic_id = r.get("licitacion_id", f"UTE-LIC-{i}")
        lics.append(Licitacion(id_externo=lic_id, titulo=f"Contrato {lic_id}"))
        grouped.setdefault(lic_id, []).append(
            Adjudicacion(
                licitacion_id=lic_id,
                nombre=r["nombre"],
                importe_adjudicado=r.get("importe_adjudicado"),
                fecha_adjudicacion=r.get("fecha_adjudicacion"),
                ccaa=r.get("ccaa"),
            )
        )
    upsert_licitaciones(lics)
    _total, _dropped, failed = replace_adjudicaciones_batch(grouped)
    assert failed == 0


def _rows() -> list[dict]:
    return [
        {
            "nombre": "UTE CONSTRUCCIONES ALFA - OBRAS BETA",
            "importe_adjudicado": 1000.0,
            "fecha_adjudicacion": "2025-01-10",
            "ccaa": "Madrid",
        },
        {
            "nombre": "UTE CONSTRUCCIONES ALFA - OBRAS BETA",
            "importe_adjudicado": 2000.0,
            "fecha_adjudicacion": "2025-02-10",
            "ccaa": "Madrid",
        },
        {
            "nombre": "EMPRESA SOLA SL",
            "importe_adjudicado": 300.0,
            "fecha_adjudicacion": "2025-01-15",
            "ccaa": "Madrid",
        },
    ]


def test_utes_socios_frecuentes_from_real_utes():
    _seed(_rows())
    res = get_utes(UTEFilters())

    # Un par real (alfa, beta) co-licitando en 2 UTEs por importe 3000.
    assert len(res.socios_frecuentes) == 1
    par = res.socios_frecuentes[0]
    assert par.contratos == 2
    assert par.importe == 3000.0
    # KPIs: 2 adjudicaciones UTE (la individual no cuenta).
    assert res.kpis.total_ute == 2


def test_utes_no_socios_without_utes():
    _seed(
        [
            {
                "nombre": "EMPRESA SOLA SL",
                "importe_adjudicado": 100.0,
                "fecha_adjudicacion": "2025-01-10",
            }
        ]
    )
    res = get_utes(UTEFilters())
    assert res.socios_frecuentes == []
    assert res.kpis.total_ute == 0


def test_utes_kpis_y_tabla_comparativa():
    """Split UTE vs individual: conteos, importes y tickets medios."""
    _seed(_rows())
    res = get_utes(UTEFilters())

    assert res.kpis.total_ute == 2
    assert res.kpis.importe_ute == 3000.0
    assert res.kpis.ticket_medio_ute == 1500.0
    assert res.kpis.ticket_medio_individual == 300.0
    # El nombre completo de la UTE cuenta como una empresa distinta.
    assert res.kpis.empresas_distintas == 1

    assert res.tabla_comparativa.ute.count == 2
    assert res.tabla_comparativa.ute.importe_total == 3000.0
    assert res.tabla_comparativa.individual.count == 1
    assert res.tabla_comparativa.individual.importe_total == 300.0


def test_utes_top_miembros_y_evolucion():
    _seed(_rows())
    res = get_utes(UTEFilters())

    assert len(res.top_miembros) == 1
    assert res.top_miembros[0].nombre == "UTE CONSTRUCCIONES ALFA - OBRAS BETA"
    assert res.top_miembros[0].count == 2
    assert res.top_miembros[0].importe == 3000.0

    # Evolución mensual: enero y febrero de 2025, solo filas UTE.
    periodos = {e.period: e for e in res.evolucion}
    assert set(periodos) == {"2025-01", "2025-02"}
    assert periodos["2025-01"].contratos == 1
    assert periodos["2025-01"].importe == 1000.0


def test_utes_filtro_fechas_en_sql():
    """El rango de fechas recorta el dataset ANTES de agregar (WHERE SQL)."""
    _seed(_rows())
    res = get_utes(UTEFilters(fecha_desde=date(2025, 2, 1)))

    # Solo la UTE de febrero sobrevive; la individual (enero) también cae.
    assert res.kpis.total_ute == 1
    assert res.kpis.importe_ute == 2000.0
    assert res.tabla_comparativa.individual.count == 0
    assert [e.period for e in res.evolucion] == ["2025-02"]


def test_utes_filtro_ccaa_en_sql():
    rows = _rows()
    rows[1]["ccaa"] = "Cataluña"
    _seed(rows)
    res = get_utes(UTEFilters(ccaa="Madrid"))

    assert res.kpis.total_ute == 1
    assert res.kpis.importe_ute == 1000.0


def test_utes_union_temporal_tambien_matchea():
    """El patrón cubre «UNION TEMPORAL» (con y sin tilde), no solo «UTE»."""
    _seed(
        [
            {
                "nombre": "UNIÓN TEMPORAL DE EMPRESAS GAMMA Y DELTA",
                "importe_adjudicado": 500.0,
                "fecha_adjudicacion": "2025-03-01",
            }
        ]
    )
    res = get_utes(UTEFilters())
    assert res.kpis.total_ute == 1
