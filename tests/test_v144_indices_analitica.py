"""v144: los índices cubrientes de la analítica de Mercado y lo que tienen que cubrir.

Dos bloques, los dos sin base de datos:

* **DDL de la revisión**: cadena, construcción concurrente sin morir por
  ``statement_timeout``, las columnas incluidas, el predicado parcial del índice
  de tecnología, el autovacuum y un downgrade que deshace lo mismo.
* **Cobertura**: las agregaciones de Mercado sin filtros no leen ninguna
  columna de ``licitaciones`` fuera del índice. Es el contrato que no se ve en
  ningún otro sitio: si una de esas consultas empieza a leer otra columna, el
  planificador deja el Index Only Scan y vuelve al Seq Scan de la tabla entera
  —~15 s en producción— sin que falle nada.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from db.repositories.aggregates import AggregateRepository, LicitacionesFilters

_MIGRACION = "db.alembic.versions.v144_lic_indices_analitica"
_ESQUEMA = Path(__file__).resolve().parents[1] / "docs" / "database-schema.md"


def _migracion() -> Any:
    import importlib

    return importlib.import_module(_MIGRACION)


def _sql_emitido(funcion: str, *, dialecto: str = "postgresql") -> list[str]:
    """``upgrade``/``downgrade`` con ``op`` sustituido: lo que importa es el SQL."""
    modulo = _migracion()
    emitido: list[str] = []
    with patch.object(modulo, "op") as op_falso:
        op_falso.get_bind.return_value.dialect.name = dialecto
        op_falso.execute.side_effect = emitido.append
        getattr(modulo, funcion)()
    return emitido


# ---------------------------------------------------------------------------
# DDL de la revisión
# ---------------------------------------------------------------------------


def test_cuelga_de_la_cabeza_anterior() -> None:
    modulo = _migracion()
    assert modulo.revision == "v144_lic_indices_analitica"
    assert modulo.down_revision == "v143_lic_busqueda_plegada_trgm"


def test_upgrade_construye_sin_bloquear_y_sin_morir_por_timeout() -> None:
    emitido = _sql_emitido("upgrade")

    assert emitido[:2] == ["SET statement_timeout = 0", "SET lock_timeout = '30s'"]
    creaciones = [s for s in emitido if s.startswith("CREATE INDEX")]
    assert len(creaciones) == 2
    assert all(s.startswith("CREATE INDEX CONCURRENTLY IF NOT EXISTS ") for s in creaciones)


def test_el_indice_de_analitica_incluye_todas_las_columnas_cubiertas() -> None:
    modulo = _migracion()
    [indice] = [s for s in _sql_emitido("upgrade") if modulo.INDICE_ANALITICA in s]

    assert "ON licitaciones (fecha_publicacion) INCLUDE (" in indice
    assert "WHERE" not in indice
    incluidas = indice.split("INCLUDE (", 1)[1].rstrip(")").split(", ")
    assert tuple(incluidas) == modulo.COLUMNAS_CUBIERTAS


def test_el_indice_de_tecnologia_es_parcial_y_no_repite_su_clave() -> None:
    """El predicado es el que implica la guarda de ``tecnologia_en_csv_sql``."""
    modulo = _migracion()
    [indice] = [s for s in _sql_emitido("upgrade") if modulo.INDICE_TECNOLOGIA in s]

    assert "ON licitaciones (tecnologia, fecha_publicacion) INCLUDE (" in indice
    assert indice.endswith("WHERE tecnologia IS NOT NULL")
    incluidas = indice.split("INCLUDE (", 1)[1].split(")", 1)[0].split(", ")
    assert "tecnologia" not in incluidas
    assert set(incluidas) == set(modulo.COLUMNAS_CUBIERTAS) - {"tecnologia"}


def test_no_toca_el_indice_de_tecnologia_existente() -> None:
    """``idx_lic_tecnologia`` difiere entre producción y la cadena de Alembic."""
    emitido = "\n".join(_sql_emitido("upgrade") + _sql_emitido("downgrade"))
    assert not re.search(r"\bidx_lic_tecnologia\b", emitido)


def test_upgrade_baja_los_umbrales_de_autovacuum() -> None:
    emitido = _sql_emitido("upgrade")
    assert emitido[-1] == (
        "ALTER TABLE licitaciones SET (autovacuum_vacuum_scale_factor = 0.02, "
        "autovacuum_vacuum_insert_scale_factor = 0.02)"
    )


def test_downgrade_deshace_lo_mismo() -> None:
    modulo = _migracion()
    emitido = _sql_emitido("downgrade")

    assert (
        "ALTER TABLE licitaciones RESET (autovacuum_vacuum_scale_factor, "
        "autovacuum_vacuum_insert_scale_factor)"
    ) in emitido
    assert f"DROP INDEX CONCURRENTLY IF EXISTS {modulo.INDICE_ANALITICA}" in emitido
    assert f"DROP INDEX CONCURRENTLY IF EXISTS {modulo.INDICE_TECNOLOGIA}" in emitido


def test_fuera_de_postgres_no_hace_nada() -> None:
    assert _sql_emitido("upgrade", dialecto="sqlite") == []
    assert _sql_emitido("downgrade", dialecto="sqlite") == []


# ---------------------------------------------------------------------------
# Cobertura: qué leen las agregaciones de Mercado sin filtros
# ---------------------------------------------------------------------------


def _columnas_de_licitaciones() -> set[str]:
    """Columnas de ``licitaciones`` según ``docs/database-schema.md``.

    Ese fichero lo genera ``scripts/gen_schema_doc.py`` desde una base migrada a
    ``head`` y CI comprueba que está al día, así que trae también las columnas
    que el modelo SQLAlchemy no declara (``organo_id``, ``primera_extraccion``).
    """
    texto = _ESQUEMA.read_text(encoding="utf-8")
    seccion = texto.split("### `licitaciones`", 1)[1].split("\n### ", 1)[0]
    return set(re.findall(r"^\| `([a-z0-9_]+)` \|", seccion, flags=re.MULTILINE))


class _Cursor:
    description: tuple[tuple[str], ...] = ()

    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[tuple[object, ...]]:
        return []


class _Conexion:
    def __init__(self) -> None:
        self.sql: list[str] = []

    def execute(self, sql: str, params: list[object] | None = None) -> _Cursor:
        self.sql.append(sql)
        return _Cursor()

    def __enter__(self) -> _Conexion:
        return self

    def __exit__(self, *_: object) -> None:
        return None


_SIN_FILTROS = LicitacionesFilters()

#: Las agregaciones que sirven las vistas de Mercado. Quedan fuera las que leen
#: filas y no agregan (``tecnologia_detalle_items``, el clustering) y las de
#: módulos SAP, que evalúan expresiones regulares sobre ``titulo``: una columna
#: de ~67 bytes de media que doblaría el índice.
_AGREGACIONES: dict[str, Callable[[AggregateRepository], object]] = {
    "organos_totales": lambda r: r.organos_totales(_SIN_FILTROS, q_folded=None),
    "organos_ranking": lambda r: r.organos_ranking(_SIN_FILTROS, q_folded=None, limit=50),
    "organos_treemap": lambda r: r.organos_treemap(_SIN_FILTROS, q_folded=None, top_organos=30),
    "trends_daily": lambda r: r.trends_daily(_SIN_FILTROS),
    "trends_heatmap": lambda r: r.trends_heatmap(_SIN_FILTROS),
    "trends_yoy": lambda r: r.trends_yoy(
        _SIN_FILTROS, hace_365d_iso="2025-09-25", hace_730d_iso="2024-09-25"
    ),
    "trends_histogram": lambda r: r.trends_histogram(_SIN_FILTROS),
    "trends_cpv_ranking": lambda r: r.trends_cpv_ranking(_SIN_FILTROS, top_n=15),
    "trends_cpv_series": lambda r: r.trends_cpv_series(_SIN_FILTROS, cpvs=["72000000"]),
    "geography_by_ccaa": lambda r: r.geography_by_ccaa(_SIN_FILTROS),
    "geography_by_provincia": lambda r: r.geography_by_provincia(_SIN_FILTROS),
    "forecast_count": lambda r: r.forecast_monthly(_SIN_FILTROS, metric="count"),
    "forecast_sum": lambda r: r.forecast_monthly(_SIN_FILTROS, metric="sum"),
    "tipos_contrato": lambda r: r.tipos_contrato_breakdown(_SIN_FILTROS),
    "tipo_estado": lambda r: r.tipo_estado_crosstab(_SIN_FILTROS),
    "cpv_top": lambda r: r.cpv_top_por_count(_SIN_FILTROS, n=15),
    "tecnologias_total": lambda r: r.tecnologias_total_y_sin_clasificar(_SIN_FILTROS),
    "tecnologias_entries": lambda r: r.tecnologias_entries(_SIN_FILTROS),
    "tecnologias_organo": lambda r: r.tecnologias_cross_organo(
        _SIN_FILTROS, top_organos=10, top_techs=8
    ),
    "tecnologias_geo": lambda r: r.tecnologias_cross_geo(_SIN_FILTROS, top_ccaa=10, top_techs=8),
    "tecnologias_evolucion": lambda r: r.tecnologias_evolucion(_SIN_FILTROS, top_techs=8),
}


def test_el_esquema_documentado_trae_las_columnas_de_licitaciones() -> None:
    """Si el parseo del esquema fallara, el test de abajo pasaría sin mirar nada."""
    columnas = _columnas_de_licitaciones()
    assert {"fecha_publicacion", "organo_id", "titulo", "importe"} <= columnas


@pytest.mark.parametrize("nombre", sorted(_AGREGACIONES))
def test_las_agregaciones_de_mercado_solo_leen_columnas_del_indice(nombre: str) -> None:
    cubiertas = {"fecha_publicacion", *_migracion().COLUMNAS_CUBIERTAS}
    columnas = _columnas_de_licitaciones()
    conexion = _Conexion()
    with patch("db.repositories.aggregates.connect_read", return_value=conexion):
        _AGREGACIONES[nombre](AggregateRepository())

    assert conexion.sql
    leidas = {
        token
        for sql in conexion.sql
        for token in re.findall(r"[a-z_][a-z0-9_]*", sql.lower())
        if token in columnas
    }
    assert leidas <= cubiertas, (
        f"{nombre} lee {sorted(leidas - cubiertas)}, que no está en idx_lic_analitica: "
        "añadirla al índice (revisión nueva) o sacarla de la consulta"
    )
