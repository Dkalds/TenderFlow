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
