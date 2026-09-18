"""Composición del SQL de ``db/repositories/mercado.py``: placeholders y dedupe.

``alcance_sql`` arma el ``WHERE`` del dossier y del listado filtro a filtro, y las
funciones que lo consumen le añaden sus propios ``%s`` (ids del grupo, búsqueda,
órgano, ``LIMIT``/``OFFSET``). El modo de fallo es el mismo que fija
``tests/test_adjudicaciones_dedupe_sql.py``: un ``%s`` de más, de menos o en otra
posición desplaza los valores siguientes, y contra una BD real la query devuelve
otra cosa sin dar error.

``tests/test_mercado_filtros_sql.py`` ya cuenta placeholders de cada filtro por
separado y de todos a la vez sobre ``_scope_sql``. Aquí se recorren las 256
combinaciones de filtros de ``alcance_sql`` comprobando además *dónde* cae cada
valor, y se captura lo que ejecutan las funciones del repositorio.

No necesitan Postgres: sustituyen ``connect_read`` por una conexión que anota el
``(sql, params)`` de cada ``execute`` sin ejecutarlo.
"""

from __future__ import annotations

import inspect
import itertools
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any, get_args
from unittest.mock import patch

import pytest

from db.repositories import mercado as repo
from db.sql_fragments import exclude_duplicados_sql

_DEDUPE_TABLE = "licitaciones_duplicados"

#: Un valor de filtro o de parámetro SQL. ``Any`` porque mezcla ids, listas de ids,
#: fechas, textos e importes, igual que ``repo.ParamsSql``.
Valor = Any
_FROM_ADJUDICACIONES = re.compile(r"\bFROM\s+adjudicaciones\b")

#: Un valor por filtro de ``alcance_sql``, distinto de todos los demás para que
#: al renderizar se vea en qué ``%s`` cayó cada uno.
_FILTROS: dict[str, Valor] = {
    "empresa_id": 7,
    "empresa_ids": [17, 19, 23],
    "fecha_desde": date(2026, 1, 1),
    "fecha_hasta": date(2026, 12, 31),
    "cpv_prefix": "7220",
    "ccaas": ["Madrid", "Cataluña"],
    "tecnologias": ["SAP", "Cloud"],
    "importe_min": 1000.0,
}

#: Lo que cada filtro tiene que dejar en el ``WHERE`` con su valor en su sitio.
_FRAGMENTO_RENDERIZADO = {
    "empresa_id": "a.empresa_id = 7",
    "empresa_ids": "a.empresa_id IN (17, 19, 23)",
    "fecha_desde": "a.fecha_adjudicacion >= '2026-01-01'",
    "fecha_hasta": "a.fecha_adjudicacion <= '2026-12-31'",
    "cpv_prefix": "l.cpv LIKE '7220%'",
    "ccaas": "l.ccaa IN ('Madrid', 'Cataluña')",
    "tecnologias": "l.tecnologia IN ('SAP', 'Cloud')",
    "importe_min": "l.importe >= 1000.0",
}

_UNIVERSOS: tuple[repo.UniversoAnalisis, ...] = (
    "technology_observed",
    "watched_company_awards_observed",
)


def _combinaciones() -> list[dict[str, Valor]]:
    """Todos los subconjuntos de ``_FILTROS``, del vacío al completo."""
    nombres = list(_FILTROS)
    return [
        {
            nombre: _FILTROS[nombre]
            for nombre, activo in zip(nombres, mascara, strict=True)
            if activo
        }
        for mascara in itertools.product((False, True), repeat=len(nombres))
    ]


def _renderizar(sql: str, params: list[Valor]) -> str:
    """Sustituye cada ``%s`` por el ``repr`` de su parámetro, en orden."""
    valores = iter(params)
    return re.sub(r"%s", lambda _m: repr(next(valores)), sql)


