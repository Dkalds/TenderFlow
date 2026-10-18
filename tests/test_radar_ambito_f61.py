"""F6.1 — el Radar aplica el ámbito de mercado completo de la organización.

``services/analytics/scoring.py`` declaraba que ``importe_max``,
``tipos_organo`` y ``procedimientos_excluidos`` se resolvían y no se aplicaban,
y los CPV viajaban en ``cpv`` —igualdad exacta contra la cadena unida
``"72,48"`` —, así que un ámbito con dos familias CPV vaciaba el Radar. Aquí se
fija la traducción del ámbito al filtro y la forma del SQL que genera; el
último bloque lo comprueba contra Postgres.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from db.repositories.aggregates import LicitacionesFilters, build_licitaciones_where
from services.analytics.scoring import _ambito_como_filtros

_SETTINGS = "db.repositories.organizations.OrganizationRepository.get_settings"


def _filtros(settings: dict[str, Any]) -> LicitacionesFilters:
    with patch(_SETTINGS, return_value=settings):
        return _ambito_como_filtros(7, None)


# ── Del ámbito al filtro ─────────────────────────────────────────────────────


def test_las_tres_dimensiones_que_faltaban_llegan_al_filtro() -> None:
    filtros = _filtros(
        {
            "importe_max": 500_000,
            "procedimientos_excluidos": ["6", " 13 "],
            "tipos_organo": ["Ayuntamiento"],
        }
    )
    assert filtros.importe_max == 500_000
    assert filtros.procedimientos_excluidos == "6,13"
    assert filtros.tipos_organo == "Ayuntamiento"


def test_los_cpv_del_ambito_van_por_prefijo() -> None:
    filtros = _filtros({"cpvs": ["72", "48"]})
    assert filtros.cpv_prefijos == "72,48"
    assert filtros.cpv is None


def test_sin_ambito_no_se_acota_nada() -> None:
    filtros = _filtros({})
    assert filtros == LicitacionesFilters()


def test_el_filtro_manual_de_tecnologia_sigue_mandando() -> None:
    with patch(_SETTINGS, return_value={"importe_max": 1, "procedimientos_excluidos": ["6"]}):
        manual = _ambito_como_filtros(7, "SAP")
    assert manual == LicitacionesFilters(tecnologia="SAP")


# ── Forma del SQL ────────────────────────────────────────────────────────────


def test_importe_max_es_cota_superior_inclusiva() -> None:
    where, params = build_licitaciones_where(LicitacionesFilters(importe_max=500_000))
    assert "importe <= %s" in where
    assert params == [500_000]


def test_cpv_por_prefijo_escapa_comodines() -> None:
    where, params = build_licitaciones_where(LicitacionesFilters(cpv_prefijos="72,4_8"))
    assert "(cpv LIKE %s ESCAPE '\\' OR cpv LIKE %s ESCAPE '\\')" in where
    assert params == ["72%", "4\\_8%"]


def test_procedimientos_excluidos_normaliza_y_conserva_los_sin_procedimiento() -> None:
    where, params = build_licitaciones_where(
        LicitacionesFilters(procedimientos_excluidos="06,6,13")
    )
    assert "procedimiento IS NULL OR" in where
    assert "COALESCE(NULLIF(ltrim(trim(procedimiento), '0'), ''), '0') NOT IN (%s,%s)" in where
    assert params == ["13", "6"]


def test_tipos_organo_solo_excluye_tipos_conocidos_y_distintos() -> None:
    where, params = build_licitaciones_where(LicitacionesFilters(tipos_organo="Ayuntamiento"))
    assert "NOT EXISTS (SELECT 1 FROM organos o" in where
    assert "o.organo_id = licitaciones.organo_id" in where
    assert "o.tipo IS NOT NULL AND o.tipo NOT IN (%s)" in where
    assert params == ["Ayuntamiento"]


def test_tipos_organo_con_alias_califica_la_tabla_exterior() -> None:
    where, _ = build_licitaciones_where(LicitacionesFilters(tipos_organo="X"), alias="l")
    assert "o.organo_id = l.organo_id" in where


def test_filtros_vacios_no_anaden_clausulas() -> None:
    where, params = build_licitaciones_where(
        LicitacionesFilters(cpv_prefijos=" , ", procedimientos_excluidos="", tipos_organo=None)
    )
    assert where == "1 = 1"
    assert params == []


# ── Contra Postgres ──────────────────────────────────────────────────────────


@pytest.fixture()
def corpus(tmp_db: Any) -> Any:
    from db.database import connect

    filas = [
        # id, importe, cpv, procedimiento
        ("F61-1", 100_000, "72000000", "1"),
        ("F61-2", 900_000, "72000000", "1"),  # fuera por importe_max
        ("F61-3", 100_000, "45000000", "1"),  # fuera por CPV
        ("F61-4", 100_000, "48000000", "06"),  # fuera por procedimiento (normalizado)
        ("F61-5", 100_000, "48000000", None),  # sin procedimiento: se queda
    ]
    with connect() as c:
        for id_externo, importe, cpv, procedimiento in filas:
            c.execute(
                "INSERT INTO licitaciones (id_externo, titulo, estado, fecha_extraccion, "
                "importe, cpv, procedimiento, fecha_limite) "
                "VALUES (%s, %s, 'PUB', '2026-09-01', %s, %s, %s, '2999-01-01')",
                (id_externo, f"SAP {id_externo}", importe, cpv, procedimiento),
            )
    return tmp_db


def test_scoring_candidates_aplica_el_ambito(corpus: Any) -> None:
    from db.repositories.aggregates import AggregateRepository

    filtros = LicitacionesFilters(
        cpv_prefijos="72,48", importe_max=500_000, procedimientos_excluidos="6"
    )
    filas = AggregateRepository().scoring_candidates(hoy_iso="2026-09-19", filters=filtros)
    assert {f["id_externo"] for f in filas} == {"F61-1", "F61-5"}
