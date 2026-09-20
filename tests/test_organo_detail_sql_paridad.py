"""C3.2 — el drill-down de órgano agrega en SQL lo que antes hacía en pandas.

``AdjudicacionRepository.load_por_organo`` traía **todas** las adjudicaciones
del órgano a un DataFrame para quedarse con veinte filas (top adjudicatarios),
una mediana (lead-time) y treinta lookups (mejor adjudicación de los mejor
puntuados). Son ahora tres consultas acotadas; estos tests las comparan con el
cálculo en pandas al que sustituyen, sobre la misma muestra sembrada en
Postgres, incluidos los casos que separan las dos semánticas si se implementan
a la ligera:

- horas en la fecha de publicación y fecha pelada en la de adjudicación (días
  completos del intervalo, no resta de fechas de calendario);
- un intervalo que cruza el cambio de hora de marzo (en UTC, no en la zona de
  la sesión);
- adjudicaciones sin nombre, sin importe, sin fecha, y anteriores a la
  publicación;
- otra organización y otro ámbito que no deben colarse.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from db.repositories.aggregates import LicitacionesFilters
from services.analytics.organo_detail import _adj_lookup_for, _lead_time_median

ORGANO = "ORG PARIDAD"


# ── Referencia: el cálculo en pandas que se sustituyó ───────────────────────


def _proyeccion_antigua(organo: str, filters: LicitacionesFilters) -> pd.DataFrame:
    """La consulta de ``load_por_organo``, tal cual era, como fuente de la referencia."""
    from db.database import connect_read
    from db.repositories.adjudicaciones import _EMPRESA_KEY_SQL, _GRAPH_FROM
    from db.repositories.aggregates import build_licitaciones_where
    from db.repositories.base import rows_to_dicts

    where, params = build_licitaciones_where(filters, alias="l")
    sql = (
        f"SELECT a.licitacion_id, {_EMPRESA_KEY_SQL} AS nombre, "
        "       a.importe_adjudicado, a.fecha_adjudicacion, "
        "       l.fecha_publicacion, l.importe AS importe_licitacion "
        f"{_GRAPH_FROM}"
        f"WHERE {where} AND l.organo_contratacion = %s"
    )
    with connect_read() as c:
        df = pd.DataFrame(rows_to_dicts(c.execute(sql, [*params, organo])))
    return df.assign(
        _importe=pd.to_numeric(df["importe_adjudicado"], errors="coerce"),
        _importe_licitacion=pd.to_numeric(df["importe_licitacion"], errors="coerce"),
    )


def _top_pandas(adj_df: pd.DataFrame) -> list[tuple[str, int, float]]:
    g = (
        adj_df.groupby("nombre")
        .agg(count=("nombre", "count"), importe=("_importe", "sum"))
        .sort_values("count", ascending=False)
        .head(20)
        .reset_index()
    )
    return [(str(r["nombre"]), int(r["count"]), float(r["importe"] or 0)) for _, r in g.iterrows()]


def _mejor_pandas(adj_df: pd.DataFrame, ids: list[str]) -> dict[str, tuple[Any, ...]]:
    sub = adj_df[adj_df["licitacion_id"].isin(ids)].sort_values("_importe", ascending=False)
    sub = sub.drop_duplicates(subset=["licitacion_id"], keep="first")
    return {
        str(r["licitacion_id"]): (r["nombre"], None if pd.isna(r["_importe"]) else r["_importe"])
        for _, r in sub.iterrows()
    }


# ── Muestra ─────────────────────────────────────────────────────────────────


def _sembrar() -> None:
    from db.upsert import (
        Adjudicacion,
        Licitacion,
        replace_adjudicaciones_batch,
        upsert_licitaciones,
    )

    licitaciones = [
        # (id, órgano, fecha_publicacion, importe, tecnologia)
        ("P1", ORGANO, "2025-01-01T10:00:00", 1_000_000.0, "SAP"),
        ("P2", ORGANO, "2025-01-05T23:30:00", 500_000.0, "SAP"),
        # Cruza el cambio de hora de marzo en Europa.
        ("P3", ORGANO, "2025-03-20T12:00:00", 300_000.0, "ORACLE"),
        ("P4", ORGANO, "2025-02-01T00:00:00", 200_000.0, "SAP"),
        ("P5", ORGANO, "2025-02-10T08:00:00", None, "SAP"),
        ("P6", ORGANO, "2025-04-01T09:15:00", 800_000.0, "SAP"),
        ("OTRO1", "ORG AJENO", "2025-01-01T10:00:00", 900_000.0, "SAP"),
    ]
    upsert_licitaciones(
        [
            Licitacion(
                id_externo=i,
                titulo=f"Licitación {i}",
                organo_contratacion=o,
                importe=imp,
                estado="ADJ",
                fecha_publicacion=f,
                tecnologia=t,
            )
            for i, o, f, imp, t in licitaciones
        ]
    )
    adjudicaciones = [
        # (licitación, nombre, importe, fecha_adjudicacion)
        ("P1", "ALFA SA", 900_000.0, "2025-01-11"),  # 9 días completos, no 10
        ("P1", "BETA SL", 50_000.0, "2025-01-11"),
        ("P2", "ALFA SA", 450_000.0, "2025-02-05"),
        # Cruza el cambio de hora. Fecha pelada como el resto de la columna:
        # con formatos mezclados, `pd.to_datetime` infiere el del primer valor
        # y anula los demás, y la referencia dejaría de ser la semántica.
        ("P3", "ALFA SA", 280_000.0, "2025-04-20"),
        ("P3", "GAMMA SA", None, "2025-04-21"),
        ("P4", "BETA SL", 150_000.0, "2025-01-15"),  # anterior a la publicación
        ("P5", "ALFA SA", 100_000.0, None),  # sin fecha
        ("P6", "BETA SL", None, "2025-06-01"),
        ("P6", "DELTA SA", 700_000.0, "2025-05-15"),
        ("OTRO1", "ALFA SA", 850_000.0, "2025-01-02"),
    ]
    agrupadas: dict[str, list[Adjudicacion]] = {}
    for lic, nombre, importe, fecha in adjudicaciones:
        agrupadas.setdefault(lic, []).append(
            Adjudicacion(
                licitacion_id=lic,
                nombre=nombre,
                importe_adjudicado=importe,
                fecha_adjudicacion=fecha,
            )
        )
    _total, _dropped, fallidas = replace_adjudicaciones_batch(agrupadas)
    assert fallidas == 0


FILTROS = [
    pytest.param(LicitacionesFilters(), id="sin-filtro"),
    pytest.param(LicitacionesFilters(tecnologia="SAP"), id="tecnologia"),
    pytest.param(LicitacionesFilters(fecha_desde="2025-02-01"), id="fecha-desde"),
]


# ── Paridad ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("filtros", FILTROS)
def test_top_adjudicatarios_igual_que_pandas(tmp_db: Any, filtros: LicitacionesFilters) -> None:
    from db.repositories.adjudicaciones import AdjudicacionRepository

    _sembrar()
    referencia = _top_pandas(_proyeccion_antigua(ORGANO, filtros))
    sql = [
        (str(f["nombre"]), int(f["count"]), float(f["importe"] or 0))
        for f in AdjudicacionRepository().top_adjudicatarios_por_organo(ORGANO, filtros)
    ]
    # Pandas no fija el orden entre empates de `count`; el SQL desempata por
    # nombre. Se compara el contenido y, aparte, que el orden por `count` sea
    # el mismo.
    assert sorted(sql) == sorted(referencia)
    assert [c for _, c, _ in sql] == [c for _, c, _ in referencia]


@pytest.mark.parametrize("filtros", FILTROS)
def test_lead_time_mediano_igual_que_pandas(tmp_db: Any, filtros: LicitacionesFilters) -> None:
    from db.repositories.adjudicaciones import AdjudicacionRepository

    _sembrar()
    referencia = _lead_time_median(_proyeccion_antigua(ORGANO, filtros))
    sql = AdjudicacionRepository().lead_time_mediano_por_organo(ORGANO, filtros)
    assert sql == referencia


def test_lead_time_no_depende_de_la_zona_de_la_sesion(tmp_db: Any) -> None:
    """Con la sesión en Madrid, el intervalo que cruza el cambio de hora sigue en UTC."""
    from db.database import connect_read
    from db.repositories.adjudicaciones import _ts_utc

    with connect_read() as c:
        c.execute("SET TIME ZONE 'Europe/Madrid'")
        # El f-string sólo interpola `_ts_utc` sobre nombres de columna fijos.
        dias = c.execute(
            "SELECT floor(extract(epoch FROM (fin - ini)) / 86400) FROM ("  # noqa: S608
            f"SELECT {_ts_utc('x.fin_txt')} AS fin, {_ts_utc('x.ini_txt')} AS ini "
            "FROM (SELECT '2025-04-20T12:00:00'::text AS fin_txt, "
            "'2025-03-20T12:00:00'::text AS ini_txt) x) y"
        ).fetchone()
        c.execute("RESET TIME ZONE")
    assert float(dias[0]) == 31


def test_lead_time_sin_adjudicaciones_es_none(tmp_db: Any) -> None:
    from db.repositories.adjudicaciones import AdjudicacionRepository

    assert AdjudicacionRepository().lead_time_mediano_por_organo("ORG INEXISTENTE") is None


@pytest.mark.parametrize("filtros", FILTROS)
def test_mejor_adjudicacion_igual_que_pandas(tmp_db: Any, filtros: LicitacionesFilters) -> None:
    from db.repositories.adjudicaciones import AdjudicacionRepository

    _sembrar()
    ids = ["P1", "P2", "P3", "P5", "P6", "OTRO1", "NO-EXISTE"]
    referencia = _mejor_pandas(_proyeccion_antigua(ORGANO, filtros), ids)
    sql = {
        str(f["licitacion_id"]): (f["nombre"], f["importe_adjudicado"])
        for f in AdjudicacionRepository().mejor_adjudicacion_por_licitacion(ORGANO, ids, filtros)
    }
    assert sql == referencia


def test_mejor_adjudicacion_sin_ids_no_consulta() -> None:
    from db.repositories.adjudicaciones import AdjudicacionRepository

    assert AdjudicacionRepository().mejor_adjudicacion_por_licitacion(ORGANO, []) == []


# ── Unitarios del lookup ────────────────────────────────────────────────────


def test_lookup_deriva_baja_y_formatea_fecha() -> None:
    lookup = _adj_lookup_for(
        [
            {
                "licitacion_id": "P1",
                "nombre": "ALFA SA",
                "importe_adjudicado": 900_000.0,
                "importe_licitacion": 1_000_000.0,
                "fecha_adjudicacion": "2025-01-11",
            },
            {
                "licitacion_id": "P6",
                "nombre": None,
                "importe_adjudicado": None,
                "importe_licitacion": 800_000.0,
                "fecha_adjudicacion": None,
            },
        ]
    )
    assert lookup["P1"]["empresa"] == "ALFA SA"
    assert lookup["P1"]["baja_pct"] == pytest.approx(10.0)
    assert lookup["P1"]["fecha_adjudicacion"] == "11/01/2025"
    assert lookup["P6"] == {"empresa": None, "baja_pct": None, "fecha_adjudicacion": None}
