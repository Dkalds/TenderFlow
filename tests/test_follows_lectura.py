"""Lectura desde `follows` detrás de `FOLLOWS_LECTURA` (T1, ADR-031 §B fase 2).

Sin BD: se espía el SQL que cada lectura antigua manda a la conexión con el
flag apagado y encendido. Lo que necesita Postgres —que las dos lecturas
devuelvan lo mismo con la escritura doble puesta— está en
``tests/test_follows_lectura_integration.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

import pytest


class _Cursor:
    description: ClassVar[list[tuple[str]]] = [("x",)]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return []


class _Conexion:
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
        monkeypatch.setattr(settings, "FOLLOWS_LECTURA", valor, raising=False)

    return fijar


@pytest.fixture()
def sentencias(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    import db.radar_dismissals as rd
    import db.repositories.follows as fo
    import db.repositories.watchlist as wl
    import db.watchlist_empresas as we

    capturadas: list[str] = []

    def abrir() -> _Conexion:
        return _Conexion(capturadas)

    for modulo, nombre in (
        (fo, "connect_read"),
        (rd, "connect_read"),
        (wl, "connect_read"),
        (we, "connect"),
    ):
        monkeypatch.setattr(modulo, nombre, abrir)
    return capturadas


def test_el_flag_nace_apagado() -> None:
    from config.settings import Settings

    assert Settings.model_fields["FOLLOWS_LECTURA"].default is False


def _leer_todo() -> None:
    from db import radar_dismissals, watchlist_empresas
    from db.repositories.watchlist import WatchlistRepository

    WatchlistRepository().list_items("k", 7, 3)
    watchlist_empresas.list_entries("k", 7, user_id=3)
    radar_dismissals.list_detalle("k", user_id=3)
    radar_dismissals.list_ids("k", user_id=3)


def test_apagado_cada_pantalla_lee_de_su_tabla(lectura: Any, sentencias: list[str]) -> None:
    lectura(False)
    _leer_todo()
    favoritos, empresas, detalle, ids = sentencias
    assert "FROM watchlist_items wi" in favoritos
    assert "FROM watchlist_empresas w" in empresas
    assert "FROM radar_dismissals" in detalle
    assert "FROM radar_dismissals" in ids
    assert not any("follows" in s for s in sentencias)


def test_encendido_la_pertenencia_sale_de_follows(lectura: Any, sentencias: list[str]) -> None:
    lectura(True)
    _leer_todo()
    favoritos, empresas, detalle, ids = sentencias
    for sql in sentencias:
        assert "FROM follows f" in sql
        # La identidad dual de v129, sobre la fila de `follows`.
        assert "f.user_id = %s OR (f.user_key = %s" in sql

    assert "f.target_type = 'licitacion' AND f.kind = 'seguir'" in favoritos
    assert "LEFT JOIN watchlist_items wi" in favoritos
    assert "f.organization_id = %s AND (f.visibility = 'organization'" in favoritos

    assert "f.target_type = 'empresa' AND f.kind = 'seguir'" in empresas
    assert "LEFT JOIN watchlist_empresas w" in empresas
    assert "f.organization_id = %s" in empresas

    for sql in (detalle, ids):
        assert "f.kind = 'descartar'" in sql
        # La vigencia la decide `follows.hasta`, no la tabla de origen.
        assert "(f.hasta IS NULL OR f.hasta > now())" in sql
        assert "LEFT JOIN LATERAL" in sql


def test_se_lee_en_cada_llamada(lectura: Any, sentencias: list[str]) -> None:
    """Apagar el flag vuelve a la tabla de origen sin reiniciar el proceso."""
    from db import radar_dismissals

    lectura(True)
    radar_dismissals.list_ids("k", user_id=3)
    lectura(False)
    radar_dismissals.list_ids("k", user_id=3)
    assert "FROM follows f" in sentencias[0]
    assert "follows" not in sentencias[1]


def test_las_formas_son_las_de_las_gemelas() -> None:
    """Mismas claves que la lectura antigua, en el SQL de cada par.

    La ruta construye el DTO con ``Model(**fila)``: una clave de más o de menos
    sería un 500 el día que se encienda el flag, no hoy.
    """
    import inspect

    from db import radar_dismissals, watchlist_empresas
    from db.repositories import follows
    from db.repositories.watchlist import WatchlistRepository

    fav_vieja = inspect.getsource(WatchlistRepository.list_items)
    fav_nueva = inspect.getsource(follows.favoritos_desde_follows)
    for columna in (
        "id",
        "id_externo",
        "created_at",
        "organization_id",
        "visibility",
        "nota",
        "titulo",
        "importe",
        "estado",
        "fecha_publicacion",
    ):
        assert columna in fav_vieja and columna in fav_nueva, columna

    emp_vieja = inspect.getsource(watchlist_empresas.list_entries)
    emp_nueva = inspect.getsource(follows.empresas_desde_follows)
    for columna in (
        "empresa_id",
        "nombre_canonico",
        "nif_canonico",
        "email",
        "frequency",
        "created_at",
        "last_notified_at",
        "organization_id",
        "visibility",
    ):
        assert columna in emp_vieja and columna in emp_nueva, columna

    det_vieja = inspect.getsource(radar_dismissals.list_detalle)
    det_nueva = inspect.getsource(follows.descartes_desde_follows)
    for clave in ('"id_externo"', '"hasta"', '"accion"', '"score"', '"banda"'):
        assert clave in det_vieja and clave in det_nueva, clave
