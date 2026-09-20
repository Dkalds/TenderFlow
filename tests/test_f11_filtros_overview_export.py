"""F1.1 — overview y exports aceptan procedimiento, provincia e importe máximo.

``GET /licitaciones`` (y el cursor) filtraban por los tres desde F1.1, pero
``GET /analytics/overview`` y ``GET /exports/download`` no los aceptaban: con
la barra de ámbito acotada por provincia, el listado enseñaba doce expedientes
mientras los KPIs de encima contaban el corpus entero y el export bajaba lo
que no se estaba viendo. Aquí se fija que los tres viajan hasta el SQL con la
semántica del listado; el último bloque compara recuentos contra Postgres.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest

from db.repositories.aggregates import LicitacionesFilters, build_licitaciones_where
from services.analytics.overview import OverviewFilters, _to_repo_filters

# ── Overview ────────────────────────────────────────────────────────────────


def test_overview_traduce_los_tres_filtros_al_repositorio() -> None:
    repo = _to_repo_filters(
        OverviewFilters(importe_max=500_000, provincia="Madrid,Toledo", procedimiento="1")
    )
    assert repo.importe_max == 500_000
    assert repo.provincia == "Madrid,Toledo"
    assert repo.procedimiento == "1"
    # Con cualquiera de ellos el overview ya no es global: no puede servirse
    # desde el snapshot precalculado.
    assert not repo.is_empty()


def test_la_ruta_de_overview_los_pasa_al_servicio() -> None:
    import api.routes.analytics as rutas

    capturado: dict[str, Any] = {}

    def _falso(filtros: OverviewFilters) -> Any:
        capturado["filtros"] = filtros
        from services.analytics.overview import OverviewResult

        return OverviewResult()

    # `cache_response` envuelve el handler; se llama al original para no
    # depender de la caché del proceso.
    handler = getattr(rutas.overview, "__wrapped__", rutas.overview)
    with patch.object(rutas, "get_overview", _falso):
        handler(
            fecha_desde=None,
            fecha_hasta=None,
            ccaa=None,
            tecnologia=None,
            estado=None,
            q=None,
            importe_min=None,
            importe_max=250_000.0,
            provincia="Sevilla",
            procedimiento="6",
            _user={"user_id": 1},
        )
    filtros = capturado["filtros"]
    assert (filtros.importe_max, filtros.provincia, filtros.procedimiento) == (
        250_000.0,
        "Sevilla",
        "6",
    )


def test_el_where_de_analytics_entiende_los_tres() -> None:
    where, params = build_licitaciones_where(
        LicitacionesFilters(importe_max=100.0, provincia="Madrid,Toledo", procedimiento="01,1,6")
    )
    assert "importe <= %s" in where
    assert "provincia IN (%s,%s)" in where
    assert "COALESCE(NULLIF(ltrim(trim(procedimiento), '0'), ''), '0') IN (%s,%s)" in where
    assert params == [100.0, "Madrid", "Toledo", "1", "6"]


# ── Export ──────────────────────────────────────────────────────────────────


class _Conexion:
    def __init__(self) -> None:
        self.sql = ""
        self.params: list[Any] = []

    def execute(self, sql: str, params: list[Any]) -> Any:
        # El cursor no se lee: `rows_to_dicts` va doblado en el test.
        self.sql, self.params = sql, list(params)
        return object()


def test_la_consulta_del_export_aplica_los_tres(monkeypatch: pytest.MonkeyPatch) -> None:
    import db.repositories.licitaciones as repo_mod

    conexion = _Conexion()

    @contextmanager
    def _connect_read() -> Any:
        yield conexion

    monkeypatch.setattr(repo_mod, "connect_read", _connect_read)
    monkeypatch.setattr(repo_mod, "rows_to_dicts", lambda cur: [])
    repo_mod.LicitacionRepository().fetch_for_pdf(
        importe_min=10.0, importe_max=20.0, provincia="Madrid", procedimiento="06", limit=5
    )
    assert "importe >= %s" in conexion.sql
    assert "importe <= %s" in conexion.sql
    assert "provincia IN (%s)" in conexion.sql
    assert "COALESCE(NULLIF(ltrim(trim(procedimiento), '0'), ''), '0') IN (%s)" in conexion.sql
    assert conexion.params == [10.0, 20.0, "Madrid", "6", 5]


def test_el_csv_tambien_los_respeta() -> None:
    """El camino CSV/Excel consulta aparte del PDF: tienen que llegarle igual."""
    import api.routes.exports as exports_mod

    parametros: dict[str, Any] = {
        "format": "csv",
        "recurso": "licitaciones",
        "pursuit_status": None,
        "responsible_user_id": None,
        "q": None,
        "estado": None,
        "ccaa": None,
        "tecnologia": None,
        "fecha_desde": None,
        "fecha_hasta": None,
        "importe_min": None,
        "importe_max": 300_000.0,
        "provincia": "Madrid",
        "procedimiento": "1",
        "limit": 100,
        "organization_id": None,
        "por_lote": False,
    }

    async def _correr() -> None:
        respuesta = await exports_mod.download_export(**parametros, _user={"user_id": 1})
        b"".join([trozo async for trozo in respuesta.body_iterator])

    with (
        patch("services.licitaciones.fetch_for_pdf", return_value=[]) as consultar,
        patch.object(exports_mod, "log_event", lambda **_: None),
    ):
        asyncio.run(_correr())

    kwargs = consultar.call_args.kwargs
    assert kwargs["importe_max"] == 300_000.0
    assert kwargs["provincia"] == "Madrid"
    assert kwargs["procedimiento"] == "1"


# ── Paridad contra Postgres ─────────────────────────────────────────────────


@pytest.fixture()
def corpus(tmp_db: Any) -> Any:
    from db.database import connect

    filas = [
        ("P1", 100_000.0, "Madrid", "1"),
        ("P2", 900_000.0, "Madrid", "01"),
        ("P3", 100_000.0, "Toledo", "6"),
        ("P4", None, "Madrid", "1"),
    ]
    with connect() as c:
        for id_externo, importe, provincia, procedimiento in filas:
            c.execute(
                "INSERT INTO licitaciones (id_externo, titulo, importe, provincia, "
                "procedimiento, tecnologia, estado, fecha_publicacion, fecha_extraccion) "
                "VALUES (%s, %s, %s, %s, %s, 'SAP', 'PUB', '2026-09-01', '2026-09-01')",
                (id_externo, f"SAP {id_externo}", importe, provincia, procedimiento),
            )
    return tmp_db


@pytest.mark.parametrize(
    "filtros",
    [
        {"importe_max": 500_000.0},
        {"provincia": "Madrid"},
        {"procedimiento": "1"},
        {"provincia": "Madrid", "procedimiento": "1", "importe_max": 500_000.0},
    ],
)
def test_listado_overview_y_export_cuentan_lo_mismo(corpus: Any, filtros: dict[str, Any]) -> None:
    from db.repositories.aggregates import AggregateRepository
    from db.repositories.licitaciones import LicitacionRepository

    repo = LicitacionRepository()
    _items, total_listado = repo.list_paginated(limit=200, **filtros)
    total_overview = AggregateRepository().overview_kpis(LicitacionesFilters(**filtros))["total"]
    total_export = len(repo.fetch_for_pdf(limit=200, **filtros))
    assert total_listado == total_overview == total_export
