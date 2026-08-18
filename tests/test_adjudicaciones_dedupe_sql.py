"""Composición del SQL de `db/repositories/adjudicaciones.py` tras sembrar el dedupe.

El 2026-08-18 se añadió la exclusión de duplicados cross-fuente a las consultas
analíticas de este repositorio (ver `tests/test_dedup_guardrail.py`). En cuatro de
ellas la cláusula no se escribió en la query sino en `_adj_filter_conditions`, el
helper que comparten.

Sembrar una condición en un constructor de `WHERE` tiene un modo de fallo que no
se ve leyendo el diff y que ninguna comprobación textual detecta: **desalinear los
`%s` con la lista de parámetros**. Si la cláusula sembrada llevara un placeholder,
todos los valores posteriores se desplazarían una posición y la query devolvería
resultados incorrectos —no un error— contra una BD real. Estos tests fijan que no
lo lleva, y de paso que la composición del `WHERE` sigue siendo válida en los dos
caminos que antes divergían (con filtros y sin ellos).

No necesitan Postgres: capturan el SQL en la frontera, sin ejecutarlo.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from db.repositories.adjudicaciones import AdjudicacionRepository

_DEDUPE_TABLE = "licitaciones_duplicados"


def _capture(method: str, **kwargs: Any) -> tuple[str, list[Any]]:
    """Ejecuta un método del repositorio y devuelve el (sql, params) que emitió."""
    captured: dict[str, Any] = {}

    def _execute(sql: str, params: Any = None) -> MagicMock:
        captured["sql"] = sql
        captured["params"] = list(params) if params is not None else []
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        return cursor

    cursor_ctx = MagicMock()
    cursor_ctx.__enter__.return_value.execute.side_effect = _execute

    with (
        patch("db.repositories.adjudicaciones.connect_read", return_value=cursor_ctx),
        patch("db.repositories.adjudicaciones.rows_to_dicts", return_value=[]),
    ):
        getattr(AdjudicacionRepository(), method)(**kwargs)

    return captured["sql"], captured["params"]


# (método, kwargs sin filtros, kwargs con filtros)
_ANALITICAS = [
    ("load_for_competitors", {}, {"ccaa": "Madrid", "fecha_desde": "2026-01-01"}),
    ("load_licitadores", {}, {"ccaa_filter": ("Madrid", "Cataluña")}),
    ("ute_kpis", {"pattern": "UTE"}, {"pattern": "UTE", "ccaa_filter": ("Madrid",)}),
    ("ute_top_miembros", {"pattern": "UTE"}, {"pattern": "UTE", "fecha_hasta": "2026-12-31"}),
    ("ute_evolucion", {"pattern": "UTE"}, {"pattern": "UTE", "ccaa_filter": ("Madrid",)}),
    ("load_ute_rows", {"pattern": "UTE"}, {"pattern": "UTE", "fecha_desde": "2026-01-01"}),
]


@pytest.mark.parametrize(("metodo", "sin_filtros", "con_filtros"), _ANALITICAS)
def test_la_clausula_de_dedupe_esta_en_ambos_caminos(
    metodo: str, sin_filtros: dict[str, Any], con_filtros: dict[str, Any]
) -> None:
    """Con filtros y sin ellos. El camino sin filtros es el que antes no tenía WHERE."""
    for kwargs in (sin_filtros, con_filtros):
        sql, _ = _capture(metodo, **kwargs)
        assert _DEDUPE_TABLE in sql, f"{metodo}({kwargs}) perdió la exclusión de duplicados"


@pytest.mark.parametrize(("metodo", "sin_filtros", "con_filtros"), _ANALITICAS)
def test_los_placeholders_cuadran_con_los_parametros(
    metodo: str, sin_filtros: dict[str, Any], con_filtros: dict[str, Any]
) -> None:
    """El fallo silencioso: un `%s` de más desplaza todos los valores siguientes."""
    for kwargs in (sin_filtros, con_filtros):
        sql, params = _capture(metodo, **kwargs)
        assert sql.count("%s") == len(params), (
            f"{metodo}({kwargs}): {sql.count('%s')} placeholders y {len(params)} "
            f"parámetros. La condición sembrada no debe llevar placeholders.\nSQL: {sql}"
        )


@pytest.mark.parametrize(("metodo", "sin_filtros", "con_filtros"), _ANALITICAS)
def test_el_where_queda_bien_formado(
    metodo: str, sin_filtros: dict[str, Any], con_filtros: dict[str, Any]
) -> None:
    """Sin `WHERE AND`, sin `AND AND` y sin un WHERE vacío antes de ORDER/GROUP."""
    for kwargs in (sin_filtros, con_filtros):
        sql, _ = _capture(metodo, **kwargs)
        normalizado = re.sub(r"\s+", " ", sql)
        assert " WHERE AND " not in normalizado, f"{metodo}: WHERE colgando\n{normalizado}"
        assert " AND AND " not in normalizado, f"{metodo}: AND duplicado\n{normalizado}"
        assert not re.search(r"WHERE\s+(ORDER|GROUP|LIMIT|\))", normalizado), (
            f"{metodo}: WHERE sin condiciones\n{normalizado}"
        )


def test_el_dedupe_referencia_la_columna_del_lado_izquierdo_del_join() -> None:
    """`a.licitacion_id`, no `l.id_externo`.

    `load_for_competitors` une con `licitaciones` por LEFT JOIN: si la cláusula
    apuntara a la columna de la derecha, una adjudicación sin licitación daría
    `NULL NOT IN (...)` → NULL → fila descartada en silencio. Perderíamos filas
    válidas creyendo que deduplicamos.
    """
    sql, _ = _capture("load_for_competitors")
    assert "a.licitacion_id NOT IN" in sql
    assert "l.id_externo NOT IN" not in sql
