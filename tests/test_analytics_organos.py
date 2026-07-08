"""Tests unitarios para services/analytics organos + organo_detail + overview.

Parchean las cargas de datos de la capa de servicios con DataFrames sintéticos
para validar las agregaciones sin tocar la BD.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from services.analytics.organo_detail import (
    OrganoDetailFilters,
    _lead_time_median,
    get_organo_detail,
)
from services.analytics.organos import OrganosFilters, get_organos
from services.analytics.overview import OverviewFilters, get_overview

# ── Datos sintéticos ────────────────────────────────────────────────────────


def _lic_rows() -> list[dict]:
    return [
        {
            "id_externo": "L1",
            "titulo": "Servicio SAP cloud",
            "organo_contratacion": "ORG A",
            "importe": 1_000_000.0,
            "estado": "ADJ",
            "fecha_publicacion": "2025-01-01",
            "ccaa": "Madrid",
            "tipo_contrato": "2",
            "url": "https://example.org/L1",
            "modulos_str": "FI · CO",
        },
        {
            "id_externo": "L2",
            "titulo": "Mantenimiento ERP",
            "organo_contratacion": "ORG A",
            "importe": 500_000.0,
            "estado": "ADJ",
            "fecha_publicacion": "2025-01-01",
            "ccaa": "Madrid",
            "tipo_contrato": "2",
            "url": "https://example.org/L2",
            "modulos_str": None,
        },
        {
            "id_externo": "L3",
            "titulo": "Obras varias",
            "organo_contratacion": "ORG B",
            "importe": 200_000.0,
            "estado": "PUB",
            "fecha_publicacion": "2025-02-01",
            "ccaa": "Cataluña",
            "tipo_contrato": "3",
            "url": None,
            "modulos_str": None,
        },
    ]


def _adj_rows() -> list[dict]:
    # ORG A: L1 → 10 días, L2 → 20 días → mediana 15
    return [
        {
            "licitacion_id": "L1",
            "organo_contratacion": "ORG A",
            "nombre_canonico": "EMPRESA UNO",
            "importe_adjudicado": 900_000.0,
            "fecha_publicacion": "2025-01-01",
            "fecha_adjudicacion": "2025-01-11",
            "baja_pct": 10.0,
        },
        {
            "licitacion_id": "L2",
            "organo_contratacion": "ORG A",
            "nombre_canonico": "EMPRESA DOS",
            "importe_adjudicado": 450_000.0,
            "fecha_publicacion": "2025-01-01",
            "fecha_adjudicacion": "2025-01-21",
            "baja_pct": None,
        },
    ]


# ── _lead_time_median ───────────────────────────────────────────────────────


def test_lead_time_median_basic():
    df = pd.DataFrame(_adj_rows())
    assert _lead_time_median(df) == 15.0


def test_lead_time_median_empty():
    assert _lead_time_median(pd.DataFrame()) is None


def test_lead_time_median_missing_columns():
    df = pd.DataFrame([{"foo": 1}])
    assert _lead_time_median(df) is None


def test_lead_time_median_ignores_negative_diffs():
    rows = [
        {"fecha_publicacion": "2025-01-20", "fecha_adjudicacion": "2025-01-10"},  # negativo
        {"fecha_publicacion": "2025-01-01", "fecha_adjudicacion": "2025-01-09"},  # 8 días
    ]
    assert _lead_time_median(pd.DataFrame(rows)) == 8.0


# ── get_organos ─────────────────────────────────────────────────────────────


def test_get_organos_ranking_and_pct():
    with patch(
        "services.analytics.organos.load_stats_dataframe",
        return_value=_lic_rows(),
    ):
        result = get_organos(OrganosFilters())

    assert result.total_organos == 2
    # ORG A tiene 2 licitaciones, ORG B 1 → ORG A primero
    assert result.organos[0].organo_contratacion == "ORG A"
    assert result.organos[0].count == 2
    # pct sobre el total de 3 licitaciones
    assert round(result.organos[0].pct) == 67
    # importe agregado de ORG A
    assert result.organos[0].importe == 1_500_000.0
    # importe_total sobre TODO el dataset (ORG A 1.5M + ORG B 0.2M)
    assert result.importe_total == 1_700_000.0


def test_get_organos_totales_sobre_dataset_completo_no_top_n():
    """importe_total y concentracion_top10 reflejan TODO el dataset, no el top-N
    que devuelve `organos` (regresión: antes el frontend los sumaba sobre el top-50)."""
    with patch(
        "services.analytics.organos.load_stats_dataframe",
        return_value=_lic_rows(),
    ):
        result = get_organos(OrganosFilters(limit=1))

    # Aunque solo se devuelve 1 órgano (top-1 = ORG A)…
    assert len(result.organos) == 1
    assert result.organos[0].importe == 1_500_000.0
    # …el importe total incluye también a ORG B (fuera del top-1).
    assert result.importe_total == 1_700_000.0
    # concentración del top-10 = 100% (solo hay 2 órganos, ambos en el top-10).
    assert result.concentracion_top10 == 100.0


def test_get_organos_empty():
    with patch("services.analytics.organos.load_stats_dataframe", return_value=[]):
        result = get_organos(OrganosFilters())
    assert result.total_organos == 0
    assert result.organos == []


def test_get_organos_q_accent_insensitive():
    """q sin tildes encuentra órganos con tildes (y viceversa), case-insensitive."""
    rows = _lic_rows()
    rows.append(
        {
            "id_externo": "L4",
            "titulo": "CPD",
            "organo_contratacion": "Gerencia de Informática de la Seguridad Social",
            "importe": 50_000.0,
            "estado": "PUB",
            "fecha_publicacion": "2025-03-01",
            "ccaa": "Madrid",
            "tipo_contrato": "2",
            "url": None,
            "modulos_str": None,
        }
    )
    with patch("services.analytics.organos.load_stats_dataframe", return_value=rows):
        sin_tildes = get_organos(OrganosFilters(q="gerencia de informatica"))
        con_tildes = get_organos(OrganosFilters(q="INFORMÁTICA"))

    for result in (sin_tildes, con_tildes):
        assert [o.organo_contratacion for o in result.organos] == [
            "Gerencia de Informática de la Seguridad Social"
        ]


def test_get_organos_q_filters_before_limit():
    """Un órgano fuera del top-limit sigue siendo encontrable con q."""
    rows = _lic_rows()  # ORG A: 2 lics, ORG B: 1 lic
    rows.append(
        {
            "id_externo": "L4",
            "titulo": "CPD",
            "organo_contratacion": "Gerencia de Informática de la Seguridad Social",
            "importe": 50_000.0,
            "estado": "PUB",
            "fecha_publicacion": "2025-03-01",
            "ccaa": "Madrid",
            "tipo_contrato": "2",
            "url": None,
            "modulos_str": None,
        }
    )
    # limit=1: sin q solo saldría ORG A; con q el match aparece igual
    with patch("services.analytics.organos.load_stats_dataframe", return_value=rows):
        sin_q = get_organos(OrganosFilters(limit=1))
        con_q = get_organos(OrganosFilters(q="seguridad social", limit=1))

    assert [o.organo_contratacion for o in sin_q.organos] == ["ORG A"]
    assert [o.organo_contratacion for o in con_q.organos] == [
        "Gerencia de Informática de la Seguridad Social"
    ]


# ── get_organo_detail ───────────────────────────────────────────────────────


def test_get_organo_detail_lead_time_and_fields():
    with (
        patch(
            "services.analytics.organo_detail.load_stats_dataframe",
            return_value=_lic_rows(),
        ),
        patch(
            "services.analytics.organo_detail.load_raw_adjudicaciones",
            return_value=_adj_rows(),
        ),
    ):
        result = get_organo_detail("ORG A", OrganoDetailFilters())

    # KPIs
    assert result.kpis.total_licitaciones == 2
    assert result.kpis.importe_total == 1_500_000.0
    assert result.kpis.pct_adjudicado == 100.0
    # Lead time: mediana de 10 y 20 días
    assert result.kpis.lead_time_medio == 15.0
    # Top adjudicatario
    assert result.kpis.top_adjudicatario in {"EMPRESA UNO", "EMPRESA DOS"}

    # top_scored enriquecido con estado_desc, url y campos de paridad
    scored = {s.id_externo: s for s in result.top_scored}
    assert scored["L1"].estado_desc == "Adjudicada"
    assert scored["L1"].url == "https://example.org/L1"
    assert scored["L1"].empresa == "EMPRESA UNO"
    assert scored["L1"].tipo_contrato_desc == "Servicios"
    assert scored["L1"].tipo_proyecto is not None


def test_get_organo_detail_unknown_organo():
    with (
        patch(
            "services.analytics.organo_detail.load_stats_dataframe",
            return_value=_lic_rows(),
        ),
        patch(
            "services.analytics.organo_detail.load_raw_adjudicaciones",
            return_value=_adj_rows(),
        ),
    ):
        result = get_organo_detail("ORG INEXISTENTE", OrganoDetailFilters())
    assert result.kpis.total_licitaciones == 0
    assert result.top_scored == []


# ── get_overview (smoke) ────────────────────────────────────────────────────


def test_get_overview_basic():
    with (
        patch(
            "services.analytics.overview.load_stats_dataframe",
            return_value=_lic_rows(),
        ),
        patch(
            "services.analytics.overview.load_adjudicaciones",
            return_value=pd.DataFrame(),
        ),
    ):
        result = get_overview(OverviewFilters())
    assert result.total_licitaciones == 3
    assert result.organos_unicos == 2
    assert result.importe_total == 1_700_000.0
    # CCAA distintas reales (Madrid, Cataluña) — no derivado de concentración
    assert result.ccaa_cubiertas == 2


def test_get_overview_empty():
    with (
        patch("services.analytics.overview.load_stats_dataframe", return_value=[]),
        patch(
            "services.analytics.overview.load_adjudicaciones",
            return_value=pd.DataFrame(),
        ),
    ):
        result = get_overview(OverviewFilters())
    assert result.total_licitaciones == 0
    assert result.ccaa_cubiertas == 0


def test_get_overview_q_filters_titulo_organo_id():
    """El filtro q hace substring case-insensitive sobre titulo/órgano/id,
    en paridad con la búsqueda del listado (KPI bar honesto con q activo)."""
    with (
        patch(
            "services.analytics.overview.load_stats_dataframe",
            return_value=_lic_rows(),
        ),
        patch(
            "services.analytics.overview.load_adjudicaciones",
            return_value=pd.DataFrame(),
        ),
    ):
        por_titulo = get_overview(OverviewFilters(q="sap"))
        por_organo = get_overview(OverviewFilters(q="org b"))
        sin_match = get_overview(OverviewFilters(q="nomatch-xyz"))
    assert por_titulo.total_licitaciones == 1  # "Servicio SAP cloud"
    assert por_organo.total_licitaciones == 1  # L3 (ORG B)
    assert sin_match.total_licitaciones == 0


def test_get_overview_importe_min_excludes_below_and_nan():
    """importe_min filtra como ``importe >= ?`` en SQL (NaN excluido)."""
    rows = _lic_rows()
    rows.append(
        {
            "id_externo": "L5",
            "titulo": "Sin importe",
            "organo_contratacion": "ORG C",
            "importe": None,
            "estado": "PUB",
            "fecha_publicacion": "2025-03-01",
            "ccaa": "Madrid",
            "tipo_contrato": "2",
            "url": None,
            "modulos_str": None,
        }
    )
    with (
        patch("services.analytics.overview.load_stats_dataframe", return_value=rows),
        patch(
            "services.analytics.overview.load_adjudicaciones",
            return_value=pd.DataFrame(),
        ),
    ):
        result = get_overview(OverviewFilters(importe_min=500_000.0))
    # Solo L1 (1M) y L2 (500K); L3 (200K) y L5 (None) quedan fuera.
    assert result.total_licitaciones == 2


def test_get_overview_ccaa_cubiertas_ignores_nulls():
    """ccaa_cubiertas cuenta CCAA distintas reales; las filas con ccaa nulo no
    inflan ni rompen el conteo (Patrón 1 meta-RFC: cobertura real, no derivada)."""
    rows = _lic_rows()  # Madrid, Madrid, Cataluña → 2 distintas
    rows.append(
        {
            "id_externo": "L4",
            "titulo": "Sin CCAA",
            "organo_contratacion": "ORG C",
            "importe": 10_000.0,
            "estado": "PUB",
            "fecha_publicacion": "2025-03-01",
            "ccaa": None,
            "tipo_contrato": "2",
            "url": None,
            "modulos_str": None,
        }
    )
    with (
        patch("services.analytics.overview.load_stats_dataframe", return_value=rows),
        patch(
            "services.analytics.overview.load_adjudicaciones",
            return_value=pd.DataFrame(),
        ),
    ):
        result = get_overview(OverviewFilters())
    # La fila con ccaa=None se excluye → siguen siendo 2 (Madrid, Cataluña).
    assert result.ccaa_cubiertas == 2