def _assert_placeholders_cuadran(sql: str, params: list[Valor], contexto: str) -> None:
    """Tantos ``%s`` como parámetros, y ningún ``AND`` duplicado o colgando."""
    assert sql.count("%s") == len(params), (
        f"{contexto}: {sql.count('%s')} placeholders y {len(params)} parámetros\n{sql}"
    )
    normalizado = " ".join(sql.split())
    assert " AND AND " not in normalizado, f"{contexto}: AND duplicado\n{normalizado}"
    assert not normalizado.startswith("AND "), f"{contexto}: AND inicial\n{normalizado}"
    assert not normalizado.endswith(" AND"), f"{contexto}: AND final\n{normalizado}"


def _assert_bien_compuesto(sql: str, params: list[Valor], contexto: str) -> None:
    """Lo anterior, un anti-join por ``FROM adjudicaciones`` y ningún ``WHERE`` vacío."""
    _assert_placeholders_cuadran(sql, params, contexto)
    assert len(_FROM_ADJUDICACIONES.findall(sql)) == sql.count(_DEDUPE_TABLE), (
        f"{contexto}: algún FROM adjudicaciones sin su exclusión de duplicados\n{sql}"
    )
    normalizado = " ".join(sql.split())
    assert " WHERE AND " not in normalizado, f"{contexto}: WHERE colgando\n{normalizado}"
    assert not re.search(r"WHERE\s*($|ORDER|GROUP|LIMIT|\))", normalizado), (
        f"{contexto}: WHERE sin condiciones\n{normalizado}"
    )


class _Cursor:
    def __init__(self, sql: str) -> None:
        self.sql = sql

    def fetchone(self) -> tuple[int, int]:
        return (0, 0)


def _filas(cursor: _Cursor) -> list[dict[str, Valor]]:
    """Dos UTEs para que el dossier recorra también sus dos consultas de UTE."""
    if "SELECT DISTINCT u.ute_empresa_id" in cursor.sql:
        return [{"ute_empresa_id": 101}, {"ute_empresa_id": 102}]
    return []


@contextmanager
def _capturando() -> Iterator[list[tuple[str, list[Valor]]]]:
    """Sustituye la conexión del repositorio y devuelve la lista de ``execute``."""
    ejecutadas: list[tuple[str, list[Valor]]] = []

    class _Conexion:
        def execute(self, sql: str, params: list[Valor] | None = None) -> _Cursor:
            ejecutadas.append((sql, list(params) if params is not None else []))
            return _Cursor(sql)

    @contextmanager
    def _connect_read() -> Iterator[_Conexion]:
        yield _Conexion()

    with (
        patch.object(repo, "connect_read", _connect_read),
        patch.object(repo, "rows_to_dicts", _filas),
    ):
        yield ejecutadas


def test_las_combinaciones_cubren_la_firma_de_alcance_sql() -> None:
    """Meta-test: un filtro o un universo nuevos entran en las combinaciones o fallan aquí."""
    firma = set(inspect.signature(repo.alcance_sql).parameters) - {"universo"}
    assert set(_FILTROS) == firma == set(_FRAGMENTO_RENDERIZADO)
    assert set(_UNIVERSOS) == set(repo._UNIVERSO_SQL) == set(get_args(repo.UniversoAnalisis))
    assert len(_combinaciones()) == 2 ** len(_FILTROS)


@pytest.mark.parametrize("universo", _UNIVERSOS)
def test_alcance_sql_pone_cada_valor_en_su_placeholder(universo: repo.UniversoAnalisis) -> None:
    """En las 256 combinaciones: cuentas cuadradas, dedupe sembrado y cada valor en su sitio."""
    for filtros in _combinaciones():
        where, params = repo.alcance_sql(universo=universo, **filtros)

        _assert_placeholders_cuadran(where, params, repr(filtros))
        assert where.count(_DEDUPE_TABLE) == 1
        assert exclude_duplicados_sql() in where, f"{filtros}: sin exclusión de duplicados"
        assert where.startswith(repo._UNIVERSO_SQL[universo]), f"{filtros}: otro universo"

        renderizado = _renderizar(where, params)
        esperados = set(filtros)
        if "empresa_ids" in esperados:
            # `empresa_ids` tiene prioridad: `empresa_id` no debe aparecer.
            esperados.discard("empresa_id")
            assert _FRAGMENTO_RENDERIZADO["empresa_id"] not in renderizado
        for nombre in esperados:
            assert _FRAGMENTO_RENDERIZADO[nombre] in renderizado, (
                f"{filtros}: falta {_FRAGMENTO_RENDERIZADO[nombre]!r}\n{renderizado}"
            )


