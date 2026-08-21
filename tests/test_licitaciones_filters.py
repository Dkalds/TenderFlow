"""Tests para LicitacionRepository.ids_for_filters.

Este set de ids alimenta el ``allowed_ids`` de la búsqueda semántica: el backend
restringe los hits a los filtros activos en vez de que el frontend finja filtrar
(o mande solo el primer valor). Multi-valor (CCAA/tecnología) y rango de fechas.
"""

from __future__ import annotations


def _seed(rows: list[dict]) -> None:
    from db.upsert import Licitacion, upsert_licitaciones

    upsert_licitaciones([Licitacion(**r) for r in rows])


def _repo():
    from db.repositories.licitaciones import LicitacionRepository

    return LicitacionRepository()


def test_ids_for_filters_multivalor_y_combinacion(tmp_db):
    _seed(
        [
            {"id_externo": "L1", "titulo": "a", "ccaa": "Madrid", "tecnologia": "SAP"},
            {"id_externo": "L2", "titulo": "b", "ccaa": "Cataluña", "tecnologia": "SAP"},
            {"id_externo": "L3", "titulo": "c", "ccaa": "Galicia", "tecnologia": "ORACLE"},
            {"id_externo": "L4", "titulo": "d", "ccaa": "Madrid", "tecnologia": "ORACLE"},
        ]
    )
    repo = _repo()

    # Multi-CCAA: se aplican TODOS los valores (no solo el primero).
    assert repo.ids_for_filters(ccaa=["Madrid", "Cataluña"]) == {"L1", "L2", "L4"}
    # Multi-tecnología.
    assert repo.ids_for_filters(tecnologia=["ORACLE"]) == {"L3", "L4"}
    # CCAA + tecnología se combinan con AND.
    assert repo.ids_for_filters(ccaa=["Madrid"], tecnologia=["SAP"]) == {"L1"}
    # Sin cláusulas → set vacío (sin restricción; el caller no debe invocarlo).
    assert repo.ids_for_filters() == set()


def test_ids_for_filters_rango_de_fechas(tmp_db):
    _seed(
        [
            {"id_externo": "F1", "titulo": "a", "fecha_publicacion": "2025-12-31"},
            {"id_externo": "F2", "titulo": "b", "fecha_publicacion": "2026-01-15"},
            {"id_externo": "F3", "titulo": "c", "fecha_publicacion": "2026-02-20"},
            {"id_externo": "F4", "titulo": "d", "fecha_publicacion": "2026-03-05"},
        ]
    )
    repo = _repo()

    assert repo.ids_for_filters(fecha_desde="2026-01-01", fecha_hasta="2026-02-28") == {
        "F2",
        "F3",
    }
    # Fecha malformada se ignora (no rompe ni filtra).
    assert repo.ids_for_filters(fecha_desde="31/12/2025") == set()


def test_ids_for_filters_respeta_cap(tmp_db):
    _seed([{"id_externo": f"C{i}", "titulo": "x", "ccaa": "Madrid"} for i in range(10)])
    repo = _repo()
    assert len(repo.ids_for_filters(ccaa=["Madrid"], cap=3)) == 3


# ---------------------------------------------------------------------------
# El ámbito global en el listado: multi-valor y CSV de tecnologías
#
# La barra de ámbito manda ``tecnologia=SAP,ORACLE`` y ``licitaciones.tecnologia``
# guarda un CSV por fila (``"SAP,SALESFORCE"``). Con igualdad, marcar dos
# tecnologías no casaba con nada y marcar una escondía los multi-tecnología —el
# mismo agujero que se arregló en ``db/repositories/aggregates.py`` para los
# agregados, y que aquí tiene que resolverse igual para que la tabla y los KPIs
# de la misma pantalla midan lo mismo.
# ---------------------------------------------------------------------------


def _compiled_where(**kwargs) -> str:
    """SQL del ``WHERE`` que arma ``_base_filters``, sin tocar base."""
    from sqlalchemy import and_, select

    from db.models import compile_query, licitaciones
    from db.repositories.licitaciones import LicitacionRepository

    clauses = LicitacionRepository._base_filters(only_classified=False, **kwargs)
    sql, _ = compile_query(select(licitaciones.c.id_externo).where(and_(*clauses)))
    return sql


def test_base_filters_un_valor_sigue_siendo_igualdad():
    assert "licitaciones.ccaa = %s" in _compiled_where(ccaa="Madrid")


def test_base_filters_multivalor_genera_in():
    sql = _compiled_where(ccaa="Madrid,Cataluña", estado="PUB,EV")
    assert "licitaciones.ccaa IN (%s, %s)" in sql
    assert "licitaciones.estado IN (%s, %s)" in sql


def test_base_filters_tecnologia_casa_contra_el_csv():
    sql = _compiled_where(tecnologia="SAP")
    assert "LIKE %s" in sql
    assert "replace(coalesce(licitaciones.tecnologia" in sql
    # Sin cláusula ESCAPE: el dialecto se compila sin conexión y la doblaría.
    assert "ESCAPE" not in sql


def test_listado_multivalor_y_multitecnologia(tmp_db):
    _seed(
        [
            {"id_externo": "P1", "titulo": "a", "ccaa": "Madrid", "tecnologia": "SAP"},
            {
                "id_externo": "P2",
                "titulo": "b",
                "ccaa": "Madrid",
                "tecnologia": "SAP,SALESFORCE",
            },
            {"id_externo": "P3", "titulo": "c", "ccaa": "Cataluña", "tecnologia": "SALESFORCE"},
            {"id_externo": "P4", "titulo": "d", "ccaa": "Galicia", "tecnologia": "ORACLE"},
        ]
    )
    repo = _repo()

    def ids(**kwargs) -> set[str]:
        items, _ = repo.list_paginated(**kwargs)
        return {row["id_externo"] for row in items}

    # Dos comunidades: unión, no vacío.
    assert ids(ccaa="Madrid,Cataluña") == {"P1", "P2", "P3"}
    # Una tecnología incluye el expediente que además lleva otra.
    assert ids(tecnologia="SAP") == {"P1", "P2"}
    assert ids(tecnologia="SALESFORCE") == {"P2", "P3"}
    # Dos tecnologías: unión.
    assert ids(tecnologia="SAP,ORACLE") == {"P1", "P2", "P4"}
    # Y se sigue combinando con el resto del ámbito.
    assert ids(ccaa="Cataluña", tecnologia="SAP") == set()


def test_listado_no_confunde_un_codigo_con_el_prefijo_de_otro(tmp_db):
    """``SAP`` no debe arrastrar ``SAPHANA``: el casado es por elemento del CSV."""
    _seed(
        [
            {"id_externo": "X1", "titulo": "a", "tecnologia": "SAPHANA"},
            {"id_externo": "X2", "titulo": "b", "tecnologia": "OTRA,SAPHANA"},
            {"id_externo": "X3", "titulo": "c", "tecnologia": "SAP"},
        ]
    )
    items, _ = _repo().list_paginated(tecnologia="SAP")
    assert {row["id_externo"] for row in items} == {"X3"}


def test_ids_for_filters_tambien_ve_los_multitecnologia(tmp_db):
    """La búsqueda semántica acota con el mismo universo que la tabla."""
    _seed(
        [
            {"id_externo": "S1", "titulo": "a", "tecnologia": "SAP,SALESFORCE"},
            {"id_externo": "S2", "titulo": "b", "tecnologia": "ORACLE"},
        ]
    )
    assert _repo().ids_for_filters(tecnologia=["SAP"]) == {"S1"}
