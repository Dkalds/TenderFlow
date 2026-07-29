"""Tests de caracterización para services/analytics/overview.get_overview.

Estos tests fijan un dataset determinístico (vía Postgres real, `tmp_db`) y
verifican los KPIs/breakdowns calculados por ``get_overview``. Sirven como red
de seguridad para la migración de la agregación pandas -> SQL: deben pasar
tanto contra la implementación basada en pandas (antes) como contra la
implementación basada en SQL (después) con el MISMO dataset y el MISMO
resultado.

Los offsets de fecha son relativos a "ahora" (``datetime.now(UTC)``) para que
el test no dependa de qué día se ejecute. Los KPIs sensibles a bucketing de
mes (``por_mes``) se derivan del mismo dataset en vez de hardcodearse, para no
ser frágiles a cruces de mes según cuándo corra la suite.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.analytics.overview import OverviewFilters, get_overview

pytestmark = pytest.mark.usefixtures("tmp_db")


def _iso(offset_hours: float) -> str:
    return (datetime.now(UTC) + timedelta(hours=offset_hours)).isoformat()


# ---------------------------------------------------------------------------
# Dataset fijo — única fuente de verdad para el dataset y los valores
# esperados derivados de él (evita hardcodear números por duplicado).
# ---------------------------------------------------------------------------
# (id, estado, ccaa, organo, importe, pub_offset_h, limite_offset_h|None)
_ROWS: list[tuple[str, str, str, str, float | None, float, float | None]] = [
    ("OV-01", "PUB", "Madrid", "O1", 100000.0, -120, 4800),
    ("OV-02", "EV", "Madrid", "O2", 200000.0, -240, 40),  # limite dentro de 48h
    ("OV-03", "RES", "Madrid", "O3", 50000.0, -480, -120),  # limite ya pasado
    ("OV-04", "ADJ", "Madrid", "O4", 300000.0, -960, -2400),
    ("OV-05", "ANUL", "Cataluña", "O5", 400000.0, -9600, None),  # >365d, fuera tasa_anulacion
    ("OV-06", "PUB", "Cataluña", "O6", 500000.0, -1080, 16),  # limite dentro de 48h
    ("OV-07", "EV", "Cataluña", "O7", 10000.0, -12, 24000),  # pub dentro de 24h -> nuevas_24h
    ("OV-08", "RES", "Valencia", "O8", None, -1440, None),  # importe nulo
    ("OV-09", "ADJ", "Valencia", "O9", 150000.0, -1680, -240),
    ("OV-10", "PUB", "Valencia", "O10", 600000.0, -1920, 48000),
    ("OV-11", "EV", "Andalucía", "O11", 700000.0, -2160, 120000),
    ("OV-12", "ANUL", "Andalucía", "O12", 250000.0, -2400, -1200),  # dentro de 365d
]


def _insert_dataset(db) -> None:
    from db.upsert import Licitacion, upsert_licitaciones

    items = [
        Licitacion(
            id_externo=id_externo,
            titulo=f"Licitacion {id_externo}",
            organo_contratacion=organo,
            importe=importe,
            estado=estado,
            fecha_publicacion=_iso(pub_h),
            fecha_limite=_iso(limite_h) if limite_h is not None else None,
            ccaa=ccaa,
            fecha_extraccion=_iso(pub_h),
        )
        for id_externo, estado, ccaa, organo, importe, pub_h, limite_h in _ROWS
    ]
    upsert_licitaciones(items)


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    _insert_dataset(db_mod)
    return db_mod


# ---------------------------------------------------------------------------
# Valores esperados derivados del dataset (no hardcodeados por duplicado)
# ---------------------------------------------------------------------------


def _expected_kpis() -> dict:
    importes = [r[4] for r in _ROWS if r[4] is not None]
    return {
        "total": len(_ROWS),
        "importe_total": sum(importes),
        "importe_medio": sum(importes) / len(importes),
        "organos_unicos": len({r[3] for r in _ROWS}),
    }


def _expected_por_estado() -> dict[str, int]:
    out: dict[str, int] = {}
    for r in _ROWS:
        out[r[1]] = out.get(r[1], 0) + 1
    return out


def _expected_por_mes() -> dict[str, tuple[int, float]]:
    out: dict[str, list] = {}
    for _id, _estado, _ccaa, _organo, importe, pub_h, _lim in _ROWS:
        mes = (datetime.now(UTC) + timedelta(hours=pub_h)).strftime("%Y-%m")
        acc = out.setdefault(mes, [0, 0.0])
        acc[0] += 1
        acc[1] += importe or 0.0
    return {k: (v[0], v[1]) for k, v in out.items()}


def _expected_concentracion_top10() -> float:
    by_organo: dict[str, float] = {}
    for r in _ROWS:
        if r[4] is not None:
            by_organo[r[3]] = by_organo.get(r[3], 0.0) + r[4]
    total = sum(by_organo.values())
    top10 = sum(sorted(by_organo.values(), reverse=True)[:10])
    return top10 / total * 100


def _expected_concentracion_geo_top3() -> float:
    by_ccaa: dict[str, float] = {}
    for r in _ROWS:
        by_ccaa[r[2]] = by_ccaa.get(r[2], 0.0) + (r[4] or 0.0)
    total = sum(by_ccaa.values())
    top3 = sum(sorted(by_ccaa.values(), reverse=True)[:3])
    return top3 / total * 100


def test_kpis(db):
    res = get_overview(OverviewFilters())
    expected = _expected_kpis()
    assert res.total_licitaciones == expected["total"]
    assert res.importe_total == pytest.approx(expected["importe_total"])
    assert res.importe_medio == pytest.approx(expected["importe_medio"])
    assert res.organos_unicos == expected["organos_unicos"]


def test_por_estado(db):
    res = get_overview(OverviewFilters())
    got = {e.estado: e.n for e in res.por_estado}
    assert got == _expected_por_estado()


def test_funnel_estados_orden_fijo(db):
    res = get_overview(OverviewFilters())
    # Orden fijo PUB, EV, RES, ADJ, ANUL — independiente del conteo.
    assert [f.estado for f in res.funnel_estados] == ["PUB", "EV", "RES", "ADJ", "ANUL"]
    expected_n = _expected_por_estado()
    total = len(_ROWS)
    for step in res.funnel_estados:
        assert step.n == expected_n.get(step.estado, 0)
        assert step.pct == pytest.approx(expected_n.get(step.estado, 0) / total * 100)


def test_por_mes(db):
    res = get_overview(OverviewFilters())
    expected = _expected_por_mes()
    got = {m.mes: (m.n_licitaciones, m.importe) for m in res.por_mes}
    assert set(got.keys()) == set(expected.keys())
    for mes, (n, importe) in expected.items():
        got_n, got_importe = got[mes]
        assert got_n == n
        assert got_importe == pytest.approx(importe)


def test_top_organos(db):
    res = get_overview(OverviewFilters())
    got = {o.organo_contratacion: (o.n, o.importe) for o in res.top_organos}
    expected = {r[3]: (1, r[4] or 0.0) for r in _ROWS if r[4] is not None}
    # O8 (importe None) contribuye 0 al agregado en pandas (sum skipna) — no
    # aparece con importe pero SÍ aparece como organo con n=1, importe=0.0 en
    # el groupby actual (sum sobre serie vacía de NaN = 0.0, no excluido del
    # todo). Se valida explícitamente su presencia con importe 0.
    assert got["O8"] == (1, 0.0)
    for organo, (n, importe) in expected.items():
        assert got[organo] == (n, pytest.approx(importe))


def test_concentracion_top10(db):
    res = get_overview(OverviewFilters())
    assert res.concentracion_top10 == pytest.approx(_expected_concentracion_top10())


def test_concentracion_geo_top3_y_ccaa_cubiertas(db):
    res = get_overview(OverviewFilters())
    assert res.concentracion_geo_top3 == pytest.approx(_expected_concentracion_geo_top3())
    assert res.ccaa_cubiertas == len({r[2] for r in _ROWS})


def test_tasa_anulacion_respeta_ventana_12_meses(db):
    res = get_overview(OverviewFilters())
    # Solo OV-12 (ANUL, -2400h ~= 100d) cae dentro de los últimos 365 días;
    # OV-05 (ANUL, -9600h ~= 400d) queda fuera de la ventana.
    dentro_12m = [r for r in _ROWS if r[5] > -365 * 24]
    anul_12m = [r for r in dentro_12m if r[1] == "ANUL"]
    expected = len(anul_12m) / len(dentro_12m) * 100
    assert res.tasa_anulacion == pytest.approx(expected)


def test_para_hoy_counts(db):
    res = get_overview(OverviewFilters())
    # nuevas_24h: pub dentro de las últimas 24h -> solo OV-07 (-12h).
    assert res.nuevas_24h == 1
    # vencen_48h: fecha_limite en [ahora, ahora+48h) -> OV-02 (+40h) y OV-06 (+16h).
    assert res.vencen_48h == 2


def test_filtro_ccaa(db):
    res = get_overview(OverviewFilters(ccaa="Madrid"))
    assert res.total_licitaciones == 4
    assert {e.estado for e in res.por_estado} == {"PUB", "EV", "RES", "ADJ"}


def test_filtro_estado(db):
    res = get_overview(OverviewFilters(estado="ANUL"))
    assert res.total_licitaciones == 2
    assert res.importe_total == pytest.approx(650000.0)


def test_filtro_importe_min(db):
    res = get_overview(OverviewFilters(importe_min=300000))
    # >= 300000: OV-04(300000), OV-05(400000), OV-06(500000), OV-10(600000),
    # OV-11(700000) -> 5 filas. OV-08 (None) excluida.
    assert res.total_licitaciones == 5


def test_filtro_q_busca_titulo_organo_id(db):
    res = get_overview(OverviewFilters(q="OV-07"))
    assert res.total_licitaciones == 1
    res_organo = get_overview(OverviewFilters(q="O11"))
    assert res_organo.total_licitaciones == 1


def test_filtro_fecha(db):
    hoy = datetime.now(UTC)
    desde = (hoy + timedelta(hours=-500)).date()
    res = get_overview(OverviewFilters(fecha_desde=desde))
    # fecha_desde se compara como fecha (sin hora) >= desde: se cuentan filas
    # cuya fecha de publicación (truncada a día) cae en o después de ese día.
    corte = desde.isoformat()
    expected = len([r for r in _ROWS if (hoy + timedelta(hours=r[5])).date().isoformat() >= corte])
    assert res.total_licitaciones == expected


def test_empty_result():
    res = get_overview(OverviewFilters())
    assert res.total_licitaciones == 0
    assert res.por_estado == []
    assert res.por_mes == []
    assert res.top_organos == []
