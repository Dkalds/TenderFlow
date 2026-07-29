"""Tests de caracterización para services/analytics/tecnologias.

Fija un dataset determinístico (Postgres real vía `tmp_db`) y verifica el
resultado de ``get_tecnologias``/``get_tecnologia_detalle``. Red de seguridad
para migrar la agregación de pandas a SQL: debe pasar igual antes (pandas) y
después (SQL) contra el mismo dataset.

El dataset se mantiene deliberadamente por debajo de los recortes top-N
(``_TOP_ORGANOS``/``_TOP_CCAA`` = 10, ``_TOP_TECHS_CROSS``=10,
``_TOP_TECHS_EVOL``=8) para que la comparación sea 100% determinística: con
empates en el recorte, el orden de desempate de pandas (`nlargest`, no
garantizado estable) no tiene por qué coincidir con el de una query SQL
distinta, y no es lo que este test necesita validar.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.analytics.tecnologias import (
    TecnologiaDetalleFilters,
    TecnologiasFilters,
    get_tecnologia_detalle,
    get_tecnologias,
)

pytestmark = pytest.mark.usefixtures("tmp_db")


def _iso(offset_days: float) -> str:
    return (datetime.now(UTC) + timedelta(days=offset_days)).isoformat()


# (id, tecnologia_csv|None, estado, organo, ccaa, importe, pub_offset_days)
_ROWS: list[tuple[str, str | None, str, str, str, float, float]] = [
    ("TE-01", "SAP", "ADJ", "Org1", "Madrid", 100000.0, -10),
    ("TE-02", "SAP,SALESFORCE", "PUB", "Org2", "Madrid", 200000.0, -20),
    ("TE-03", "SALESFORCE", "ADJ", "Org3", "Cataluña", 50000.0, -40),
    ("TE-04", "ORACLE", "EV", "Org4", "Cataluña", 300000.0, -400),
    ("TE-05", "", "PUB", "Org5", "Valencia", 10000.0, -15),  # sin_clasificar
    ("TE-06", None, "RES", "Org6", "Valencia", 20000.0, -25),  # sin_clasificar
    ("TE-07", "SAP", "ADJ", "Org7", "Andalucía", 400000.0, -5),
    ("TE-08", "MICROSOFT", "PUB", "Org8", "Andalucía", 500000.0, -60),
    ("TE-09", "IBM", "ADJ", "Org9", "Galicia", 60000.0, -70),
    ("TE-10", "SERVICENOW", "PUB", "Org10", "Galicia", 70000.0, -80),
    ("TE-11", "WORKDAY", "ADJ", "Org1", "Madrid", 80000.0, -90),
    ("TE-12", "SAP", "EV", "Org2", "Madrid", 90000.0, -100),
    ("TE-13", "SALESFORCE", "ADJ", "Org3", "Cataluña", 110000.0, -110),
]

_LABELS = {
    "SAP": "SAP",
    "SALESFORCE": "Salesforce",
    "ORACLE": "Oracle",
    "MICROSOFT": "Microsoft Dynamics / Azure",
    "IBM": "IBM",
    "SERVICENOW": "ServiceNow",
    "WORKDAY": "Workday",
}


def _insert_dataset(db) -> None:
    from db.upsert import Licitacion, upsert_licitaciones

    items = [
        Licitacion(
            id_externo=id_externo,
            titulo=f"Licitacion {id_externo}",
            organo_contratacion=organo,
            importe=importe,
            estado=estado,
            fecha_publicacion=_iso(pub_d),
            tecnologia=tec,
            ccaa=ccaa,
            fecha_extraccion=_iso(pub_d),
        )
        for id_externo, tec, estado, organo, ccaa, importe, pub_d in _ROWS
    ]
    upsert_licitaciones(items)


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    _insert_dataset(db_mod)
    return db_mod


def _exploded() -> list[dict]:
    """Replica en Python puro el explode + mapeo a label del servicio."""
    out = []
    for id_externo, tec, estado, organo, ccaa, importe, pub_d in _ROWS:
        codes = [c.strip() for c in (tec or "").split(",") if c.strip()]
        for code in codes:
            out.append(
                {
                    "id": id_externo,
                    "label": _LABELS[code],
                    "estado": estado,
                    "organo": organo,
                    "ccaa": ccaa,
                    "importe": importe,
                    "pub_d": pub_d,
                }
            )
    return out


def test_sin_clasificar_y_total(db):
    res = get_tecnologias(TecnologiasFilters())
    assert res.total == len(_ROWS)
    assert res.sin_clasificar == 2


def test_entries_count_importe_pct(db):
    res = get_tecnologias(TecnologiasFilters())
    rows = _exploded()
    total = len(_ROWS)

    by_label: dict[str, list[dict]] = {}
    for r in rows:
        by_label.setdefault(r["label"], []).append(r)

    got = {e.tecnologia: e for e in res.tecnologias}
    assert set(got.keys()) == set(by_label.keys())

    for label, items in by_label.items():
        count = len(items)
        importe = sum(i["importe"] for i in items)
        pct_adj = sum(1 for i in items if i["estado"] == "ADJ") / count * 100
        entry = got[label]
        assert entry.count == count
        assert entry.importe == pytest.approx(importe)
        assert entry.importe_medio == pytest.approx(importe / count)
        assert entry.pct == pytest.approx(round(count / total * 100, 2))
        assert entry.pct_adjudicado == pytest.approx(round(pct_adj, 1))


def test_kpis_lider_y_medias(db):
    res = get_tecnologias(TecnologiasFilters())
    rows = _exploded()
    by_label: dict[str, list[dict]] = {}
    for r in rows:
        by_label.setdefault(r["label"], []).append(r)

    assert res.n_tecnologias == len(by_label)
    lider_label, lider_items = max(by_label.items(), key=lambda kv: len(kv[1]))
    assert res.tecnologia_lider == lider_label
    assert res.lider_count == len(lider_items)

    per_label_importe = [sum(i["importe"] for i in items) for items in by_label.values()]
    expected_importe_medio_global = sum(per_label_importe) / len(by_label)
    assert res.importe_medio_global == pytest.approx(round(expected_importe_medio_global, 2))

    per_label_pct_adj = [
        round(sum(1 for i in items if i["estado"] == "ADJ") / len(items) * 100, 1)
        for items in by_label.values()
    ]
    expected_tasa = sum(per_label_pct_adj) / len(by_label)
    assert res.tasa_adjudicacion_media == pytest.approx(round(expected_tasa, 1))


def test_cross_organo(db):
    res = get_tecnologias(TecnologiasFilters())
    rows = _exploded()
    expected: dict[tuple[str, str], int] = {}
    for r in rows:
        key = (r["organo"], r["label"])
        expected[key] = expected.get(key, 0) + 1

    got = {(c.organo, c.tecnologia): c.count for c in res.cross_organo}
    assert got == expected


def test_cross_geo(db):
    res = get_tecnologias(TecnologiasFilters())
    rows = _exploded()
    expected: dict[tuple[str, str], int] = {}
    for r in rows:
        key = (r["ccaa"], r["label"])
        expected[key] = expected.get(key, 0) + 1

    got = {(c.ccaa, c.tecnologia): c.count for c in res.cross_geo}
    assert got == expected


def test_evolucion_mensual(db):
    res = get_tecnologias(TecnologiasFilters())
    rows = _exploded()
    expected: dict[tuple[str, str], list] = {}
    for r in rows:
        mes = (datetime.now(UTC) + timedelta(days=r["pub_d"])).strftime("%Y-%m")
        key = (mes, r["label"])
        acc = expected.setdefault(key, [0, 0.0])
        acc[0] += 1
        acc[1] += r["importe"]

    got = {(e.mes, e.tecnologia): (e.count, e.importe) for e in res.evolucion_mensual}
    assert set(got.keys()) == set(expected.keys())
    for key, (n, importe) in expected.items():
        got_n, got_importe = got[key]
        assert got_n == n
        assert got_importe == pytest.approx(importe)


def test_filtro_ccaa(db):
    res = get_tecnologias(TecnologiasFilters(ccaa="Madrid"))
    assert res.total == 4  # TE-01, TE-02, TE-11, TE-12
    assert res.sin_clasificar == 0


def test_filtro_fechas(db):
    hoy = datetime.now(UTC)
    desde = (hoy + timedelta(days=-30)).date()
    res = get_tecnologias(TecnologiasFilters(fecha_desde=desde))
    expected = len(
        [
            r
            for r in _ROWS
            if (hoy + timedelta(days=r[6])).date().isoformat() >= desde.isoformat()
        ]
    )
    assert res.total == expected


def test_empty_result():
    res = get_tecnologias(TecnologiasFilters())
    assert res.total == 0
    assert res.tecnologias == []


def test_tecnologia_detalle(db):
    res = get_tecnologia_detalle("SAP", TecnologiaDetalleFilters(limit=100))
    rows = [r for r in _exploded() if r["label"] == "SAP"]
    assert res.n == len(rows)
    assert res.importe_total == pytest.approx(sum(r["importe"] for r in rows))
    assert res.importe_medio == pytest.approx(res.importe_total / res.n)
    # Orden por importe desc; el más caro es TE-07 (400000).
    assert res.items[0].id_externo == "TE-07"


def test_tecnologia_detalle_vacia(db):
    res = get_tecnologia_detalle("WORKDAY_INEXISTENTE", TecnologiaDetalleFilters())
    assert res.n == 0
    assert res.items == []
