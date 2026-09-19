"""El listado por cursor ordena como el de offset (RFC 2026-09-06, paso del front).

Sin BD. El de offset (`GET /licitaciones`) se retira; su sucesor tiene que
servir lo que /detalle le pedía —ordenar por importe o por título y decir «de
N»— o el frontend no puede migrar sin perder funciones. Aquí se fija el SQL del
keyset y el cursor; la paginación completa contra Postgres está en
``tests/test_cursor_ordenado_integration.py``.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from fastapi import HTTPException


class _Cursor:
    description: ClassVar[list[tuple[str]]] = [("x",)]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return []

    def fetchone(self) -> tuple[int]:
        return (7,)


class _Conexion:
    def __init__(self, sentencias: list[tuple[str, list[Any]]]) -> None:
        self._sentencias = sentencias

    def execute(self, sql: str, params: Any = None) -> _Cursor:
        self._sentencias.append((sql, list(params or [])))
        return _Cursor()

    def __enter__(self) -> _Conexion:
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False


@pytest.fixture()
def sentencias(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, list[Any]]]:
    import db.repositories.licitaciones as lic

    capturadas: list[tuple[str, list[Any]]] = []
    monkeypatch.setattr(lic, "connect_read", lambda: _Conexion(capturadas))
    return capturadas


def _repo() -> Any:
    from db.repositories.licitaciones import LicitacionRepository

    return LicitacionRepository()


# ── Semántica de los seis órdenes ────────────────────────────────────────


@pytest.mark.parametrize(
    ("sort", "columna", "descendente"),
    [
        ("fecha_publicacion", "fecha_publicacion", True),
        ("-fecha_publicacion", "fecha_publicacion", False),
        ("importe", "importe", False),
        ("-importe", "importe", True),
        ("titulo", "titulo", False),
        ("-titulo", "titulo", True),
    ],
)
def test_los_seis_ordenes_significan_lo_mismo_que_en_offset(
    sort: str, columna: str, descendente: bool
) -> None:
    """Mismo sentido que ``_SORT_MAP``: el front manda el mismo valor a los dos."""
    from db.repositories.licitaciones import _SORT_MAP, _orden_cursor

    col, desc = _orden_cursor(sort)
    assert col.key == columna
    assert desc is descendente
    compilado = str(_SORT_MAP[sort].compile())
    assert compilado.endswith("DESC" if descendente else "ASC")


def test_un_orden_desconocido_no_llega_al_sql() -> None:
    from db.repositories.licitaciones import _orden_cursor

    with pytest.raises(ValueError):
        _orden_cursor("ml_proba; DROP TABLE licitaciones")


# ── SQL del keyset ────────────────────────────────────────────────────────


def test_sin_orden_el_cursor_es_el_de_siempre(sentencias: list[Any]) -> None:
    _repo().list_cursor(cursor_fecha="2026-03-01", cursor_id="X", limit=10)
    ((sql, _),) = sentencias
    assert "ORDER BY licitaciones.fecha_publicacion DESC, licitaciones.id_externo DESC" in sql
    assert "NULLS LAST" not in sql


def test_importe_descendente_con_cursor_con_valor(sentencias: list[Any]) -> None:
    _repo().list_cursor(sort="-importe", cursor_orden=(1000.0, "X-9"), limit=10)
    ((sql, params),) = sentencias
    assert (
        "licitaciones.importe < %s OR licitaciones.importe = %s "
        "AND licitaciones.id_externo < %s OR licitaciones.importe IS NULL"
    ) in sql
    assert "ORDER BY licitaciones.importe DESC NULLS LAST, licitaciones.id_externo DESC" in sql
    assert params[-4:] == [1000.0, 1000.0, "X-9", 11]


def test_en_la_cola_de_nulos_solo_avanza_el_id(sentencias: list[Any]) -> None:
    _repo().list_cursor(sort="importe", cursor_orden=(None, "X-9"), limit=10)
    ((sql, _),) = sentencias
    assert "licitaciones.importe IS NULL AND licitaciones.id_externo > %s" in sql
    assert "ORDER BY licitaciones.importe ASC NULLS LAST, licitaciones.id_externo ASC" in sql


def test_titulo_ascendente_primera_pagina(sentencias: list[Any]) -> None:
    _repo().list_cursor(sort="titulo", limit=25, ccaa="Madrid")
    ((sql, params),) = sentencias
    assert "ORDER BY licitaciones.titulo ASC NULLS LAST, licitaciones.id_externo ASC" in sql
    assert "Madrid" in params
    assert params[-1] == 26  # una fila de más para saber si hay siguiente


def test_el_total_cuenta_el_mismo_universo(sentencias: list[Any]) -> None:
    total = _repo().count_cursor(ccaa="Madrid", importe_min=10.0)
    ((sql, params),) = sentencias
    assert total == 7
    assert sql.startswith("SELECT count(*)")
    assert "licitaciones.tecnologia IS NOT NULL" in sql  # el mismo `only_classified`
    assert "Madrid" in params and 10.0 in params


# ── Cursor opaco ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("valor", [123456.78, None, "Suministro de licencias", 0.0])
def test_el_cursor_ordenado_va_y_vuelve(valor: Any) -> None:
    from api.routes.licitaciones._base import _decode_cursor_orden, _encode_cursor_orden

    token = _encode_cursor_orden("-importe", valor, "PA-S 2026/000058")
    assert _decode_cursor_orden(token, "-importe") == (valor, "PA-S 2026/000058")


def test_un_cursor_de_otro_orden_es_400() -> None:
    from api.routes.licitaciones._base import _decode_cursor_orden, _encode_cursor_orden

    token = _encode_cursor_orden("importe", 10.0, "X")
    with pytest.raises(HTTPException) as exc:
        _decode_cursor_orden(token, "titulo")
    assert exc.value.status_code == 400


def test_un_cursor_de_fecha_no_vale_para_otro_orden() -> None:
    from api.routes.licitaciones._base import _decode_cursor_orden, _encode_cursor

    with pytest.raises(HTTPException) as exc:
        _decode_cursor_orden(_encode_cursor("2026-01-01", "X"), "importe")
    assert exc.value.status_code == 400


def test_la_respuesta_conserva_las_claves_de_la_base() -> None:
    """``total`` se añade en una subclase: la base sigue con sus cuatro claves."""
    from shared.dto import CursorPaginatedResponse, CursorPaginatedResponseWithTotal

    base = set(CursorPaginatedResponse[int].model_fields)
    assert set(CursorPaginatedResponseWithTotal[int].model_fields) == base | {"total"}
    assert CursorPaginatedResponseWithTotal[int](items=[], limit=1).total is None
