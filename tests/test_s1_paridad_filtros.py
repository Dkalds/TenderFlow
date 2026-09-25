"""El listado y los agregados filtran ``q`` y ``tecnologia`` con la misma expresión.

``db/repositories/aggregates.py::build_licitaciones_where`` (texto, KPIs y
agregados) y ``db/repositories/licitaciones.py::LicitacionRepository._base_filters``
(SQLAlchemy Core, listado y cursor) construyen el filtro de la misma pantalla
con dos implementaciones. Los dos docstrings citan este fichero como el que
fija su paridad; hasta 2026-09 el fichero no existía.

Para ``q`` y ``tecnologia`` no basta con que los dos lados «hagan lo mismo»:
la expresión de cada columna tiene que ser **la misma cadena** en los dos, y
la parte que indexaría un índice de expresión no puede llevar parámetros
ligados. ``translate(titulo, $1, $2)`` no casa con un índice sobre
``translate(titulo, 'áà…', 'aa…')`` en cuanto Postgres usa un plan genérico, y
el listado lo emitía así: SQLAlchemy convertía las dos tablas de plegado en
parámetros. Nada fallaba; el índice, cuando existiera, simplemente no se usaría.

Dos bloques:

- **Sin BD**: el SQL emitido, que es lo que decide si un índice sirve.
- **Con Postgres**: el mismo recuento por los dos caminos para los casos que
  distinguen una semántica de otra (acentos, códigos multi-tecnología, prefijo
  de otro código, espacios en el CSV, mayúsculas, ``NULL``).
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Any

import pytest
from sqlalchemy import and_, select

from db.models import compile_query, licitaciones
from db.repositories.aggregates import LicitacionesFilters, build_licitaciones_where
from db.repositories.licitaciones import LicitacionRepository
from db.sql_fragments import (
    FOLD_DST,
    FOLD_DST_SQL,
    FOLD_SRC,
    FOLD_SRC_SQL,
    _literal_constante_sql,
    fold_expr,
    tecnologia_en_csv_sql,
    tecnologia_tokens_sql,
)

#: Columnas en las que busca ``q``, en el orden en que las emiten los dos lados.
_COLUMNAS_Q = ("titulo", "descripcion", "organo_contratacion", "id_externo")

#: Una expresión plegada completa: columna y los dos argumentos de ``translate``.
#: Las tablas de plegado no contienen comas ni paréntesis, así que basta esto.
_PLEGADO_RE = re.compile(r"lower\(translate\(([\w.]+), ([^,)]+), ([^,)]+)\)\)")


def _listado(**filtros: Any) -> tuple[str, list[Any]]:
    """SQL y parámetros del ``WHERE`` del listado, sin el filtro de clasificadas."""
    clausulas = LicitacionRepository._base_filters(only_classified=False, **filtros)
    return compile_query(select(licitaciones.c.id_externo).where(and_(*clausulas)))


def _agregados(**filtros: Any) -> tuple[str, list[Any]]:
    """El ``WHERE`` de los agregados, calificado como lo califica SQLAlchemy."""
    return build_licitaciones_where(LicitacionesFilters(**filtros), alias="licitaciones")


def _plegados(sql: str) -> list[tuple[str, str, str]]:
    return [m.groups() for m in _PLEGADO_RE.finditer(sql)]


# ── q: la expresión plegada ────────────────────────────────────────────────


def test_q_pliega_las_mismas_cuatro_columnas_con_la_misma_cadena() -> None:
    """Cada columna lleva exactamente ``fold_expr`` en los dos lados."""
    sql_listado, _ = _listado(q="Murcía")
    sql_agregados, _ = _agregados(q="Murcía")

    esperado = [fold_expr(f"licitaciones.{c}") for c in _COLUMNAS_Q]
    for sql in (sql_listado, sql_agregados):
        encontradas = [m.group(0) for m in _PLEGADO_RE.finditer(sql)]
        assert encontradas == esperado, sql


def test_q_sin_parametros_ligados_en_el_translate() -> None:
    """Las tablas de plegado van como literales, nunca como ``%s``.

    Era el defecto del listado: ``func.translate(col, FOLD_SRC, FOLD_DST)`` con
    cadenas de Python compilaba a ``translate(licitaciones.titulo, %s, %s)``.
    """
    sql_listado, params_listado = _listado(q="Murcía")
    sql_agregados, params_agregados = _agregados(q="Murcía")

    for sql in (sql_listado, sql_agregados):
        plegados = _plegados(sql)
        assert len(plegados) == len(_COLUMNAS_Q)
        for _columna, origen, destino in plegados:
            assert (origen, destino) == (FOLD_SRC_SQL, FOLD_DST_SQL)
    assert "translate(licitaciones.titulo, %s" not in sql_listado
    assert FOLD_SRC not in params_listado
    assert FOLD_DST not in params_listado
    # Lo único que viaja como parámetro es el término, ya plegado, una vez por
    # columna y igual en los dos lados.
    assert params_listado == params_agregados == ["%murcia%"] * len(_COLUMNAS_Q)


def test_q_sin_alias_es_la_expresion_del_indice_propuesto() -> None:
    """Sin alias, el agregado emite el texto que congelaría la migración del índice.

    ``docs/plans/2026-09-indices-busqueda-propuestos.md`` propone un GIN trigram
    por columna sobre esta misma cadena. Si ``fold_expr`` cambia de texto, la
    migración tendrá que reescribir los índices en el mismo cambio.
    """
    where, _ = build_licitaciones_where(LicitacionesFilters(q="x"))
    assert [m.group(0) for m in _PLEGADO_RE.finditer(where)] == [
        f"lower(translate({c}, '{FOLD_SRC}', '{FOLD_DST}'))" for c in _COLUMNAS_Q
    ]


def test_fold_expr_conserva_su_texto_historico() -> None:
    """Pasar las tablas a literales centralizados no cambió ni un carácter.

    ``fold_expr`` es parte de la clave canónica, cuyo índice (``v101``) congela
    la expresión: ``tests/test_clave_canonica_index.py`` lo comprueba contra la
    revisión, y esto contra la forma que tenía antes de centralizar.
    """
    assert fold_expr("l.organo_contratacion") == (
        f"lower(translate(l.organo_contratacion, '{FOLD_SRC}', '{FOLD_DST}'))"
    )


def test_el_filtro_de_organo_del_listado_tambien_pliega_con_literales() -> None:
    """``_plegado`` lo usa también ``organo``: se arregla por el mismo sitio."""
    sql, params = _listado(organo="Ayuntamiento de Alcalá")
    assert _plegados(sql) == [("licitaciones.organo_contratacion", FOLD_SRC_SQL, FOLD_DST_SQL)]
    assert params == ["%ayuntamiento de alcala%"]


@pytest.mark.parametrize("valor", ["a'b", "a\\b", "50%"])
def test_un_literal_constante_con_caracteres_peligrosos_no_se_emite(valor: str) -> None:
    """La comilla, la barra y el ``%`` harían que el literal dijera otra cosa."""
    with pytest.raises(ValueError, match="no admitidos"):
        _literal_constante_sql(valor)


def test_las_tablas_de_plegado_son_literales_validos() -> None:
    literales = (FOLD_SRC_SQL, FOLD_DST_SQL)
    assert literales == (f"'{FOLD_SRC}'", f"'{FOLD_DST}'")
    assert len(FOLD_SRC) == len(FOLD_DST), "translate() empareja carácter a carácter"


# ── tecnologia: solapamiento sobre una sola expresión ─────────────────────


def test_tecnologia_usa_la_misma_expresion_en_los_dos_lados() -> None:
    """La expresión de la columna es idéntica; solo el lado de los valores cambia de grafía."""
    sql_listado, params_listado = _listado(tecnologia="SAP,ORACLE")
    sql_agregados, params_agregados = _agregados(tecnologia="SAP,ORACLE")

    tokens = tecnologia_tokens_sql("licitaciones.tecnologia")
    assert f"{tokens} && CAST(ARRAY[%s, %s] AS TEXT[])" in sql_listado
    assert f"{tokens} && ARRAY[%s,%s]::text[]" in sql_agregados
    assert params_listado == params_agregados == ["SAP", "ORACLE"]


def test_tecnologia_ya_no_explota_ni_compara_por_subcadena() -> None:
    """Ni ``unnest`` por fila en los agregados ni ``LIKE`` en el listado."""
    sql_listado, _ = _listado(tecnologia="SAP")
    sql_agregados, _ = _agregados(tecnologia="SAP")
    assert "unnest" not in sql_agregados
    assert "LIKE" not in sql_listado
    assert "licitaciones.tecnologia = " not in sql_listado
    assert "licitaciones.tecnologia = " not in sql_agregados


def test_la_expresion_indexable_de_tecnologia_no_lleva_parametros() -> None:
    """La parte que indexaría el GIN es texto fijo: los ``%s`` van a la derecha del ``&&``."""
    sql_listado, _ = _listado(tecnologia="SAP")
    izquierda = sql_listado.split(" && ", 1)[0]
    assert izquierda.endswith(tecnologia_tokens_sql("licitaciones.tecnologia"))
    assert "%s" not in tecnologia_tokens_sql("licitaciones.tecnologia")


def test_tecnologia_un_marcador_por_codigo_y_ninguno_sin_codigos() -> None:
    """Los llamantes pasan un parámetro por código, como antes del cambio."""
    assert tecnologia_en_csv_sql("l.tecnologia", n=3).count("%s") == 3
    with pytest.raises(ValueError):
        tecnologia_en_csv_sql("l.tecnologia", n=0)


def test_tecnologia_en_blanco_no_filtra_en_ninguno_de_los_dos_lados() -> None:
    """Un ``,`` suelto de la barra de ámbito no puede convertirse en un filtro vacío."""
    assert LicitacionRepository._base_filters(only_classified=False, tecnologia=" , ") == []
    assert _agregados(tecnologia=" , ") == ("1 = 1", [])


def test_el_export_y_la_agenda_emiten_el_mismo_fragmento(monkeypatch: pytest.MonkeyPatch) -> None:
    """Los otros consumidores del fragmento heredan la forma sin cambiar sus ``params``."""
    import db.repositories.licitaciones as repo_mod
    from db.repositories.base import ambito_agenda_sql

    capturado: dict[str, Any] = {}

    class _Conexion:
        def execute(self, sql: str, params: list[Any]) -> object:
            capturado["sql"], capturado["params"] = sql, list(params)
            return object()

    @contextmanager
    def _connect_read() -> Any:
        yield _Conexion()

    monkeypatch.setattr(repo_mod, "connect_read", _connect_read)
    monkeypatch.setattr(repo_mod, "rows_to_dicts", lambda _cur: [])
    repo_mod.LicitacionRepository().fetch_for_pdf(tecnologia="SAP,ORACLE", limit=5)
    assert f"{tecnologia_tokens_sql('tecnologia')} && ARRAY[%s,%s]::text[]" in capturado["sql"]
    assert capturado["params"] == ["SAP", "ORACLE", 5]

    clausulas, params = ambito_agenda_sql("l", tecnologias=["SAP"], ccaas=None)
    assert clausulas == [f"{tecnologia_tokens_sql('l.tecnologia')} && ARRAY[%s]::text[]"]
    assert params == ["SAP"]


# ── Con Postgres: el mismo recuento por los dos caminos ───────────────────

# (id, titulo, descripcion, organo, tecnologia). Todas llevan tecnología salvo
# la última: el listado aplica siempre «solo clasificadas» y los agregados no,
# así que una fila sin tecnología que casara con ``q`` descuadraría el recuento
# por un motivo que no es el que se mide aquí.
_FILAS = (
    ("PF-01", "Mantenimiento en Murcia", None, "Consejería", "SAP"),
    ("PF-02", "Soporte ERP", None, "Ayuntamiento de Alcalá", "SAP,SALESFORCE"),
    ("PF-03", "Migración HANA", None, "Diputación", "SAPHANA"),
    ("PF-04", "Licencias", None, "Universidad", " SAP , ORACLE"),
    ("PF-05", "Base de datos", "Proyecto en Múrcia", "Hospital", "ORACLE"),
    ("PF-06", "Minúsculas", None, "Cabildo", "sap"),
    ("PF-07", "Otra cosa sin señal", None, "Nadie", None),
)


@pytest.fixture()
def corpus(tmp_db: Any) -> Any:
    db_mod, _ = tmp_db
    with db_mod.connect() as conn:
        for id_externo, titulo, descripcion, organo, tecnologia in _FILAS:
            conn.execute(
                "INSERT INTO licitaciones (id_externo, titulo, descripcion, "
                "organo_contratacion, tecnologia, estado, fecha_publicacion, "
                "fecha_extraccion) VALUES (%s, %s, %s, %s, %s, 'PUB', '2026-09-01', "
                "'2026-09-01T00:00:00+00:00')",
                (id_externo, titulo, descripcion, organo, tecnologia),
            )
    return db_mod


@pytest.mark.parametrize(
    ("filtros", "esperado"),
    [
        # Código entero del CSV, con los multi-tecnología y los espacios fuera.
        ({"tecnologia": "SAP"}, 3),
        # `SAPHANA` no es `SAP`; `sap` en minúscula es otro código, como antes.
        ({"tecnologia": "sap"}, 1),
        ({"tecnologia": "ORACLE"}, 2),
        ({"tecnologia": "SAP,ORACLE"}, 4),
        ({"tecnologia": "SALESFORCE"}, 1),
        # `q` pliega acentos en los dos lados: título y descripción.
        ({"q": "murcia"}, 2),
        ({"q": "MÚRCIA"}, 2),
        ({"q": "alcala"}, 1),
        ({"q": "pf-03"}, 1),
        ({"q": "murcia", "tecnologia": "ORACLE"}, 1),
    ],
)
def test_listado_y_agregados_cuentan_lo_mismo(
    corpus: Any, filtros: dict[str, Any], esperado: int
) -> None:
    from db.repositories.aggregates import AggregateRepository

    total_listado = LicitacionRepository().count_cursor(**filtros)
    total_agregados = AggregateRepository().overview_kpis(LicitacionesFilters(**filtros))["total"]
    assert total_listado == total_agregados == esperado
