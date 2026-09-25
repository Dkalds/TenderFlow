"""El ``WHERE`` común de analytics entiende el ámbito tal y como lo manda la UI.

La barra de ámbito permite marcar varias CCAAs, estados o tecnologías y las
manda unidas por comas (``web/src/lib/filters.ts``). El builder comparaba con
igualdad, así que dos valores no casaban con nada y el filtro de tecnología se
dejaba fuera los expedientes multi-tecnología —``licitaciones.tecnologia`` es
un CSV de códigos por fila—. Aquí se fija el contrato: la forma del SQL sin
tocar base, y el recuento real contra un corpus con los dos casos.
"""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import patch

import pytest

from db.repositories.aggregates import (
    AggregateRepository,
    LicitacionesFilters,
    build_licitaciones_where,
)

# ---------------------------------------------------------------------------
# Forma del SQL — sin base de datos
# ---------------------------------------------------------------------------


def test_un_solo_valor_sigue_comparando_por_igualdad():
    """El caso de siempre no cambia de plan: ``= %s`` contra el índice btree."""
    where, params = build_licitaciones_where(LicitacionesFilters(ccaa="Madrid"))
    assert "ccaa = %s" in where
    assert params == ["Madrid"]


def test_varios_valores_se_convierten_en_un_in():
    where, params = build_licitaciones_where(LicitacionesFilters(ccaa="Madrid,Cataluña"))
    assert "ccaa IN (%s,%s)" in where
    assert params == ["Madrid", "Cataluña"]


def test_estado_multivalor_y_espacios_sobrantes():
    where, params = build_licitaciones_where(LicitacionesFilters(estado="PUB, EV ,"))
    assert "estado IN (%s,%s)" in where
    assert params == ["PUB", "EV"]


def test_tecnologia_casa_contra_el_csv_de_la_fila():
    """No es ``=``: la columna guarda ``"SAP,SALESFORCE"`` en una sola fila."""
    where, params = build_licitaciones_where(LicitacionesFilters(tecnologia="SAP"))
    assert "unnest(string_to_array(" in where
    assert "trim(_tec.code) IN (%s)" in where
    assert params == ["SAP"]


def test_tecnologia_va_por_el_indice_parcial():
    """La guarda ``IS NOT NULL`` es lo que deja usar ``idx_lic_tecnologia``.

    Con el ``EXISTS`` a solas Postgres lo evaluaba fila a fila sobre la tabla
    entera: un Seq Scan de ~870 MB por cada consulta del ámbito SAP. La guarda va
    dentro del paréntesis para que el fragmento siga siendo una sola conjunción
    allí donde se pegue.
    """
    where, _ = build_licitaciones_where(LicitacionesFilters(tecnologia="SAP"))
    assert "(tecnologia IS NOT NULL AND EXISTS (" in where

    where, _ = build_licitaciones_where(LicitacionesFilters(tecnologia="SAP,ORACLE"), alias="l")
    assert "(l.tecnologia IS NOT NULL AND EXISTS (" in where


class _CursorVacio:
    description: tuple[tuple[str], ...] = ()

    def __init__(self, fila: tuple[int, ...] | None) -> None:
        self._fila = fila

    def fetchone(self) -> tuple[int, ...] | None:
        return self._fila

    def fetchall(self) -> list[tuple[object, ...]]:
        return []


class _ConexionQueApunta:
    """Guarda cada sentencia y responde con ``fila`` a los ``fetchone``."""

    def __init__(self, fila: tuple[int, ...] | None = None) -> None:
        self.fila = fila
        self.sentencias: list[tuple[str, list[object]]] = []

    def execute(self, sql: str, params: list[object]) -> _CursorVacio:
        self.sentencias.append((sql, list(params)))
        return _CursorVacio(self.fila)

    def __enter__(self) -> _ConexionQueApunta:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _sql_de(llamada: Callable[[AggregateRepository], object], fila: tuple[int, ...] | None = None):
    conexion = _ConexionQueApunta(fila)
    with patch("db.repositories.aggregates.connect_read", return_value=conexion):
        resultado = llamada(AggregateRepository())
    return conexion.sentencias, resultado


@pytest.mark.parametrize(
    "llamada",
    [
        lambda r: r.tecnologias_entries(LicitacionesFilters()),
        lambda r: r.tecnologias_cross_organo(LicitacionesFilters(), top_organos=5, top_techs=5),
        lambda r: r.tecnologias_cross_geo(LicitacionesFilters(), top_ccaa=5, top_techs=5),
        lambda r: r.tecnologias_evolucion(LicitacionesFilters(), top_techs=5),
        lambda r: r.tecnologia_detalle_items(LicitacionesFilters(), tech_codes=["SAP"], limit=5),
        lambda r: r.tecnologia_detalle_kpis(LicitacionesFilters(), tech_codes=["SAP"]),
    ],
    ids=["entries", "cross_organo", "cross_geo", "evolucion", "detalle_items", "detalle_kpis"],
)
def test_los_explode_de_tecnologia_van_por_el_indice_parcial(llamada):
    """Sin filtro de tecnología no hay ``EXISTS`` que aporte la guarda: la pone
    cada consulta. El resultado no cambia —una fila sin tecnología no produce
    ningún ``code``—; el plan sí, de la tabla entera a las filas etiquetadas."""
    sentencias, _ = _sql_de(llamada)
    assert sentencias
    for sql, _ in sentencias:
        assert "tecnologia IS NOT NULL" in sql