def test_el_dossier_compone_bien_todas_sus_consultas() -> None:
    """Las consultas del dossier con cada combinación de filtros: ocho, o siete sin base."""
    for filtros in _combinaciones():
        sin_empresa = {k: v for k, v in filtros.items() if k not in {"empresa_id", "empresa_ids"}}
        group_ids = list(filtros.get("empresa_ids", [7]))
        alcance = repo.alcance_sql(universo="technology_observed", **filtros)
        for alcance_base in (None, alcance):
            with _capturando() as ejecutadas:
                repo.filas_perfil_empresa(
                    group_ids,
                    alcance=alcance,
                    alcance_base=alcance_base,
                    alcance_mercado=repo.alcance_sql(universo="technology_observed", **sin_empresa),
                    alcance_historia=repo.alcance_sql(
                        universo="technology_observed", empresa_ids=group_ids
                    ),
                )
            # identidades, historia, actividad, [base], posición, UTEs, su actividad y miembros.
            assert len(ejecutadas) == (7 if alcance_base is None else 8)
            for sql, params in ejecutadas:
                _assert_bien_compuesto(sql, params, f"perfil {filtros} base={alcance_base}")


@pytest.mark.parametrize("q", [None, "   ", "sap"])
@pytest.mark.parametrize("organo", [None, "xunta"])
@pytest.mark.parametrize("sort", [*sorted(repo._AWARD_SORT_SQL), "desconocido"])
def test_el_listado_compone_bien_con_busqueda_organo_y_orden(
    q: str | None, organo: str | None, sort: str
) -> None:
    """Total y página, con cada combinación de filtros del alcance."""
    for filtros in _combinaciones():
        alcance = repo.alcance_sql(universo="technology_observed", **filtros)
        with _capturando() as ejecutadas:
            repo.adjudicaciones_empresa(alcance, q=q, organo=organo, sort=sort, limit=0, offset=-1)
        assert len(ejecutadas) == 2
        for sql, params in ejecutadas:
            _assert_bien_compuesto(sql, params, f"listado {filtros} q={q!r} organo={organo!r}")
        # LIMIT y OFFSET son los dos últimos parámetros de la página, ya acotados.
        assert ejecutadas[1][1][-2:] == [1, 0]


def test_cuota_denominador_y_hhi_componen_bien() -> None:
    """Los tres agregados de segmento, con sus filtros opcionales y cada segmentación."""
    for cpv_prefix, ccaa, desde in itertools.product(
        (None, "72"), (None, "Madrid"), (None, "2026-01-01")
    ):
        filtros = {"cpv_prefix": cpv_prefix, "ccaa": ccaa, "desde": desde}
        with _capturando() as ejecutadas:
            repo.denominador_cuota(**filtros)
            repo.cuota_mercado(**filtros, limit=10)
        assert len(ejecutadas) == 3
        for sql, params in ejecutadas:
            _assert_bien_compuesto(sql, params, f"cuota {filtros}")

    for segment_by in sorted(repo._SEGMENT_COLUMNS):
        with _capturando() as ejecutadas:
            repo.concentracion_hhi(segment_by=segment_by, min_contratos=5)
        ((sql, params),) = ejecutadas
        # La subconsulta de contratos lleva su propio anti-join: son dos.
        assert sql.count(_DEDUPE_TABLE) == 2
        _assert_bien_compuesto(sql, params, f"hhi {segment_by}")
