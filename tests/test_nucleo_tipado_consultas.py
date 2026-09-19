"""Las cinco consultas calientes de T2 leen el núcleo tipado detrás del flag.

Sin BD: se captura el SQL que cada consulta manda a la conexión y se comprueba
por los dos lados de ``NUCLEO_TIPADO_LECTURA``.

- **Apagado** (el default): ni una sombra de ``v133`` en el SQL, y la forma de
  siempre en filtros, orden y proyección. Es la garantía de que este cambio no
  mueve nada hasta que alguien encienda el flag.
- **Encendido**: filtros y orden sobre ``*_ts``/``importe_num``, guardas de
  fecha como rango de ``timestamptz`` y el importe proyectado casteado con su
  nombre de siempre (``AS importe``), sin castear columnas en el ``WHERE``.

El resultado contra datos reales (``EXPLAIN`` y comparación de filas) es el
paso 6 del runbook ``docs/runbooks/nucleo-tipado-ventana.md`` y necesita
producción; aquí sólo se fija el SQL.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, ClassVar

import pytest

_SOMBRAS = ("fecha_publicacion_ts", "fecha_limite_ts", "importe_num", "duracion_valor_num")


class _Cursor:
    description: ClassVar[list[tuple[str]]] = [("x",)]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return []

    def fetchone(self) -> None:
        return None


class _Conexion:
    """Conexión espía: guarda el SQL y no devuelve filas."""

    def __init__(self, sentencias: list[str]) -> None:
        self._sentencias = sentencias

    def execute(self, sql: str, params: Any = None) -> _Cursor:
        self._sentencias.append(sql)
        return _Cursor()

    def __enter__(self) -> _Conexion:
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False


@pytest.fixture()
def lectura(monkeypatch: pytest.MonkeyPatch) -> Callable[[bool], None]:
    from config import settings

    def fijar(valor: bool) -> None:
        monkeypatch.setattr(settings, "NUCLEO_TIPADO_LECTURA", valor, raising=False)

    return fijar


@pytest.fixture()
def sentencias(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    import db.repositories.aggregates as agg
    import db.repositories.licitaciones as lic
    import db.repositories.publico as pub

    capturadas: list[str] = []
    for modulo in (lic, agg, pub):
        monkeypatch.setattr(modulo, "connect_read", lambda: _Conexion(capturadas))
    monkeypatch.setattr(lic, "fts_available", lambda: True)
    return capturadas


def _sin_sombras(sql: str) -> bool:
    return not any(s in sql for s in _SOMBRAS)


# ── Filtros comunes para ejercitar todas las ramas de fecha e importe ─────

_FILTROS: dict[str, Any] = {
    "fecha_desde": "2026-01-01",
    "fecha_hasta": "2026-06-30",
    "cierre_desde": "2026-07-01",
    "cierre_hasta": "2026-07-31",
    "importe_min": 1000.0,
    "importe_max": 500000.0,
    "dias_restantes_max": 30,
}


# ── 1. Listado (rama SA Core) ─────────────────────────────────────────────


def _listado(**extra: Any) -> None:
    from db.repositories.licitaciones import LicitacionRepository

    LicitacionRepository().list_paginated(**_FILTROS, **extra)


def test_listado_apagado_no_toca_las_sombras(lectura: Any, sentencias: list[str]) -> None:
    lectura(False)
    _listado(sort="-importe")
    assert len(sentencias) == 2  # COUNT + datos
    for sql in sentencias:
        assert _sin_sombras(sql), sql
    datos = sentencias[1]
    assert "licitaciones.fecha_publicacion >= %s" in datos
    assert "licitaciones.fecha_limite >= %s" in datos
    assert "licitaciones.importe >= %s" in datos
    assert "ORDER BY licitaciones.importe DESC" in datos
    assert "CAST(" not in datos


def test_listado_encendido_filtra_y_ordena_por_las_sombras(
    lectura: Any, sentencias: list[str]
) -> None:
    lectura(True)
    _listado()
    datos = sentencias[1]
    assert "licitaciones.fecha_publicacion_ts >= %s" in datos
    assert "licitaciones.fecha_publicacion_ts <= %s" in datos
    assert "licitaciones.fecha_limite_ts >= %s" in datos
    assert "licitaciones.fecha_limite_ts < %s" in datos
    assert "licitaciones.importe_num >= %s" in datos
    assert "licitaciones.importe_num <= %s" in datos
    assert "TIMESTAMPTZ '1900-01-01 00:00:00+00'" in datos
    assert "ORDER BY licitaciones.fecha_publicacion_ts DESC" in datos
    assert "CAST(licitaciones.importe_num AS double precision) AS importe" in datos
    # Ni un filtro sobre el texto viejo: el WHERE sólo compara sombras.
    where = datos.split("WHERE", 1)[1]
    assert not re.search(r"licitaciones\.fecha_(publicacion|limite) ", where)
    assert not re.search(r"licitaciones\.importe ", where)


def test_el_orden_se_resuelve_en_cada_llamada(lectura: Any, sentencias: list[str]) -> None:
    """Sin caché de importación: cambiar el flag cambia el orden sin reiniciar."""
    lectura(True)
    _listado(sort="importe")
    lectura(False)
    _listado(sort="importe")
    assert "ORDER BY licitaciones.importe_num ASC" in sentencias[1]
    assert "ORDER BY licitaciones.importe ASC" in sentencias[3]


# ── 1b. Listado (rama FTS) ────────────────────────────────────────────────


def test_listado_fts_sigue_el_flag(lectura: Any, sentencias: list[str]) -> None:
    lectura(False)
    _listado(q="sap")
    apagado = list(sentencias)
    sentencias.clear()
    lectura(True)
    _listado(q="sap")
    encendido = list(sentencias)

    for sql in apagado:
        assert _sin_sombras(sql), sql
    assert "l.fecha_publicacion >= %s" in apagado[1]
    assert "(l.fecha_limite >= '1900' AND l.fecha_limite < '3000')" in apagado[1]
    assert "SELECT l.id_externo, l.titulo, l.organo_contratacion, l.importe," in apagado[1]
    assert "ORDER BY l.fecha_publicacion DESC" in apagado[1]

    datos = encendido[1]
    assert "l.fecha_publicacion_ts >= %s" in datos
    assert "l.fecha_limite_ts >= %s" in datos
    assert "l.importe_num >= %s" in datos
    assert "l.fecha_limite_ts >= TIMESTAMPTZ '1900-01-01 00:00:00+00'" in datos
    assert "CAST(l.importe_num AS double precision) AS importe" in datos
    assert "ORDER BY l.fecha_publicacion_ts DESC" in datos


# ── 2. Cursor ─────────────────────────────────────────────────────────────


def _cursor() -> None:
    from db.repositories.licitaciones import LicitacionRepository

    LicitacionRepository().list_cursor(
        cursor_fecha="2026-03-01T10:00:00+00:00", cursor_id="X-1", **_FILTROS
    )


def test_cursor_apagado_es_el_de_siempre(lectura: Any, sentencias: list[str]) -> None:
    lectura(False)
    _cursor()
    (sql,) = sentencias
    assert _sin_sombras(sql)
    assert "licitaciones.fecha_publicacion < %s" in sql
    assert "licitaciones.fecha_publicacion = %s" in sql
    assert "ORDER BY licitaciones.fecha_publicacion DESC, licitaciones.id_externo DESC" in sql


def test_cursor_encendido_pagina_por_la_sombra(lectura: Any, sentencias: list[str]) -> None:
    lectura(True)
    _cursor()
    (sql,) = sentencias
    assert "licitaciones.fecha_publicacion_ts < %s" in sql
    assert "licitaciones.fecha_publicacion_ts = %s" in sql
    assert "ORDER BY licitaciones.fecha_publicacion_ts DESC, licitaciones.id_externo DESC" in sql
    assert "CAST(licitaciones.importe_num AS double precision) AS importe" in sql


# ── 3. Scoring (universo del Radar y su distribución de importes) ────────


def test_scoring_apagado_es_el_de_siempre(lectura: Any, sentencias: list[str]) -> None:
    from db.repositories.aggregates import AggregateRepository, LicitacionesFilters

    lectura(False)
    repo = AggregateRepository()
    repo.scoring_candidates(
        hoy_iso="2026-09-19",
        filters=LicitacionesFilters(fecha_desde="2026-01-01", importe_min=10.0),
    )
    repo.importe_percentiles_universo(hoy_iso="2026-09-19")
    repo.licitaciones_by_ids(["A"])
    for sql in sentencias:
        assert _sin_sombras(sql), sql
    candidatas, percentiles, por_ids = sentencias
    assert f"SELECT {AggregateRepository._SCORING_COLS} FROM" in candidatas
    assert "(fecha_limite >= '1900' AND fecha_limite < '3000') AND fecha_limite >= %s" in candidatas
    assert "fecha_publicacion >= %s" in candidatas
    assert "importe >= %s" in candidatas
    assert "ORDER BY importe)" in percentiles
    assert f"SELECT {AggregateRepository._SCORING_COLS} FROM" in por_ids


def test_scoring_encendido_lee_las_sombras(lectura: Any, sentencias: list[str]) -> None:
    from db.repositories.aggregates import AggregateRepository, LicitacionesFilters

    lectura(True)
    repo = AggregateRepository()
    repo.scoring_candidates(
        hoy_iso="2026-09-19",
        filters=LicitacionesFilters(fecha_desde="2026-01-01", importe_min=10.0),
    )
    repo.importe_percentiles_universo(hoy_iso="2026-09-19")
    candidatas, percentiles = sentencias
    assert "CAST(importe_num AS double precision) AS importe, cpv" in candidatas
    assert "fecha_limite_ts >= TIMESTAMPTZ '1900-01-01 00:00:00+00'" in candidatas
    assert "AND fecha_limite_ts >= %s" in candidatas
    assert "fecha_publicacion_ts >= %s" in candidatas
    assert "importe_num >= %s" in candidatas
    assert "ORDER BY CAST(importe_num AS double precision))" in percentiles
    assert "fecha_limite_ts >= %s" in percentiles


# ── 4. Overview ───────────────────────────────────────────────────────────


def test_overview_kpis_sigue_el_flag(lectura: Any, sentencias: list[str]) -> None:
    from db.repositories.aggregates import AggregateRepository, LicitacionesFilters

    filtros = LicitacionesFilters(fecha_desde="2026-01-01", importe_min=10.0)
    lectura(False)
    AggregateRepository().overview_kpis(filtros)
    lectura(True)
    AggregateRepository().overview_kpis(filtros)
    apagado, encendido = sentencias

    assert _sin_sombras(apagado)
    assert "COALESCE(SUM(importe), 0)" in apagado
    assert "AVG(importe)" in apagado
    assert "fecha_publicacion >= %s" in apagado

    assert "COALESCE(SUM(CAST(importe_num AS double precision)), 0)" in encendido
    assert "fecha_publicacion_ts >= %s" in encendido
    assert "importe_num >= %s" in encendido


def test_el_constructor_comun_no_cambia_para_los_demas_agregados(lectura: Any) -> None:
    """``nucleo`` es opt-in: el resto de agregados no se mueve con el flag."""
    from db.repositories.aggregates import LicitacionesFilters, build_licitaciones_where

    filtros = LicitacionesFilters(fecha_desde="2026-01-01", importe_min=10.0)
    lectura(True)
    where, _ = build_licitaciones_where(filtros, alias="l")
    assert _sin_sombras(where)
    where_nucleo, _ = build_licitaciones_where(filtros, alias="l", nucleo=True)
    assert "l.fecha_publicacion_ts >= %s" in where_nucleo
    lectura(False)
    assert build_licitaciones_where(filtros, alias="l", nucleo=True)[0] == where


# ── 5. Superficie pública ─────────────────────────────────────────────────


def test_publica_apagada_proyecta_la_columna_de_siempre(
    lectura: Any, sentencias: list[str]
) -> None:
    from db.repositories.publico import _SELECT_PUBLICO, PublicoRepository

    lectura(False)
    PublicoRepository().ficha("X")
    PublicoRepository().listar()
    for sql in sentencias:
        assert _sin_sombras(sql), sql
        assert f"SELECT {_SELECT_PUBLICO} FROM" in sql


def test_publica_encendida_proyecta_el_importe_exacto(lectura: Any, sentencias: list[str]) -> None:
    from db.repositories.publico import _BASE_WHERE, PublicoRepository

    lectura(True)
    PublicoRepository().ficha("X")
    PublicoRepository().listar()
    for sql in sentencias:
        assert "l.organo_contratacion, CAST(l.importe_num AS double precision) AS importe" in sql
        # El orden del listado y la publicabilidad no se mueven: son la
        # definición de la vista materializada.
    assert _BASE_WHERE in sentencias[0]
    assert "ORDER BY c.fecha_publicacion DESC NULLS LAST" in sentencias[1]