def test_sin_clasificar_se_calcula_como_complemento_de_las_etiquetadas():
    """El total y las etiquetadas van en subconsultas separadas, cada una por
    su índice; las sin clasificar salen de restar, con el ámbito repetido."""
    filtros = LicitacionesFilters(ccaa="Madrid")
    sentencias, resultado = _sql_de(
        lambda r: r.tecnologias_total_y_sin_clasificar(filtros), fila=(10, 3)
    )

    assert resultado == (10, 7)
    [(sql, params)] = sentencias
    assert sql.count("SELECT COUNT(*) FROM licitaciones WHERE") == 2
    assert "tecnologia IS NOT NULL AND trim(tecnologia) != ''" in sql
    assert "FILTER" not in sql
    assert params == ["Madrid", "Madrid"]


def test_alias_califica_todas_las_columnas_del_ambito():
    where, _ = build_licitaciones_where(
        LicitacionesFilters(ccaa="Madrid,Cataluña", tecnologia="SAP", estado="PUB,EV"),
        alias="l",
    )
    assert "l.ccaa IN" in where
    assert "l.estado IN" in where
    assert "COALESCE(l.tecnologia, '')" in where


def test_valor_en_blanco_no_anade_clausula():
    where, params = build_licitaciones_where(LicitacionesFilters(ccaa=" , "))
    assert where == "1 = 1"
    assert params == []


# ---------------------------------------------------------------------------
# Recuento real contra Postgres
# ---------------------------------------------------------------------------

# (id, ccaa, tecnologia, estado)
_FILAS = (
    ("W-01", "Madrid", "SAP", "PUB"),
    ("W-02", "Madrid", "SAP,SALESFORCE", "EV"),
    ("W-03", "Cataluña", "SALESFORCE", "PUB"),
    ("W-04", "Andalucía", "ORACLE", "ADJ"),
    ("W-05", "Galicia", None, "PUB"),
)


@pytest.fixture()
def corpus(tmp_db):
    db_mod, _ = tmp_db
    with db_mod.connect() as conn:
        for id_externo, ccaa, tecnologia, estado in _FILAS:
            conn.execute(
                "INSERT INTO licitaciones (id_externo, titulo, estado, fecha_publicacion, "
                "fecha_extraccion, tecnologia, importe, ccaa) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    id_externo,
                    f"Licitación {id_externo}",
                    estado,
                    "2026-08-01",
                    "2026-08-01T00:00:00+00:00",
                    tecnologia,
                    100000.0,
                    ccaa,
                ),
            )
    return db_mod


def _total(filters: LicitacionesFilters) -> int:
    return int(AggregateRepository().overview_kpis(filters)["total"])


def test_dos_ccaas_suman_en_vez_de_vaciar(corpus):
    """Marcar dos comunidades devolvía cero; ahora devuelve la unión."""
    assert _total(LicitacionesFilters(ccaa="Madrid")) == 2
    assert _total(LicitacionesFilters(ccaa="Madrid,Cataluña")) == 3


def test_tecnologia_incluye_los_expedientes_multitecnologia(corpus):
    """W-02 es ``"SAP,SALESFORCE"``: cuenta tanto para SAP como para Salesforce."""
    assert _total(LicitacionesFilters(tecnologia="SAP")) == 2
    assert _total(LicitacionesFilters(tecnologia="SALESFORCE")) == 2
    assert _total(LicitacionesFilters(tecnologia="SAP,ORACLE")) == 3
    assert _total(LicitacionesFilters(tecnologia="ORACLE")) == 1


def test_estados_multiples(corpus):
    assert _total(LicitacionesFilters(estado="PUB")) == 3
    assert _total(LicitacionesFilters(estado="PUB,EV")) == 4


def test_los_filtros_del_ambito_se_combinan_con_and(corpus):
    assert _total(LicitacionesFilters(ccaa="Madrid,Cataluña", tecnologia="SALESFORCE")) == 2
    assert _total(LicitacionesFilters(ccaa="Cataluña", tecnologia="SAP")) == 0


def test_sin_clasificar_cuenta_nulos_y_blancos(corpus):
    """El complemento de las etiquetadas deja fuera el NULL y el CSV en blanco."""
    with corpus.connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones (id_externo, titulo, estado, fecha_publicacion, "
            "fecha_extraccion, tecnologia, importe, ccaa) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                "W-06",
                "Licitación W-06",
                "PUB",
                "2026-08-01",
                "2026-08-01T00:00:00+00:00",
                "  ",
                100000.0,
                "Galicia",
            ),
        )
    repo = AggregateRepository()
    assert repo.tecnologias_total_y_sin_clasificar(LicitacionesFilters()) == (6, 2)
    assert repo.tecnologias_total_y_sin_clasificar(LicitacionesFilters(ccaa="Galicia")) == (2, 2)
    assert repo.tecnologias_total_y_sin_clasificar(LicitacionesFilters(tecnologia="SAP")) == (2, 0)


def test_sin_tecnologia_no_cuela_por_el_explode(corpus):
    """La fila sin tecnología (NULL) no casa con ningún código."""
    assert "W-05" not in {
        row["id_externo"]
        for row in AggregateRepository().tecnologia_detalle_items(
            LicitacionesFilters(), tech_codes=["SAP", "SALESFORCE", "ORACLE"], limit=50
        )
    }
