"""Lecturas nuevas del snapshot del overview: indicadores con filtros y variantes.

Dos cosas que ``db/repositories/kpi_snapshots.py`` hace desde 2026-09 sin tocar
el esquema de ``kpi_snapshots``:

- ``read_adj_indicadores_snapshot`` lee los indicadores de adjudicaciones de la
  fila ``global`` para cualquier filtro —esos indicadores nunca dependieron del
  filtro—, con la misma regla de frescura que el resto del snapshot.
- Las variantes por tecnología (``dimension = 'tecnologia:<código>'``): cómo
  se eligen, cómo se calculan sin poner en riesgo el snapshot global, y cuándo
  se sirven.

Sin Postgres: la tabla la hace una lista en memoria que reproduce la lectura
real (``DISTINCT ON (metrica)`` por ``dimension``, la más reciente gana). La
ida y vuelta real está en ``tests/test_overview_snapshot_paridad.py``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import db.repositories.kpi_snapshots as ks
from db.repositories.aggregates import LicitacionesFilters

_AHORA = datetime.now(UTC).isoformat()
_VIEJO = "2020-01-01T00:00:00+00:00"

_ADJ = {
    "hhi": 410,
    "pct_oferta_unica": 93.1,
    "lead_time_medio": None,
    "pct_pyme": 0.7,
    "adj_total": 170000,
    "adj_con_n_ofertas": 5780,
}
_KPIS_SAP = {"total": 12, "importe_total": 3000.0, "importe_medio": 250.0, "organos": 4}


def _fila(metrica: str, dimension: str, texto: Any, computed_at: str = _AHORA) -> tuple[Any, ...]:
    valor_text = texto if isinstance(texto, str) or texto is None else json.dumps(texto)
    return (metrica, dimension, None, valor_text, computed_at)


class _TablaFalsa:
    """``kpi_snapshots`` en memoria, con la lectura de ``_read_metricas``."""

    def __init__(self, filas: list[tuple[Any, ...]]) -> None:
        self.filas = filas
        self.dimensiones_leidas: list[str] = []
        self._resultado: list[tuple[Any, ...]] = []

    @contextmanager
    def connect_read(self) -> Iterator[_TablaFalsa]:
        yield self

    def execute(self, _sql: str, params: tuple[str, list[str]]) -> _TablaFalsa:
        dimension, metricas = params
        self.dimensiones_leidas.append(dimension)
        elegidas: dict[str, tuple[Any, ...]] = {}
        for metrica, dim, valor, texto, computed_at in sorted(
            self.filas, key=lambda f: str(f[4]), reverse=True
        ):
            if dim == dimension and metrica in metricas and metrica not in elegidas:
                elegidas[metrica] = (metrica, valor, texto, computed_at)
        self._resultado = [elegidas[m] for m in sorted(elegidas)]
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._resultado


@pytest.fixture()
def tabla(monkeypatch: pytest.MonkeyPatch) -> _TablaFalsa:
    falsa = _TablaFalsa([])
    monkeypatch.setattr(ks, "connect_read", falsa.connect_read)
    return falsa


# ── Indicadores de adjudicaciones con cualquier filtro ─────────────────────


def test_indicadores_frescos_se_leen_con_sus_valores_como_float(tabla: _TablaFalsa) -> None:
    tabla.filas = [_fila(ks.OV_ADJ_INDICADORES, "global", _ADJ)]

    adj = ks.read_adj_indicadores_snapshot()

    assert adj is not None
    assert adj["hhi"] == 410.0
    assert isinstance(adj["hhi"], float)
    assert adj["lead_time_medio"] is None
    assert adj["adj_total"] == 170000.0
    assert tabla.dimensiones_leidas == ["global"]


def test_indicadores_caducados_no_se_sirven(tabla: _TablaFalsa) -> None:
    """Misma frescura que el snapshot completo: pasado el umbral, en vivo."""
    tabla.filas = [_fila(ks.OV_ADJ_INDICADORES, "global", _ADJ, computed_at=_VIEJO)]

    assert ks.read_adj_indicadores_snapshot() is None
    assert ks.read_adj_indicadores_snapshot(max_age_seconds=10**10) is not None


@pytest.mark.parametrize(
    "texto",
    [None, "{no es json", json.dumps({"hhi": 1.0}), json.dumps([1, 2])],
    ids=["sin_fila_de_texto", "json_roto", "faltan_claves", "no_es_objeto"],
)
def test_indicadores_ilegibles_degradan_a_en_vivo(tabla: _TablaFalsa, texto: Any) -> None:
    tabla.filas = [_fila(ks.OV_ADJ_INDICADORES, "global", texto)]
    assert ks.read_adj_indicadores_snapshot() is None


def test_sin_fila_de_indicadores_no_hay_snapshot(tabla: _TablaFalsa) -> None:
    assert ks.read_adj_indicadores_snapshot() is None


def test_un_fallo_de_conexion_no_se_propaga(monkeypatch: pytest.MonkeyPatch) -> None:
    """Leer el snapshot es una optimización: nunca puede tumbar el overview."""

    @contextmanager
    def _roto() -> Iterator[Any]:
        raise RuntimeError("pool agotado")
        yield  # pragma: no cover

    monkeypatch.setattr(ks, "connect_read", _roto)
    assert ks.read_adj_indicadores_snapshot() is None


def test_un_valor_no_numerico_tampoco_se_propaga(tabla: _TablaFalsa) -> None:
    tabla.filas = [_fila(ks.OV_ADJ_INDICADORES, "global", {**_ADJ, "hhi": "mucho"})]
    assert ks.read_adj_indicadores_snapshot() is None


# ── Qué filtro tiene variante ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("filtros", "esperado"),
    [
        (LicitacionesFilters(tecnologia="SAP"), "SAP"),
        # Mismo SQL que "SAP" tras `csv_values`, así que misma fila.
        (LicitacionesFilters(tecnologia=" SAP "), "SAP"),
        (LicitacionesFilters(tecnologia="SAP,"), "SAP"),
        (LicitacionesFilters(tecnologia="SAP,ORACLE"), None),
        (LicitacionesFilters(tecnologia="SAP", ccaa="Madrid"), None),
        (LicitacionesFilters(tecnologia="SAP", solo_abiertas=True), None),
        (LicitacionesFilters(tecnologia=" , "), None),
        (LicitacionesFilters(ccaa="Madrid"), None),
        (LicitacionesFilters(), None),
    ],
)
def test_solo_una_tecnologia_y_nada_mas_tiene_variante(
    filtros: LicitacionesFilters, esperado: str | None
) -> None:
    assert ks.tecnologia_de_variante(filtros) == esperado


# ── Lectura de la variante ────────────────────────────────────────────────


def _filas_con_variante(computed_at: str = _AHORA) -> list[tuple[Any, ...]]:
    dimension = ks.dimension_tecnologia("SAP")
    return [
        _fila(ks.OV_KPIS, dimension, _KPIS_SAP, computed_at),
        _fila(ks.OV_TASA_ANULACION, dimension, {"anul": 2, "total": 8}, computed_at),
        _fila(ks.OV_ADJ_INDICADORES, "global", _ADJ, computed_at),
        # Globales que la variante no debe mezclar con las suyas.
        _fila(ks.OV_KPIS, "global", {**_KPIS_SAP, "total": 999}, computed_at),
        _fila(ks.OV_TASA_ANULACION, "global", {"anul": 50, "total": 100}, computed_at),
    ]


def test_filtro_de_una_tecnologia_con_variante_la_sirve(tabla: _TablaFalsa) -> None:
    tabla.filas = _filas_con_variante()

    snap = ks.read_overview_snapshot_for(LicitacionesFilters(tecnologia="SAP"))

    assert snap is not None
    assert snap.dimension == "tecnologia:SAP"
    assert snap.kpis == _KPIS_SAP
    assert snap.tasa_anulacion == (2, 8)
    # Los indicadores de adjudicaciones son los globales: no dependen del filtro.
    assert snap.adj_indicadores is not None
    assert snap.adj_indicadores["hhi"] == 410.0
    # P75 y activas solo describen la tabla entera: en una variante no se sirven,
    # que es lo que mantiene igual `/analytics/resumen/hoy` con este filtro.
    assert snap.importe_p75 is None
    assert snap.total_activas is None
    assert tabla.dimensiones_leidas == ["tecnologia:SAP", "global"]


def test_tecnologia_sin_variante_no_tiene_snapshot(tabla: _TablaFalsa) -> None:
    tabla.filas = _filas_con_variante()

    assert ks.read_overview_snapshot_for(LicitacionesFilters(tecnologia="ORACLE")) is None
    assert tabla.dimensiones_leidas == ["tecnologia:ORACLE"]


def test_variante_caducada_no_se_sirve(tabla: _TablaFalsa) -> None:
    tabla.filas = _filas_con_variante(computed_at=_VIEJO)
    assert ks.read_overview_snapshot_for(LicitacionesFilters(tecnologia="SAP")) is None


def test_variante_incompleta_no_se_sirve(tabla: _TablaFalsa) -> None:
    """Sin una de sus dos métricas, la variante entera cae al cálculo en vivo."""
    tabla.filas = [
        f for f in _filas_con_variante() if f[:2] != (ks.OV_TASA_ANULACION, "tecnologia:SAP")
    ]
    assert ks.read_overview_snapshot_for(LicitacionesFilters(tecnologia="SAP")) is None


def test_otros_filtros_no_consultan_la_tabla(tabla: _TablaFalsa) -> None:
    """Sin variante posible, ni siquiera se lee: ``None`` directo."""
    tabla.filas = _filas_con_variante()

    assert ks.read_overview_snapshot_for(LicitacionesFilters(ccaa="Madrid")) is None
    assert ks.read_overview_snapshot_for(LicitacionesFilters(tecnologia="SAP", q="x")) is None
    assert tabla.dimensiones_leidas == []


# ── Precálculo de las variantes ───────────────────────────────────────────


class _ConexionFalsa:
    """Registra las sentencias que el precálculo emite por su cuenta."""

    def __init__(self) -> None:
        self.sentencias: list[str] = []

    def execute(self, sql: str, _params: Any = None) -> _ConexionFalsa:
        self.sentencias.append(sql)
        return self


class _RepoFalso:
    def __init__(self, codigos: list[str], *, roto: str | None = None) -> None:
        self.codigos = codigos
        self.roto = roto
        self.pedido_n: int | None = None
        self.filtros_vistos: list[LicitacionesFilters] = []

    def tecnologias_mas_frecuentes(self, n: int, *, conn: Any = None) -> list[str]:
        self.pedido_n = n
        if self.roto == "ranking":
            raise RuntimeError("statement timeout")
        return self.codigos

    def overview_kpis(self, filters: LicitacionesFilters, *, conn: Any = None) -> dict[str, Any]:
        self.filtros_vistos.append(filters)
        if self.roto is not None and filters.tecnologia == self.roto:
            raise RuntimeError("statement timeout")
        return {"total": len(filters.tecnologia or ""), "importe_total": 1.0}

    def overview_tasa_anulacion(
        self, filters: LicitacionesFilters, *, hace_365d_iso: str, conn: Any = None
    ) -> tuple[int, int]:
        return 1, 10


def test_cada_variante_se_calcula_con_el_filtro_de_su_tecnologia() -> None:
    conn = _ConexionFalsa()
    repo = _RepoFalso(["SAP", "ORACLE"])

    filas = ks._filas_variantes_tecnologia(conn, repo, hace_365d_iso="2025-09-24")

    assert repo.pedido_n == ks.N_TECNOLOGIAS_VARIANTES
    assert repo.filtros_vistos == [
        LicitacionesFilters(tecnologia="SAP"),
        LicitacionesFilters(tecnologia="ORACLE"),
    ]
    assert [(f["metrica"], f["dimension"]) for f in filas] == [
        (ks.OV_KPIS, "tecnologia:SAP"),
        (ks.OV_TASA_ANULACION, "tecnologia:SAP"),
        (ks.OV_KPIS, "tecnologia:ORACLE"),
        (ks.OV_TASA_ANULACION, "tecnologia:ORACLE"),
    ]
    assert json.loads(filas[1]["valor_text"]) == {"anul": 1, "total": 10}


def test_una_variante_que_falla_se_omite_sin_abortar_la_transaccion() -> None:
    """El punto de guardado deshace solo esa variante; las demás se escriben."""
    conn = _ConexionFalsa()
    repo = _RepoFalso(["SAP", "ROTA", "ORACLE"], roto="ROTA")

    filas = ks._filas_variantes_tecnologia(conn, repo, hace_365d_iso="2025-09-24")

    assert {f["dimension"] for f in filas} == {"tecnologia:SAP", "tecnologia:ORACLE"}
    assert conn.sentencias.count("ROLLBACK TO SAVEPOINT ov_variante") == 1
    # Cada punto de guardado abierto se libera, haya fallado o no.
    assert conn.sentencias.count("SAVEPOINT ov_variante") == 3
    assert conn.sentencias.count("RELEASE SAVEPOINT ov_variante") == 3


def test_si_falla_la_eleccion_de_tecnologias_no_hay_variantes() -> None:
    conn = _ConexionFalsa()
    repo = _RepoFalso(["SAP"], roto="ranking")

    assert ks._filas_variantes_tecnologia(conn, repo, hace_365d_iso="2025-09-24") == []
    assert "ROLLBACK TO SAVEPOINT ov_top_tecnologias" in conn.sentencias


def test_las_variantes_van_detras_de_las_filas_globales(monkeypatch: pytest.MonkeyPatch) -> None:
    """El snapshot global se calcula igual que antes y las variantes se añaden al final."""

    class _RepoCompleto(_RepoFalso):
        def overview_adjudicaciones_indicadores(self, *, conn: Any = None) -> dict[str, Any]:
            return _ADJ

        def importe_p75(self, *, conn: Any = None) -> float:
            return 1234.0

        def count_total_activas(self, *, conn: Any = None) -> int:
            return 77

    monkeypatch.setattr(ks, "AggregateRepository", lambda: _RepoCompleto(["SAP"]))
    monkeypatch.setattr(ks, "loose_distinct_strings", lambda _c, _t, _col: ["72000000"])

    filas = ks.compute_overview_snapshot_rows(_ConexionFalsa())

    globales = [f for f in filas if f["dimension"] == "global"]
    assert [f["metrica"] for f in globales] == [
        ks.OV_KPIS,
        ks.OV_ADJ_INDICADORES,
        ks.OV_TASA_ANULACION,
        ks.OV_IMPORTE_P75,
        ks.OV_TOTAL_ACTIVAS,
        ks.META_CPV_VALUES,
    ]
    assert filas[: len(globales)] == globales
    assert [f["dimension"] for f in filas[len(globales) :]] == ["tecnologia:SAP"] * 2
    # La variante de P75/activas no existe: esas dos son solo de la tabla entera.
    assert {f["metrica"] for f in filas if f["dimension"] != "global"} == {
        ks.OV_KPIS,
        ks.OV_TASA_ANULACION,
    }


def test_la_ventana_de_la_tasa_es_la_misma_para_global_y_variantes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un solo ``hace_365d_iso`` por pasada: global y variantes miden la misma ventana."""
    ventanas: list[str] = []

    class _RepoVentana(_RepoFalso):
        def overview_adjudicaciones_indicadores(self, *, conn: Any = None) -> dict[str, Any]:
            return _ADJ

        def importe_p75(self, *, conn: Any = None) -> float:
            return 1.0

        def count_total_activas(self, *, conn: Any = None) -> int:
            return 1

        def overview_tasa_anulacion(
            self, filters: LicitacionesFilters, *, hace_365d_iso: str, conn: Any = None
        ) -> tuple[int, int]:
            ventanas.append(hace_365d_iso)
            return 0, 1

    monkeypatch.setattr(ks, "AggregateRepository", lambda: _RepoVentana(["SAP", "ORACLE"]))
    monkeypatch.setattr(ks, "loose_distinct_strings", lambda _c, _t, _col: [])

    ks.compute_overview_snapshot_rows(_ConexionFalsa())

    assert len(ventanas) == 3
    assert len(set(ventanas)) == 1
    hace = datetime.fromisoformat(ventanas[0])
    assert abs((datetime.now(UTC) - timedelta(days=365)) - hace) < timedelta(minutes=5)
