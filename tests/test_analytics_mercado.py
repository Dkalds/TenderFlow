"""Tests for the Mercado analytics services (tecnologias, proyectos-modulos, clusters).

These cover the React parity work: technology cross-tabs and detail,
SAP module YoY / tipo x estado / CPV breakdowns, and real semantic clustering.
Data access is mocked at ``load_stats_dataframe`` so the tests stay fast and
DB-independent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import services.analytics.clusters as clusters_mod
import services.analytics.proyectos_modulos as pm_mod
import services.analytics.tecnologias as tec_mod


def _iso(days_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


# ---------------------------------------------------------------------------
# tecnologias
# ---------------------------------------------------------------------------


def _tec_rows() -> list[dict]:
    rows: list[dict] = []
    base = {
        "organo_contratacion": "Ayuntamiento A",
        "ccaa": "Madrid",
        "cpv": "72000000",
        "importe": 100_000.0,
        "fecha_publicacion": _iso(30),
    }
    # 5x SAP (2 adjudicadas)
    for i in range(5):
        rows.append(
            {
                **base,
                "id_externo": f"S{i}",
                "titulo": f"SAP proyecto {i}",
                "tecnologia": "SAP",
                "estado": "ADJ" if i < 2 else "PUB",
                "organo_contratacion": "Ayuntamiento A" if i % 2 else "Diputacion B",
                "ccaa": "Madrid" if i % 2 else "Cataluña",
            }
        )
    # 3x ORACLE
    for i in range(3):
        rows.append(
            {
                **base,
                "id_externo": f"O{i}",
                "titulo": f"Oracle base {i}",
                "tecnologia": "ORACLE",
                "estado": "PUB",
            }
        )
    # 2x comma-separated (explodes to SAP + SALESFORCE)
    for i in range(2):
        rows.append(
            {
                **base,
                "id_externo": f"C{i}",
                "titulo": f"SAP y Salesforce {i}",
                "tecnologia": "SAP,SALESFORCE",
                "estado": "ADJ",
            }
        )
    # 2x unclassified
    for i in range(2):
        rows.append(
            {
                **base,
                "id_externo": f"N{i}",
                "titulo": f"Generico {i}",
                "tecnologia": "",
                "estado": "PUB",
            }
        )
    return rows


def test_tecnologias_kpis_and_explode():
    with patch.object(tec_mod, "load_stats_dataframe", return_value=_tec_rows()):
        res = tec_mod.get_tecnologias(tec_mod.TecnologiasFilters())

    labels = {e.tecnologia for e in res.tecnologias}
    assert labels == {"SAP", "Oracle", "Salesforce"}
    assert res.n_tecnologias == 3
    assert res.sin_clasificar == 2
    # total = todas las licitaciones en alcance (denominador de cobertura).
    assert res.total >= res.sin_clasificar
    assert res.total - res.sin_clasificar > 0  # hay clasificadas
    # SAP = 5 direct + 2 comma rows = 7, and is the leader.
    sap = next(e for e in res.tecnologias if e.tecnologia == "SAP")
    assert sap.count == 7
    assert res.tecnologia_lider == "SAP"
    assert res.lider_count == 7
    # SAP adjudicadas: 2 (PUB/ADJ) direct + 2 comma (ADJ) = 4 of 7.
    assert round(sap.pct_adjudicado) == round(4 / 7 * 100)
    assert sap.importe_medio == sap.importe / sap.count


def test_tecnologias_cross_tabs_present():
    with patch.object(tec_mod, "load_stats_dataframe", return_value=_tec_rows()):
        res = tec_mod.get_tecnologias(tec_mod.TecnologiasFilters())
    assert res.cross_organo and all(c.count > 0 for c in res.cross_organo)
    assert res.cross_geo and all(c.count > 0 for c in res.cross_geo)
    assert res.evolucion_mensual and all(e.mes and e.tecnologia for e in res.evolucion_mensual)


def test_tecnologia_detalle_filters_by_label():
    with patch.object(tec_mod, "load_stats_dataframe", return_value=_tec_rows()):
        det = tec_mod.get_tecnologia_detalle("SAP", tec_mod.TecnologiaDetalleFilters(limit=50))
    assert det.tecnologia == "SAP"
    assert det.n == 7  # de-duplicated across the comma-separated explode
    assert len(det.items) == 7
    # estado is rendered as a human label, not the raw code.
    assert all(it.estado in {"Adjudicada", "Publicada"} for it in det.items if it.estado)


def test_tecnologias_empty():
    with patch.object(tec_mod, "load_stats_dataframe", return_value=[]):
        res = tec_mod.get_tecnologias(tec_mod.TecnologiasFilters())
    assert res.tecnologias == []
    assert res.n_tecnologias == 0


# ---------------------------------------------------------------------------
# proyectos-modulos
# ---------------------------------------------------------------------------


def _pm_rows() -> list[dict]:
    rows: list[dict] = []
    base = {
        "organo_contratacion": "Org",
        "ccaa": "Madrid",
        "cpv": "72260000",
        "importe": 200_000.0,
        "tecnologia": "SAP",
    }
    # 4 S/4HANA mentions this year
    for i in range(4):
        rows.append(
            {
                **base,
                "id_externo": f"A{i}",
                "titulo": "Proyecto SAP S/4HANA implantacion",
                "estado": "ADJ",
                "tipo_contrato": "2",
                "fecha_publicacion": _iso(60),
            }
        )
    # 1 S/4HANA mention previous year
    rows.append(
        {
            **base,
            "id_externo": "P0",
            "titulo": "Migracion SAP S/4HANA",
            "estado": "PUB",
            "tipo_contrato": "2",
            "fecha_publicacion": _iso(500),
        }
    )
    # some other contracts for tipo_estado / cpv variety
    for i in range(3):
        rows.append(
            {
                **base,
                "id_externo": f"B{i}",
                "titulo": "Servicio generico TI",
                "estado": "PUB",
                "tipo_contrato": "1",
                "cpv": "48000000",
                "fecha_publicacion": _iso(90),
            }
        )
    return rows


def test_proyectos_modulos_yoy_tipo_estado_cpv():
    with patch.object(pm_mod, "load_stats_dataframe", return_value=_pm_rows()):
        res = pm_mod.get_proyectos_modulos(pm_mod.ProyectosModulosFilters())

    assert res.top_modulo_yoy is not None
    assert res.top_modulo_yoy.modulo == "S/4HANA"
    assert res.top_modulo_yoy.n_act == 4
    # 4 this year vs 1 last year -> +300%.
    assert round(res.top_modulo_yoy.crecimiento_pct) == 300

    assert res.tipo_estado and all(t.n > 0 for t in res.tipo_estado)
    # estado labelled, tipo kept raw.
    assert any(t.estado == "Adjudicada" for t in res.tipo_estado)

    assert res.cpv and res.cpv[0].count >= res.cpv[-1].count
    assert all(c.cpv_desc for c in res.cpv)


def test_proyectos_modulos_importe_distinct_sin_doble_conteo():
    """Una licitación con varios módulos SAP cuenta su importe UNA vez (no por módulo)."""
    rows = [
        {
            "id_externo": "M1",
            "titulo": "Implantacion SAP FI y CO integrados",  # detecta FI + CO
            "organo_contratacion": "Org",
            "ccaa": "Madrid",
            "cpv": "72000000",
            "importe": 1_000_000.0,
            "tecnologia": "SAP",
            "estado": "ADJ",
            "tipo_contrato": "2",
            "fecha_publicacion": _iso(30),
        },
    ]
    with patch.object(pm_mod, "load_stats_dataframe", return_value=rows):
        res = pm_mod.get_proyectos_modulos(pm_mod.ProyectosModulosFilters())

    # FI y CO detectados → 2 filas de módulo…
    mods = {m.modulo for m in res.modulos}
    assert {"FI", "CO"} <= mods
    # …pero 1 sola licitación clasificada, con su importe contado UNA vez.
    assert res.total_clasificados == 1
    assert res.importe_total_sap == 1_000_000.0
    assert res.ticket_medio_sap == 1_000_000.0
    # La suma de filas de módulo SÍ doble-cuenta (FI 1M + CO 1M = 2M): por eso el
    # KPI debe venir de importe_total_sap distinct, no de sum(modulos.importe).
    assert sum(m.importe for m in res.modulos) == 2_000_000.0


# ---------------------------------------------------------------------------
# clusters
# ---------------------------------------------------------------------------


def _cluster_rows(n: int = 30) -> list[dict]:
    titulos = [
        "Mantenimiento sistema SAP S/4HANA financiero",
        "Implantacion Salesforce CRM atencion ciudadana",
        "Soporte Oracle base de datos y migracion",
    ]
    rows = []
    for i in range(n):
        rows.append(
            {
                "id_externo": f"L{i:03d}",
                "titulo": titulos[i % len(titulos)] + f" expediente {i}",
                "organo_contratacion": f"Organo {i % 4}",
                "importe": float(50_000 * ((i % 5) + 1)),
                "estado": "ADJ" if i % 2 else "PUB",
                "ccaa": "Madrid",
                "tecnologia": "SAP",
                "cpv": "72000000",
                "fecha_publicacion": _iso(40 + i),
            }
        )
    return rows


def test_clusters_shape_and_labels():
    rows = _cluster_rows(30)
    with patch.object(clusters_mod, "load_stats_dataframe", return_value=rows):
        res = clusters_mod.get_clusters(clusters_mod.ClustersFilters(n_clusters=3))

    assert res.total == 30
    assert res.n_clusters_detectados == 3
    assert len(res.clusters) == 3
    # Calidad de la partición expuesta (guía para elegir K).
    assert res.silhouette is not None
    assert -1.0 <= res.silhouette <= 1.0
    for c in res.clusters:
        assert c.n > 0
        assert c.label and c.label != ""
        assert c.importe_box is not None
        b = c.importe_box
        assert b.min <= b.q1 <= b.median <= b.q3 <= b.max
        assert c.items  # bounded drill-down sample present
        # Descriptores de identidad (interpretabilidad).
        assert c.organo_dominante in {"Organo 0", "Organo 1", "Organo 2", "Organo 3"}
        assert c.cpv_dominante  # cpv 72000000 → label legible no vacío
    # sorted by n descending
    sizes = [c.n for c in res.clusters]
    assert sizes == sorted(sizes, reverse=True)


def test_clusters_deterministic():
    rows = _cluster_rows(30)
    with patch.object(clusters_mod, "load_stats_dataframe", return_value=rows):
        a = clusters_mod.get_clusters(clusters_mod.ClustersFilters(n_clusters=3))
        b = clusters_mod.get_clusters(clusters_mod.ClustersFilters(n_clusters=3))
    assert [(c.cluster_id, c.n, c.label) for c in a.clusters] == [
        (c.cluster_id, c.n, c.label) for c in b.clusters
    ]


def test_clusters_too_few_rows():
    with patch.object(clusters_mod, "load_stats_dataframe", return_value=_cluster_rows(5)):
        res = clusters_mod.get_clusters(clusters_mod.ClustersFilters(n_clusters=3))
    assert res.total == 5
    assert res.clusters == []
