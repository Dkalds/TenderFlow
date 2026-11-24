"""Verifica el push-down de filtros a SQL en ``services.analytics.competitors``.

``tests/test_analytics_competitors.py`` mockea la carga de datos (no ejerce
SQL real) para validar la resolución de identidad — ese fichero no cambia.
Este fichero usa Postgres real (``tmp_db``) para confirmar que los 4 filtros
que ahora también viven en el ``WHERE`` de
``AdjudicacionRepository.load_for_competitors`` (tecnologia, estado, rango de
fechas, importe_min) siguen produciendo el mismo resultado que el filtrado
100% en pandas de antes — es decir, que mover el filtro a SQL no cambió qué
filas terminan agregadas.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.analytics.competitors import CompetitorFilters, get_competitors

pytestmark = pytest.mark.usefixtures("tmp_db")


def _iso(offset_days: float) -> str:
    return (datetime.now(UTC) + timedelta(days=offset_days)).strftime("%Y-%m-%d")


def _insert(
    db,
    lic_id: str,
    empresa: str,
    *,
    tecnologia: str | None,
    estado: str,
    importe_licitacion: float,
    importe_adjudicado: float,
    fecha_adjudicacion: str,
    ccaa: str = "Madrid",
    cpv: str | None = None,
) -> None:
    from db.upsert import (
        Adjudicacion,
        Licitacion,
        replace_adjudicaciones_batch,
        upsert_licitaciones,
    )

    lic = Licitacion(
        id_externo=lic_id,
        titulo=f"Contrato {lic_id}",
        organo_contratacion="Organo X",
        importe=importe_licitacion,
        estado=estado,
        tecnologia=tecnologia,
        ccaa=ccaa,
        cpv=cpv,
        fecha_publicacion=_iso(-500),
    )
    upsert_licitaciones([lic])
    adj = Adjudicacion(
        licitacion_id=lic_id,
        nombre=empresa,
        importe_adjudicado=importe_adjudicado,
        fecha_adjudicacion=fecha_adjudicacion,
        ccaa=ccaa,
    )
    _total, _dropped, failed = replace_adjudicaciones_batch({lic_id: [adj]})
    assert failed == 0


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    _insert(
        db_mod,
        "CF-01",
        "Accenture",
        tecnologia="SAP",
        estado="ADJ",
        importe_licitacion=100000.0,
        importe_adjudicado=90000.0,
        fecha_adjudicacion=_iso(-10),
    )
    _insert(
        db_mod,
        "CF-02",
        "Accenture",
        tecnologia="SALESFORCE",
        estado="PUB",
        importe_licitacion=50000.0,
        importe_adjudicado=40000.0,
        fecha_adjudicacion=_iso(-100),
    )
    _insert(
        db_mod,
        "CF-03",
        "Indra",
        tecnologia="SAP",
        estado="ANUL",
        importe_licitacion=200000.0,
        importe_adjudicado=180000.0,
        fecha_adjudicacion=_iso(-5),
        ccaa="Cataluña",
    )
    return db_mod


def test_sin_filtros_incluye_todo(db):
    res = get_competitors(CompetitorFilters())
    assert res.total_adjudicaciones == 3
    assert {c.nombre for c in res.competitors} == {"Accenture", "Indra"}


def test_filtro_tecnologia_via_sql(db):
    res = get_competitors(CompetitorFilters(tecnologia="SAP"))
    # SAP: CF-01 (Accenture) y CF-03 (Indra).
    assert res.total_adjudicaciones == 2
    assert {c.nombre for c in res.competitors} == {"Accenture", "Indra"}


def test_filtro_estado_via_sql(db):
    res = get_competitors(CompetitorFilters(estado="ADJ"))
    assert res.total_adjudicaciones == 1
    assert res.competitors[0].nombre == "Accenture"
    assert res.competitors[0].count == 1


def test_filtro_importe_min_via_sql(db):
    res = get_competitors(CompetitorFilters(importe_min=150000))
    # Solo CF-03 (importe_licitacion=200000) supera 150000.
    assert res.total_adjudicaciones == 1
    assert res.competitors[0].nombre == "Indra"


def test_filtro_fecha_via_sql(db):
    hoy = datetime.now(UTC)
    desde = (hoy + timedelta(days=-20)).date()
    res = get_competitors(CompetitorFilters(fecha_desde=desde))
    # >= -20d: CF-01(-10d) y CF-03(-5d) -> Accenture, Indra. CF-02 (-100d) fuera.
    assert res.total_adjudicaciones == 2
    assert {c.nombre for c in res.competitors} == {"Accenture", "Indra"}


def test_filtro_fecha_hasta_via_sql(db):
    hasta = (datetime.now(UTC) + timedelta(days=-50)).date()
    res = get_competitors(CompetitorFilters(fecha_hasta=hasta))
    # <= -50d: solo CF-02 (-100d).
    assert res.total_adjudicaciones == 1
    assert res.competitors[0].nombre == "Accenture"


def test_filtro_ccaa_via_sql(db):
    res = get_competitors(CompetitorFilters(ccaa="Cataluña"))
    assert res.total_adjudicaciones == 1
    assert res.competitors[0].nombre == "Indra"


def test_filtros_combinados_via_sql(db):
    res = get_competitors(CompetitorFilters(tecnologia="SAP", estado="ADJ"))
    assert res.total_adjudicaciones == 1
    assert res.competitors[0].nombre == "Accenture"


def test_filtro_sin_resultados(db):
    res = get_competitors(CompetitorFilters(tecnologia="ORACLE"))
    assert res.total_adjudicaciones == 0
    assert res.competitors == []


def test_el_cpv_se_filtra_antes_del_tope_de_filas(tmp_db):
    """Socios pide un CPV: el ``LIMIT`` tiene que cortar sobre ese CPV.

    Con el filtro en pandas, un tope de 1 se gastaba en la adjudicación más
    reciente de otro CPV y el segmento pedido salía vacío.
    """
    from db.repositories.adjudicaciones import AdjudicacionRepository

    comun = {"tecnologia": "SAP", "estado": "ADJ", "importe_licitacion": 1000.0}
    _insert(
        tmp_db[0],
        "CPV-72",
        "Indra",
        importe_adjudicado=900.0,
        fecha_adjudicacion=_iso(-30),
        cpv="72260000",
        **comun,
    )
    _insert(
        tmp_db[0],
        "CPV-48",
        "Accenture",
        importe_adjudicado=900.0,
        fecha_adjudicacion=_iso(-1),
        cpv="48000000",
        **comun,
    )

    filas = AdjudicacionRepository().load_for_competitors(cpv_prefijo="72", limit=1)

    assert [f["licitacion_id"] for f in filas] == ["CPV-72"]


def test_presupuesto_efectivo_prefiere_la_base_sin_iva(tmp_db):
    """La baja del mapa se mide contra la misma base que ``VALID_PAIR_LOTE``
    (``BASE_COMPARABLE_SQL``, ADR-032 §B): la base sin IVA declarada antes que
    el ``importe`` histórico, que puede llevar IVA."""
    from db.repositories.adjudicaciones import AdjudicacionRepository
    from db.upsert import (
        Adjudicacion,
        Licitacion,
        replace_adjudicaciones_batch,
        upsert_licitaciones,
    )

    upsert_licitaciones(
        [
            Licitacion(
                id_externo="CF-IVA",
                titulo="Contrato con IVA",
                organo_contratacion="Organo X",
                importe=121_000.0,
                importe_base_sin_iva=100_000.0,
                estado="ADJ",
                tecnologia="SAP",
                ccaa="Madrid",
                fecha_publicacion=_iso(-500),
            )
        ]
    )
    adj = Adjudicacion(
        licitacion_id="CF-IVA",
        nombre="Accenture",
        importe_adjudicado=80_000.0,
        fecha_adjudicacion=_iso(-10),
        ccaa="Madrid",
    )
    assert replace_adjudicaciones_batch({"CF-IVA": [adj]})[2] == 0

    (fila,) = AdjudicacionRepository().load_for_competitors()
    assert fila["presupuesto_efectivo"] == pytest.approx(100_000.0)
